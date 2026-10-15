from types import SimpleNamespace
import numpy as np
import soundfile
import pytest
from reel_engine import local_transcription as speech


def test_batch_checks_load_one_model_and_invalidate_when_audio_changes(monkeypatch,tmp_path):
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(16000,dtype=np.float32),16000)
    loads=[];requests=[]
    class Model:
        def transcribe(self,audio,**kwargs):
            requests.append(audio.copy())
            word=SimpleNamespace(start=.1,end=.2,word='test',probability=.9)
            return iter([SimpleNamespace(words=[word])]),None
    def load():loads.append(True);return Model()
    monkeypatch.setattr(speech,'load_whisper',load)
    first=speech.recheck_local(tmp_path,[(0,.5),(.5,1)])
    assert len(loads)==1 and len(requests)==2
    assert first['rechecks'][1]['words'][0]['start']==pytest.approx(.6)
    assert all(c['cache_reused'] for c in speech.recheck_local(tmp_path,[(0,.5),(.5,1)])['rechecks'])
    assert len(requests)==2
    soundfile.write(tmp_path/'local-audio.wav',np.ones(16000,dtype=np.float32)*.2,16000)
    speech.recheck_local(tmp_path,[(0,.5)])
    assert len(requests)==3
    with pytest.raises(ValueError,match='outside'):speech.recheck_local(tmp_path,[(0,2)])


@pytest.mark.parametrize('fast',[False,True])
def test_child_recheck_audio_is_final_source_bound_cpu_and_reused(monkeypatch,tmp_path,fast):
    from reel_engine import render
    source=tmp_path/'source.mkv';source.write_bytes(b'source');calls=[]
    def run(args):
        calls.append(args);soundfile.write(args[-1],np.zeros(16000,dtype=np.float32),16000)
    monkeypatch.setattr(render,'run',run)
    job={'source':str(source),'source_sha256':render.file_hash(source),'fast':fast}
    audio=speech.ensure_recheck_audio(job,tmp_path)
    assert audio.exists() and len(calls)==1
    assert calls[0][calls[0].index('-hwaccel')+1]=='none'
    assert calls[0][calls[0].index('-i')+1]==str(source)
    speech.ensure_recheck_audio(job,tmp_path);assert len(calls)==1
    audio.write_bytes(b'changed');speech.ensure_recheck_audio(job,tmp_path);assert len(calls)==2
    source.write_bytes(b'wrong')
    with pytest.raises(ValueError,match='Final source changed'):speech.ensure_recheck_audio(job,tmp_path)
