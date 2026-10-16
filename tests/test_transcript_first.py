import json
from pathlib import Path
import pytest
from reel_engine import transcript_first as workflow
from reel_engine.youtube_transcript import atomic_json


INFO={'id':'abcdefghijk','duration':900.,'title':'New source','availability':'public',
      'formats':[{'height':1080,'vcodec':'h264'}],'language':'en'}


def test_captions_select_before_any_video_or_audio_download(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(workflow.youtube,'ytdlp',lambda args,**kw:calls.append(args) or json.dumps(INFO))
    monkeypatch.setattr(workflow,'fetch_selection_captions',lambda *a,**kw:{'cues':[{'start':1,'end':900,'text':'Story'}]})
    monkeypatch.setattr(workflow,'download_audio',lambda *a:pytest.fail('Captions do not need audio before selection'))
    job=workflow.analyze(tmp_path,'https://youtu.be/abcdefghijk',1,fresh=True)
    assert len(calls)==1 and '--skip-download' in calls[0]
    assert job['download_policy']['full_video_download'] is False
    assert not job.get('proxy') and not job.get('eager_download') and not job.get('source')
    assert Path(job['transcript']).exists() and job['transcript_route']['route']=='captions'


def test_caption_failure_uses_audio_only_draft_once(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(workflow.youtube,'ytdlp',lambda *a,**kw:json.dumps(INFO))
    def fail(*a,**kw):calls.append('caption');raise ValueError('HTTP 429')
    monkeypatch.setattr(workflow,'fetch_selection_captions',fail)
    monkeypatch.setattr(workflow,'download_audio',lambda *a:calls.append('audio') or {'source':'audio.webm','cached':False})
    draft=tmp_path/'draft.json';atomic_json(draft,{'provider':'local-selection-draft','cues':[]})
    monkeypatch.setattr(workflow,'transcribe_selection_draft',lambda *a:calls.append('ASR') or {'transcript':str(draft),'transcription_timings':{}})
    job=workflow.analyze(tmp_path,'https://youtu.be/abcdefghijk',1)
    assert calls==['caption','audio','ASR']
    assert job['transcript_route']['reason']['message']=='HTTP 429'


def test_audio_transfer_never_requests_video_and_validates_streams(tmp_path,monkeypatch):
    calls=[]
    def download(args,**kw):calls.append(args);(tmp_path/'source.webm').write_bytes(b'audio')
    monkeypatch.setattr(workflow.youtube,'ytdlp',download)
    monkeypatch.setattr(workflow.youtube,'transfer_options',lambda *a:[])
    monkeypatch.setattr(workflow,'probe',lambda *a:{'format':{'duration':900},'streams':[{'codec_type':'audio'}]})
    result=workflow.download_audio(INFO,tmp_path)
    assert calls[0][calls[0].index('-f')+1]=='bestaudio'
    assert result['render_eligible'] is False
    assert workflow.download_audio(INFO,tmp_path)['cached'] and len(calls)==1
    assert Path(calls[0][calls[0].index('-o')+1]).name=='source.%(ext)s'


def test_prepare_binds_audio_hash_before_real_verification(tmp_path,monkeypatch):
    from reel_engine import fast
    root=tmp_path/'jobs'/'abcdefghijk-transcript';root.mkdir(parents=True)
    audio=tmp_path/'audio.webm';audio.write_bytes(b'audio')
    job={'id':root.name,'run_id':'run','audio_reference':{'source':str(audio),'source_sha256':fast.file_hash(audio)}}
    def prepare(state,bound,selection):
        saved=json.loads((root/'job.json').read_text())
        assert saved['source_sha256']==fast.file_hash(audio)==bound['source_sha256']
        assert saved['source']==str(audio) and saved['media_kind']=='audio-reference'
        return {'verified':True}
    monkeypatch.setattr(fast,'prepare_selected',prepare)
    assert workflow.prepare(tmp_path,job,'selection.json')['verified']


def selected_fixture(tmp_path,monkeypatch,fail=False):
    from reel_engine import fast,fast_download,speech_worker,detail
    audio=tmp_path/'audio.webm';audio.write_bytes(b'audio')
    section=tmp_path/'section.mkv';section.write_bytes(b'video')
    root=tmp_path/'jobs'/'abcdefghijk-transcript';root.mkdir(parents=True)
    job={'id':root.name,'video_id':'abcdefghijk','run_id':'test','requested_clips':1,'created':0,
         'transcript_first':True,'fast':False,'metadata':{'duration':900},
         'audio_reference':{'source':str(audio),'source_sha256':fast.file_hash(audio),'duration':900}}
    atomic_json(root/'job.json',job);atomic_json(root/'transcript.json',{'language':'en','provider':'youtube-captions'})
    selection=root/'selection.json';atomic_json(selection,{'candidates':[{'start':120.,'end':155.,'reason':'Story','opening':'Hook','ending':'Payoff'}]})
    monkeypatch.setattr(fast.youtube,'ytdlp',lambda *a,**kw:json.dumps(INFO))
    calls=[]
    def transfer(info,folder,a,b,duration):
        calls.append((a,b))
        if fail:raise RuntimeError('HTTP 429')
        return {'source':str(section),'kind':'section','height':1080,'padded_range':[117.,158.]}
    monkeypatch.setattr(fast_download,'download_section',transfer)
    monkeypatch.setattr(fast.youtube,'download',lambda *a,**kw:pytest.fail('Must never fall back to full video'))
    monkeypatch.setattr(fast_download,'confirm_section_audio',lambda *a,**kw:{'offset_verified':True,'source_offset':117.})
    def request(root,run,op,args=None,**kw):
        if op=='stop':return {'stopped':True}
        assert args['ranges']==[[117.,158.]] and args['skip_diarization'] is True
        output=Path(args['root'])/'verified-passages.json'
        atomic_json(output,{'passages':[{'range':[117.,158.],'words':[{'id':'word','start':120.,'end':121.,'confidence':.9}],'signature':'test'}]})
        return {'verified_passages':str(output)}
    monkeypatch.setattr(speech_worker,'request',request)
    def details(source,folder,ranges,**kw):
        assert source==str(section) and ranges==[(3.,38.)]
        return {'passages':[]}
    monkeypatch.setattr(detail,'make_details',details)
    return fast,job,selection,calls


def test_only_selected_video_is_downloaded_and_words_are_mapped(tmp_path,monkeypatch):
    fast,job,selection,calls=selected_fixture(tmp_path,monkeypatch)
    report=fast.prepare_selected(tmp_path,job,selection)
    child=report['clips'][0]
    assert calls==[(120.,155.)]
    assert child['candidate_local']['start']==3 and child['candidate_local']['end']==38
    assert child['review_mode']=='single-pass' and child['transcript_first']
    assert Path(child['details']).exists()
    verified=json.loads(Path(child['verified_words']).read_text())
    assert verified['passages'][0]['words'][0]['start']==3
    assert 'unreviewed' in child['passage_classification']['classification']


def test_section_failure_stops_without_full_video_fallback(tmp_path,monkeypatch):
    fast,job,selection,calls=selected_fixture(tmp_path,monkeypatch,fail=True)
    with pytest.raises(RuntimeError,match='429'):fast.prepare_selected(tmp_path,job,selection)
    assert calls==[(120.,155.)]


