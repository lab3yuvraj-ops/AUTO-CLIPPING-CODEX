import json
import threading
from pathlib import Path
from types import SimpleNamespace as NS
from contextlib import contextmanager
import numpy as np
import pytest
import soundfile
from reel_engine import original_captions as captions,passage_gate,local_transcription as local,render,youtube
from reel_engine.caption_errors import CaptionFetchError
from reel_engine.speaker_camera import build_speaker_camera
from reel_engine.tracking import crop_centers


def evidence(kind,**extra):return {'reviewed_by':'Codex','source_sha256':'source','reason':'Whole-source ranking and actual selected speech/frames were reviewed.','classification':kind,'animated':False,'identity_confident':True,**extra}


def test_mixed_source_classifies_each_passage_and_never_rejects_dialogue_count():
    selection={'candidates':[{'start':5,'end':40,'passage_evidence':evidence('single/dominant-presenter')},{'start':55,'end':95,'passage_evidence':evidence('multi-speaker dialogue',speaker_count=4)}]}
    reports=passage_gate.classify_selection(selection,'source')
    assert all(r['eligible'] for r in reports)
    assert [r['diarization_required'] for r in reports]==[False,True]
    assert reports[1]['crop_strategy']=='speaker-switching'
    animated=passage_gate.classify_passage(evidence('multi-speaker dialogue',animated=True),'source')
    assert not animated['eligible'] and animated['fallback']=='full'
    unknown=passage_gate.classify_passage(evidence('unknown'),'source')
    assert not unknown['eligible'] and unknown['fallback']=='full'


def test_uncertain_identity_is_eligible_but_stable_with_visible_review_flag():
    result=passage_gate.classify_passage(evidence('multi-speaker dialogue',identity_confident=False,speakers_too_far_apart=True),'source')
    assert result['eligible'] and result['requires_stable_context'] and result['editorial_warnings'] and result['prefer_alternative']
    plan=build_speaker_camera([{'start':0,'end':2,'speaker':'A'},{'start':2,'end':4,'speaker':'B'}],[{'id':'shot','start':0,'end':4,'stable_center':.42,'evidence':'Reviewed context composition preserves the discussed object.'}],[])
    assert crop_centers(plan,[],[0,1,2,3])==[.42]*4 and plan['unresolved']


def test_fast_policy_honors_retry_after_once_and_then_stops(tmp_path,monkeypatch):
    calls=[];waits=[];started=[]
    def fail(*a,**k):calls.append(True);raise RuntimeError('HTTP Error 429\nRetry-After: 7')
    monkeypatch.setattr(captions.youtube,'ytdlp',fail)
    info={'id':'abcdefghijk','language':'en','subtitles':{'en':[{'ext':'json3'}]}}
    with pytest.raises(CaptionFetchError):captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info,sleep=waits.append,max_attempts=2,cache_dir=tmp_path/'cache',on_failure=started.append)
    assert len(calls)==2 and waits==[7] and started[0]['retry_after']=='7'


def test_ready_asr_cancels_pending_caption_retry_without_shortening_retry_after(tmp_path,monkeypatch):
    calls=[];event=threading.Event();event.set()
    def fail(*a,**k):calls.append(True);raise RuntimeError('HTTP Error 429\nRetry-After: 60')
    monkeypatch.setattr(captions.youtube,'ytdlp',fail)
    info={'language':'en','subtitles':{'en':[{'ext':'json3'}]}}
    with pytest.raises(CaptionFetchError) as exc:captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info,sleep=lambda _:pytest.fail('Do not wait on captions after ASR'),max_attempts=2,cache_dir=tmp_path/'cache',stop_wait=event)
    assert len(calls)==1 and exc.value.diagnostic['retry_cancelled']


