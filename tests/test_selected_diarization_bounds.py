"""Selected speech batches must never expand into whole-source diarization."""
from types import SimpleNamespace
import numpy as np
import soundfile
from reel_engine import local_transcription as local, render


def test_two_padded_passages_share_one_model_load_and_bound_diarization(tmp_path,monkeypatch):
    source=tmp_path/'proxy.mkv';source.write_bytes(b'proxy evidence')
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(100*16000,dtype=np.float32),16000)
    monkeypatch.setattr(render,'probe',lambda _: {'format':{'duration':'100'}})
    calls=[];loads=[];asr=[]
    class Whisper:
        def transcribe(self,portion,**kwargs):
            asr.append(len(portion)/16000)
            word=SimpleNamespace(start=1.,end=2.,word='Hello',probability=.98)
            return iter([SimpleNamespace(words=[word])]),None
    class Annotation:
        def __init__(self,duration):self.duration=duration
        def itertracks(self,yield_label):
            return iter([(SimpleNamespace(start=0.,end=self.duration),None,'speaker_a')])
    def pipeline(data):
        duration=data['waveform'].shape[1]/data['sample_rate'];calls.append(duration)
        return Annotation(duration)
    def models():loads.append(True);return Whisper(),pipeline
    monkeypatch.setattr(local,'load_models',models)
    result=local.verify_passages(source,tmp_path,[(7.,48.),(57.,98.)],skip_diarization=False)
    assert len(loads)==1
    assert calls==[41.,41.] and asr==[41.,41.]
    assert result['ranges']==[[7.,48.],[57.,98.]]
