import hashlib
import json
from types import SimpleNamespace as NS

import numpy as np
import pytest
import soundfile

import reel
from reel_engine import local_transcription as speech
from reel_engine import youtube_transcript as yt


def test_whole_source_asr_defers_speakers_and_recovers_checkpoint(monkeypatch,tmp_path):
    source=tmp_path/'source';source.write_bytes(b'video')
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(16000),16000)
    calls=[]
    class Model:
        def transcribe(self,*args,**kwargs):
            calls.append(kwargs)
            return iter([NS(words=[NS(start=.1,end=.2,word='Hello',probability=.95)])]),NS(language='en')
    monkeypatch.setattr(speech,'load_whisper',lambda:Model())
    monkeypatch.setattr(speech,'load_models',lambda:pytest.fail('No whole-source speaker load'))
    speech.transcribe_local(source,tmp_path)
    draft=json.loads((tmp_path/'transcript.json').read_text())
    assert draft['provider']=='local-asr-draft' and draft['requires_selected_verification']
    assert draft['words'][0]['speaker']=='UNKNOWN' and draft['beam_size']==5
    assert calls[0]['language'] is None and calls[0]['beam_size']==5
    (tmp_path/'transcript.json').unlink()
    speech.transcribe_local(source,tmp_path)
    assert len(calls)==1
    (tmp_path/'transcript.json').unlink();source.write_bytes(b'changed video')
    speech.transcribe_local(source,tmp_path)
    assert len(calls)==2


def test_selected_speakers_reuse_full_source_word_times(monkeypatch,tmp_path):
    source=tmp_path/'source';source.write_bytes(b'video')
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(60*16000),16000)
    yt.atomic_json(tmp_path/'transcript.json',{
        'provider':'local-asr-draft','source_sha256':hashlib.sha256(b'video').hexdigest(),
        'models':{'transcription':speech.settings.whisper_model},'beam_size':5,'language':'en',
        'words':[{'id':1,'start':11,'end':12,'text':'Hello','confidence':.95}]})
    monkeypatch.setattr('reel_engine.render.probe',lambda p:{'format':{'duration':'60'}})
    class Whisper:
        def transcribe(self,*args,**kwargs):pytest.fail('Do not transcribe selected speech twice')
    class Pipeline:
        def __call__(self,arg):
            return NS(itertracks=lambda **kwargs:iter([(NS(start=0,end=5),None,'SPEAKER_00')]))
    monkeypatch.setattr(speech,'load_models',lambda:(Whisper(),Pipeline()))
    monkeypatch.setattr(speech,'load_diarization',lambda:Pipeline())
    speech.verify_passages(source,tmp_path,[(10,45)])
    passage=json.loads((tmp_path/'verified-passages.json').read_text())['passages'][0]
    assert passage['words'][0]['start']==11 and passage['words'][0]['end']==12
    assert passage['timings']['full_source_asr_reused']
    job={'transcript':str(tmp_path/'transcript.json'),'source_sha256':hashlib.sha256(b'video').hexdigest()}
    word=passage['words'][0]
    spec={'candidate':{'start':10,'end':45},'words':[word]}
    yt.require_verified_words(job,spec)
    spec['words']=[{**word,'end':13}]
    with pytest.raises(ValueError,match='timing'):yt.require_verified_words(job,spec)


def test_rechecks_use_detected_language_and_bound_overlapping_work(monkeypatch,tmp_path):
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(10*16000),16000)
    yt.atomic_json(tmp_path/'transcript.json',{'language':'en'})
    calls=[]
    class Model:
        def transcribe(self,*args,**kwargs):
            calls.append(kwargs)
            return iter([NS(words=[NS(start=.1,end=.2,word='Hello',probability=.9)])]),None
    monkeypatch.setattr(speech,'load_whisper',lambda:Model())
    speech.recheck_local(tmp_path,[(0,3),(0,4)])
    third=speech.recheck_local(tmp_path,[(0,5)])['rechecks'][0]
    assert third['status']=='needs_human_review' and len(calls)==2
    assert all(c['language']=='en' and c['beam_size']==5 for c in calls)
    assert speech.recheck_local(tmp_path,[(0,3)])['rechecks'][0]['cache_reused']
    speech.recheck_local(tmp_path,[(0,5)],force=True)
    assert len(calls)==3
    with pytest.raises(ValueError):speech.recheck_local(tmp_path,[(float('nan'),2)])


def test_batch_preserves_completed_clips_when_another_fails(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path/'workflow')
    for ident in ('testvideo01','testvideo02'):
        reel.save(reel.job_path(ident),{'id':ident})
    (tmp_path/'edit.json').write_text('{}')
    manifest=tmp_path/'batch.json'
    reel.save(manifest,[{'job':ident,'edit':'edit.json'} for ident in ('testvideo01','testvideo02')])
    def review(ident,edit):
        if ident=='testvideo02':raise RuntimeError('secret provider response')
        return {'pages':['preview.jpg']}
    monkeypatch.setattr(reel,'review',review)
    result=reel.batch(manifest,'review')
    assert result['results'][0]['ok'] and not result['results'][1]['ok']
    assert not result['publication_authorized'] and 'secret' not in json.dumps(result)
    reel.save(manifest,[{'job':'testvideo01','edit':'edit.json'}]*2)
    with pytest.raises(ValueError,match='distinct'):reel.batch(manifest,'review')


def test_failed_draft_fetch_not_repeated_after_download(monkeypatch,tmp_path):
    calls=[]
    def fail(*args):
        calls.append(1);raise RuntimeError('secret signed URL')
    monkeypatch.setattr(yt,'_fetch_caption_draft',fail)
    with pytest.raises(RuntimeError):yt.fetch_caption_draft('testvideo01',tmp_path,60)
    with pytest.raises(ValueError,match='recently failed'):yt.fetch_caption_draft('testvideo01',tmp_path,60)
    assert len(calls)==1
    saved=json.loads((tmp_path/'caption-fetch-failure.json').read_text())
    assert 'secret' not in json.dumps(saved)
    saved['retry_after']=0;yt.atomic_json(tmp_path/'caption-fetch-failure.json',saved)
    with pytest.raises(RuntimeError):yt.fetch_caption_draft('testvideo01',tmp_path,60)
    assert len(calls)==2
