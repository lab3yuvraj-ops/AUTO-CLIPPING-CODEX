import json
from pathlib import Path
import pytest
from reel_engine import youtube_transcript as yt


def fixture():
    return {'events':[{'tStartMs':i*1000,'dDurationMs':1000,'segs':[{'utf8':'एक कहानी यहाँ है'}]} for i in range(60)]}


def test_cues_remain_draft_and_do_not_invent_word_timing():
    data=fixture();data['events'].insert(1,data['events'][0])
    result=yt.parse_json3(data,60)
    assert len(result['cues'])==60
    assert result['words']==[] and result['requires_selected_verification']
    assert result['cues'][-1]['end']==60


def test_incomplete_track_rejected():
    with pytest.raises(ValueError):yt.parse_json3({'events':fixture()['events'][:10]},60)
    data=fixture();data['events']=data['events'][:5]+data['events'][55:]
    with pytest.raises(ValueError,match='gap'):yt.parse_json3(data,60)


def test_challenge_falls_back_without_leaking_provider_payload(monkeypatch,tmp_path):
    import reel_engine.local_transcription as local
    def fail(*args):raise RuntimeError('secret signed URL')
    monkeypatch.setattr(yt,'fetch_caption_draft',fail)
    monkeypatch.setattr('reel_engine.render.probe',lambda p:{'format':{'duration':'60'}})
    calls=[]
    monkeypatch.setattr(local,'transcribe_local',lambda *args:calls.append(args) or {'transcript':'local.json'})
    assert yt.transcript_for_selection('source',tmp_path,'testvideo01')['transcript']=='local.json'
    assert len(calls)==1 and 'secret' not in (tmp_path/'caption-fallback.json').read_text()


def test_existing_full_transcript_is_never_replaced(monkeypatch,tmp_path):
    original={'provider':'local','words':[{'text':'saved'}]}
    yt.atomic_json(tmp_path/'transcript.json',original)
    monkeypatch.setattr(yt,'fetch_caption_draft',lambda *args:pytest.fail('No new download'))
    result=yt.transcript_for_selection('source',tmp_path,'testvideo01')
    assert result['transcription_timings']['checkpoint_reused']
    assert json.loads((tmp_path/'transcript.json').read_text())==original


def test_fetch_uses_original_not_translated_track(monkeypatch,tmp_path):
    calls=[]
    def downloader(args,**kwargs):
        calls.append(args)
        if '--dump-single-json' in args:
            return json.dumps({'automatic_captions':{'hi':[], 'hi-orig':[], 'en':[]}})
        (tmp_path/'youtube-captions.hi-orig.json3').write_text(json.dumps(fixture()),encoding='utf-8')
        return ''
    monkeypatch.setattr(yt.youtube,'ytdlp',downloader)
    result=yt.fetch_caption_draft('testvideo01',tmp_path,60)
    assert result['language']=='hi-orig'
    assert calls[1][calls[1].index('--sub-langs')+1]=='hi-orig'
    assert len(yt.fetch_caption_draft('testvideo01',tmp_path,60)['cues'])==60
    assert len(calls)==2


def test_native_track_mismatch_falls_back_instead_of_selecting_first_language(monkeypatch,tmp_path):
    info={'language':'en-US','automatic_captions':{'ar-orig':[],'hi-orig':[]}}
    monkeypatch.setattr(yt.youtube,'ytdlp',lambda *a,**k:pytest.fail('No wrong-language fetch'))
    with pytest.raises(ValueError,match='original automatic caption'):
        yt.fetch_caption_draft('testvideo01',tmp_path,60,info)


def test_wrong_language_cached_draft_is_not_reused(monkeypatch,tmp_path):
    yt.atomic_json(tmp_path/'youtube-transcript.json',{'video_id':'testvideo01','language':'ar','text':'wrong'})
    monkeypatch.setattr(yt.youtube,'ytdlp',lambda *a,**k:pytest.fail('No wrong-language fetch'))
    with pytest.raises(ValueError,match='original automatic caption'):
        yt.fetch_caption_draft('testvideo01',tmp_path,60,{'language':'en-US','automatic_captions':{'ar-orig':[]}})


def test_full_local_override_preserves_draft(monkeypatch,tmp_path):
    from reel_engine import local_transcription as local
    yt.atomic_json(tmp_path/'transcript.json',{'provider':'youtube-captions','text':'Draft'})
    def full(source,root):
        assert not (root/'transcript.json').exists()
        assert json.loads((root/'youtube-transcript.json').read_text())['text']=='Draft'
        return {'transcript':'new-local'}
    monkeypatch.setattr(local,'transcribe_local',full)
    assert yt.transcript_for_selection('source',tmp_path,'testvideo01',True)['transcript']=='new-local'