def test_one_batch_reuses_whole_asr_words_and_only_diarizes_dialogue_range(tmp_path,monkeypatch):
    source=tmp_path/'proxy.mkv';source.write_bytes(b'proxy')
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(100*16000,dtype=np.float32),16000)
    (tmp_path/'transcript.json').write_text(json.dumps({'provider':'local-asr-draft','source_sha256':render.file_hash(source),'models':{'transcription':'small'},'beam_size':5,'language':'en','words':[{'start':8.,'end':9.,'text':'Hello','confidence':.99},{'start':58.,'end':59.,'text':'Answer','confidence':.99}]}))
    monkeypatch.setattr(render,'probe',lambda _: {'format':{'duration':'100'}})
    monkeypatch.setattr(local,'load_whisper',lambda:pytest.fail('Reuse existing audio-bound word timings'))
    calls=[];loads=[];marks=[]
    def pipeline(data):
        duration=data['waveform'].shape[1]/16000;calls.append(duration)
        return NS(itertracks=lambda **kwargs:iter([(NS(start=0,end=duration/2),None,'A'),(NS(start=duration/2,end=duration),None,'B')]))
    monkeypatch.setattr(local,'load_diarization',lambda:loads.append(True) or pipeline)
    @contextmanager
    def hook(name):
        marker={'name':name};marks.append(marker);yield marker
    result=local.verify_passages(source,tmp_path,[(7.,48.),(57.,98.)],skip_diarization=[True,False],timing_hook=hook)
    saved=json.loads(Path(result['verified_passages']).read_text())
    assert calls==[41.] and loads==[True]
    assert all(p['timings']['full_source_asr_reused'] for p in saved['passages'])
    assert [p['words'][0]['text'] for p in saved['passages']]==['Hello','Answer']
    assert saved['passages'][0]['speaker_turns'][0]['speaker']=='DOMINANT_SPEAKER'
    assert all(t['speaker'].startswith(saved['passages'][1]['signature'][:12]) for t in saved['passages'][1]['speaker_turns'])
    assert all(m['cached'] for m in marks if 'words_reused' in m['name'])


def test_complete_audio_rejects_partials_and_sparse_controls(tmp_path):
    import subprocess
    source=tmp_path/'source.f251.webm'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=3','-c:a','libopus',str(source)],check=True,capture_output=True)
    assert youtube.complete_audio(source,3)
    control=Path(str(source)+'.aria2');control.touch()
    assert not youtube.complete_audio(source,3)
    control.unlink();Path(str(source)+'.part').touch()
    assert not youtube.complete_audio(source,3)


def test_selected_review_hash_guard_and_classification_record(tmp_path):
    page=tmp_path/'actual-page.jpg';page.write_bytes(b'actual selected frame sheet')
    hashes={str(page):render.file_hash(page)}
    selection={'candidates':[{'start':5,'end':40,'passage_evidence':evidence('multi-speaker dialogue',reviewed_page_hashes=hashes)}]}
    (tmp_path/'selected-details.json').write_text(json.dumps({'passages':[{'range':[5,40],'source_sha256':'source','page_files':[{'file':str(page),'sha256':render.file_hash(page)}]}]}))
    passage_gate.require_selected_review(tmp_path,selection,'source')
    page.write_bytes(b'changed')
    with pytest.raises(ValueError,match='unchanged'):passage_gate.require_selected_review(tmp_path,selection,'source')


def test_early_audio_binding_requires_exact_pcm_before_word_reuse(tmp_path):
    import subprocess
    from reel_engine.proxy_asr import bind_proxy_asr
    audio=tmp_path/'audio.wav'
    soundfile.write(audio,np.sin(np.arange(16000*3)/16000*2*np.pi*440)*.2,16000,subtype='PCM_16')
    video=tmp_path/'proxy.mkv'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=blue:size=160x90:rate=30:duration=3','-i',str(audio),'-c:v','libx264','-c:a','pcm_s16le','-shortest',str(video)],check=True,capture_output=True)
    asr=tmp_path/'asr';asr.mkdir();root=tmp_path/'job';root.mkdir()
    __import__('shutil').copyfile(audio,asr/'local-audio.wav')
    data={'provider':'local-asr-draft','source_sha256':render.file_hash(audio),'models':{'transcription':'small','compute_type':'int8'},'words':[{'start':1,'end':1.5,'text':'Hello','confidence':.99}],'beam_size':5,'device':'cpu'}
    (asr/'transcript.json').write_text(json.dumps(data))
    bound=bind_proxy_asr(audio,asr,{'source':str(video),'source_sha256':render.file_hash(video)},root)
    assert bound['source_sha256']==render.file_hash(video) and bound['audio_equivalence']['identical_pcm']
    assert bound['words']==data['words'] and bound['asr_original_source_sha256']==render.file_hash(audio)


def test_preparation_preserves_revision_and_publication_records(tmp_path):
    from reel_engine.fast import save_clip_record
    path=tmp_path/'job.json';old={'id':'abcdefghijk','edit_spec_hash':'reviewed edit','keep_lossless':True,'video':'saved.mp4','approval':{'old':True}}
    path.write_text(json.dumps(old))
    saved=save_clip_record(tmp_path,{'id':'abcdefghijk','status':'Awaiting Codex edit'})
    assert saved['keep_lossless'] and saved['edit_spec_hash']=='reviewed edit' and saved['video']=='saved.mp4' and 'approval' not in saved
    saved['publishing']={'pending':True};path.write_text(json.dumps(saved));before=path.read_bytes()
    with pytest.raises(ValueError,match='preserved'):save_clip_record(tmp_path,{'id':'abcdefghijk'})
    assert path.read_bytes()==before
