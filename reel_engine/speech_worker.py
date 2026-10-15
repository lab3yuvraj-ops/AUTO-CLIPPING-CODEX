"""Authenticated loopback worker; models stay loaded during one bounded run.

No autonomous analysis: requests come from the local CLI. Idle workers exit.
The private session record is never exported or printed.
"""
import json,os,secrets,subprocess,sys,time
from pathlib import Path
from multiprocessing.connection import Client,Listener
from .config import settings
from .preparation_speed import cpu_budget
from .youtube_transcript import atomic_json

class RunModels:
    def __init__(self,beam,profile=None):
        self.beam=beam
        if profile and profile.get('beam_size')!=beam:profile=None
        self.budget=cpu_budget(profile=profile);self.workers=self.budget['workers'];self.model=None;self.model_load_seconds=0
    def whisper(self):
        if self.model is None:
            from .local_transcription import load_whisper
            start=time.perf_counter()
            self.model=load_whisper(cpu_threads=self.budget['threads'],num_workers=self.workers)
            self.model_load_seconds=time.perf_counter()-start
        return self.model

def serve(root,run):
    root=Path(root);record=root/f'speech-worker-{run}.json';key=secrets.token_bytes(32)
    profile_path=Path(__file__).resolve().parents[1]/'workflow'/'cpu-preparation-profile.json'
    profile=json.loads(profile_path.read_text()) if profile_path.exists() else None
    job=json.loads((root/'job.json').read_text(encoding='utf-8')) if (root/'job.json').exists() else {}
    beam=settings.whisper_beam_size if job.get('careful_sections') else settings.fast_whisper_beam_size
    models=RunModels(beam,profile)
    with Listener(('127.0.0.1',0),authkey=key) as listener:
        listener._listener._socket.settimeout(900)
        atomic_json(record,{'address':listener.address,'auth':key.hex(),'pid':os.getpid(),'run_id':run})
        try:
            while True:
                try:connection=listener.accept()
                except TimeoutError:break
                with connection:
                    request=connection.recv()
                    try:
                        if request['operation']=='stop':connection.send({'stopped':True});break
                        args=request['arguments']
                        if request['operation']=='verify':
                            from .local_transcription import verify_passages
                            timing=request.get('timing')
                            if timing:
                                from .timing import stage
                                args['timing_hook']=lambda name:stage(timing['state'],timing['job'],name,run_id=run)
                            result=verify_passages(**args,beam_size=models.beam,worker=models)
                        elif request['operation']=='transcribe':
                            from .local_transcription import transcribe_local
                            result=transcribe_local(**args,worker=models,beam_size=models.beam)
                        else:raise ValueError('Unsupported speech worker operation')
                        connection.send({'result':result})
                    except Exception as exc:connection.send({'error':str(exc),'kind':type(exc).__name__})
        finally:record.unlink(missing_ok=True)

def request(root,run,operation,arguments=None,timing=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);record=root/f'speech-worker-{run}.json'
    connection=None
    if record.exists():
        try:
            saved=json.loads(record.read_text());connection=Client(tuple(saved['address']),authkey=bytes.fromhex(saved['auth']))
        except (OSError,EOFError):record.unlink(missing_ok=True)
    if connection is None:
        if operation=='stop':return {'stopped':True,'already_stopped':True}
        log=(root/'speech-worker.log').open('ab')
        try:subprocess.Popen([sys.executable,'-m','reel_engine.speech_worker',str(root.resolve()),run],stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        finally:log.close()
        deadline=time.monotonic()+30
        while not record.exists():
            if time.monotonic()>deadline:raise RuntimeError('Local speech worker failed to start; inspect private speech-worker.log')
            time.sleep(.1)
        saved=json.loads(record.read_text());connection=Client(tuple(saved['address']),authkey=bytes.fromhex(saved['auth']))
    with connection:
        connection.send({'operation':operation,'arguments':arguments or {},'timing':timing})
        response=connection.recv()
    if 'error' in response:raise RuntimeError(response['kind']+': '+response['error'])
    return response.get('result',response)

if __name__=='__main__':serve(sys.argv[1],sys.argv[2])
