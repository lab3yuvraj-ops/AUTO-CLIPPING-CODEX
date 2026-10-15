import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from reel_engine.preparation_speed import beam_agreement,cpu_budget,diarization_needed
from reel_engine.fast_download import section_range,sections_or_full

def test_padding_ranges_exact_and_bounded():
    assert section_range(1,40,100)==[0,43]
    assert section_range(65,99,100)==[62,100]
    with pytest.raises(ValueError):section_range(65,101,100)

def test_diarization_only_real_mappable_dialogue():
    base={'classification':'multi-speaker dialogue','identity_confident':True}
    assert diarization_needed(base)
    for change in ({'single_narrator':True},{'identity_confident':False},{'screen_identity_mappable':False},{'classification':'single/dominant-presenter'}):
        assert not diarization_needed({**base,**change})

def test_beam_gate_counts_deletions_and_extra_omissions():
    words=[{'id':i,'text':str(i),'start':i,'end':i+.1,'confidence':.9} for i in range(100)]
    assert beam_agreement(words,words)['eligible_for_default']
    assert not beam_agreement(words,words[:-3])['eligible_for_default']
    low=[{**w,'confidence':.1 if w['id']<10 else .9} for w in words]
    assert beam_agreement(words,low)['extra_skipped_percentage_points']==10
    assert not beam_agreement(words,low)['eligible_for_default']

def test_parallel_requires_matching_measured_cpu_improvement():
    assert cpu_budget(16)['workers']==1
    profile={'logical_cores':16,'parallel_seconds':20,'sequential_seconds':30}
    assert cpu_budget(16,profile)['workers']==2
    assert cpu_budget(4,profile)['workers']==1
    assert cpu_budget(16,{**profile,'parallel_seconds':40})['workers']==1

def test_429_sections_attempt_once_and_one_full_fallback(tmp_path,monkeypatch):
    from reel_engine import fast_download as module
    from reel_engine.errors import StageError
    calls=[]
    def section(*a,**k):calls.append('section');raise StageError('HTTP Error 429: Too Many Requests')
    monkeypatch.setattr(module,'download_section',section)
    monkeypatch.setattr(module,'probe',lambda *a:{'streams':[{'codec_type':'video','height':2160}]})
    monkeypatch.setattr(module,'file_hash',lambda *a:'final_hash')
    def full():calls.append('full');return {'source':'original.mkv'}
    result=sections_or_full({},tmp_path,[(10,45),(55,95)],100,full)
    assert calls==['section','full']
    assert all(r['kind']=='full' and r['height']==2160 and r['offset_verified'] is False for r in result)
    assert json.loads((tmp_path/'section-fallback.json').read_text())['cause']['http_status']==429

def test_worker_keeps_one_model_and_uses_tested_thread_budget(monkeypatch):
    from reel_engine.speech_worker import RunModels
    from reel_engine import local_transcription as local
    calls=[]
    monkeypatch.setattr(local,'load_whisper',lambda **k:calls.append(k) or object())
    worker=RunModels(5,{'beam_size':5,'logical_cores':16,'parallel_seconds':20,'sequential_seconds':30})
    assert worker.whisper() is worker.whisper() and len(calls)==1
    assert calls[0]['num_workers'] in (1,2)

def test_proxy_is_never_final_render_source(tmp_path):
    import reel
    with pytest.raises(ValueError,match='proxy pixels'):reel.prepare_edit({'media_kind':'proxy'},{},tmp_path)

def test_careful_section_route_does_not_force_animated_fast_mode():
    from reel_engine.fast import preparation_classifications
    from reel_engine.passage_gate import classify_passage
    evidence={'reviewed_by':'Codex','source_sha256':'h','reason':'Saved actual source review','animated':True,'classification':'multi-speaker dialogue','identity_confident':False}
    assert not classify_passage(evidence,'h')['eligible']
    job={'source_sha256':'h','careful_sections':True,'fast':False}
    classified=preparation_classifications({'candidates':[{'start':1,'end':40,'passage_evidence':evidence}]},job)[0]
    assert classified['eligible'] and classified['careful_identity_review_required']
    assert not classified['diarization_required'] and classified['editorial_warnings']
    assert job['fast'] is False

def test_parallel_batch_runs_each_passage_once(tmp_path,monkeypatch):
    import threading
    import numpy as np
    import soundfile
    from reel_engine import local_transcription as local,render
    source=tmp_path/'source.mkv';source.write_bytes(b'validated-test-source')
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(80*16000,dtype='float32'),16000)
    (tmp_path/'transcript.json').write_text(json.dumps({'provider':'youtube-captions','language':'en'}))
    monkeypatch.setattr(render,'probe',lambda *a:{'format':{'duration':80}})
    barrier=threading.Barrier(2);calls=[]
    class Model:
        def transcribe(self,audio,**kwargs):
            calls.append(kwargs);barrier.wait(timeout=5)
            return iter([NS(words=[NS(start=1,end=1.5,word='hello',probability=.9)])]),None
    model=Model();worker=NS(workers=2,whisper=lambda:model)
    result=local.verify_passages(source,tmp_path,[(1.,36.),(41.,76.)],skip_diarization=True,beam_size=5,worker=worker)
    assert len(calls)==2 and result['cache_hits']==0
    passages=json.loads((tmp_path/'verified-passages.json').read_text())['passages']
    assert all(p['timings']['parallel_batch'] and not p['timings']['asr_checkpoint_reused'] and p['timings']['diarization_seconds']==0 for p in passages)