def test_render_blocks_draft_timing_and_wrong_source(tmp_path):
    transcript=tmp_path/'transcript.json';yt.atomic_json(transcript,{'provider':'youtube-captions'})
    job={'transcript':str(transcript),'source_sha256':'abc'}
    spec={'candidate':{'start':10,'end':45},'words':[{'id':1,'start':11,'end':12}]}
    with pytest.raises(ValueError,match='verify'):yt.require_verified_words(job,spec)
    yt.atomic_json(tmp_path/'verified-passages.json',{'source_sha256':'abc','passages':[{'range':[9,46],'words':[{'id':1,'start':11,'end':12}]}]})
    yt.require_verified_words(job,spec)
    spec['words'][0]['end']=13
    with pytest.raises(ValueError,match='timing'):yt.require_verified_words(job,spec)
    job['source_sha256']='different'
    with pytest.raises(ValueError,match='different source'):yt.require_verified_words(job,spec)


def test_scoped_verification_preserves_offsets_and_reuses_cache(monkeypatch,tmp_path):
    from reel_engine import local_transcription as local
    import numpy as np
    source=tmp_path/'source';source.write_bytes(b'media');(tmp_path/'local-audio.wav').touch()
    yt.atomic_json(tmp_path/'transcript.json',{'provider':'youtube-captions'})
    monkeypatch.setattr('reel_engine.render.probe',lambda p:{'format':{'duration':'200'}})
    monkeypatch.setattr('soundfile.read',lambda *a,**k:(np.zeros(200*16000,dtype=np.float32),16000))
    from types import SimpleNamespace as NS
    class Whisper:
        def transcribe(self,*args,**kwargs):
            assert kwargs['beam_size']==5
            return iter([NS(words=[NS(start=1,end=2,word='नमस्ते',probability=.95)])]),None
    class Pipeline:
        def __call__(self,arg):
            return NS(itertracks=lambda **kwargs:iter([(NS(start=0,end=5),None,'SPEAKER_00')]))
    calls=[]
    monkeypatch.setattr(local,'load_models',lambda:calls.append(1) or (Whisper(),Pipeline()))
    local.verify_passages(source,tmp_path,[(10,45),(100,140)])
    evidence=json.loads((tmp_path/'verified-passages.json').read_text(encoding='utf-8'))
    assert [p['words'][0]['start'] for p in evidence['passages']]==[11,101]
    assert evidence['passages'][0]['words'][0]['id']!=evidence['passages'][1]['words'][0]['id']
    local.verify_passages(source,tmp_path,[(10,45),(100,140)])
    assert calls==[1]
    assert json.loads((tmp_path/'transcript.json').read_text())['provider']=='youtube-captions'


def test_speaker_failure_reuses_successful_asr_checkpoint(monkeypatch,tmp_path):
    from reel_engine import local_transcription as local
    import numpy as np
    from types import SimpleNamespace as NS
    source=tmp_path/'source';source.write_bytes(b'media');(tmp_path/'local-audio.wav').touch()
    yt.atomic_json(tmp_path/'transcript.json',{'provider':'youtube-captions'})
    monkeypatch.setattr('reel_engine.render.probe',lambda p:{'format':{'duration':'60'}})
    monkeypatch.setattr('soundfile.read',lambda *a,**k:(np.zeros(60*16000,dtype=np.float32),16000))
    calls=[];fail=[True]
    class Whisper:
        def transcribe(self,*args,**kwargs):
            calls.append(1)
            return iter([NS(words=[NS(start=1,end=2,word='नमस्ते',probability=.95)])]),None
    class Pipeline:
        def __call__(self,arg):
            if fail[0]:raise RuntimeError('interrupted diarization')
            return NS(itertracks=lambda **kwargs:iter([(NS(start=0,end=5),None,'SPEAKER_00')]))
    monkeypatch.setattr(local,'load_models',lambda:(Whisper(),Pipeline()))
    with pytest.raises(RuntimeError):local.verify_passages(source,tmp_path,[(10,45)])
    fail[0]=False
    local.verify_passages(source,tmp_path,[(10,45)])
    assert calls==[1]
    evidence=json.loads((tmp_path/'verified-passages.json').read_text(encoding='utf-8'))
    assert evidence['passages'][0]['timings']['asr_checkpoint_reused']
    assert evidence['passages'][0]['words'][0]['start']==11
