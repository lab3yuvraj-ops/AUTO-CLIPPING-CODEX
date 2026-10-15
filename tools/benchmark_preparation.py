"""Replay selected speech on saved media without changing job evidence."""
import sys,json,time,os,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reel_engine.preparation_speed import beam_agreement
from reel_engine.youtube_transcript import atomic_json
from reel_engine.config import settings

def main():
    beam=int(sys.argv[1]) if len(sys.argv)>1 else 1
    import soundfile
    from faster_whisper import WhisperModel
    out=Path('workflow/benchmarks/preparation-20261015');out.mkdir(parents=True,exist_ok=True)
    requests=[]
    for ident in ('krsBRQbOPQ4-fast-1527c559','-ZjLRVNAFKk'):
        root=Path('workflow/jobs')/ident
        data=json.loads((root/'verified-passages.json').read_text(encoding='utf-8'))
        transcript=json.loads((root/'transcript.json').read_text(encoding='utf-8'))
        audio,rate=soundfile.read(root/'local-audio.wav',dtype='float32')
        assert rate==16000 and audio.ndim==1
        for index,p in enumerate(data['passages']):
            a,b=p['range'];requests.append((ident,index,p,audio[round(a*rate):round(b*rate)],transcript))
    threads=max(1,min(12,(os.cpu_count() or 1)));started=time.perf_counter()
    model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=threads,num_workers=2,
        download_root=str(settings.local_model_dir/'whisper'),local_files_only=True)
    load=time.perf_counter()-started
    def execute(req):
        ident,index,p,audio,transcript=req;a,b=p['range'];start=time.perf_counter()
        segments,_=model.transcribe(audio,language=transcript.get('language','en').split('-')[0],beam_size=beam,word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
        words=[{'id':i,'text':w.word.strip(),'start':w.start+a,'end':w.end+a,'confidence':w.probability} for i,w in enumerate(w for s in segments for w in s.words or [] if w.word.strip())]
        return {'job':ident,'passage':index+1,'range':p['range'],'seconds':time.perf_counter()-start,'words':words,
                'comparison':beam_agreement(p['words'],words,transcript.get('cues',[]))}
    start=time.perf_counter();sequential=[execute(req) for req in requests];seq=time.perf_counter()-start
    atomic_json(out/f'beam-{beam}-sequential.json',{'model_load_seconds':load,'seconds':seq,'passages':sequential,'threads':threads})
    print(json.dumps({'sequential_seconds':seq,'comparisons':[r['comparison'] for r in sequential]}),flush=True)
    threads=max(1,min(12,(os.cpu_count() or 1)//2));start=time.perf_counter()
    model=WhisperModel('small',device='cpu',compute_type='int8',cpu_threads=threads,num_workers=2,download_root=str(settings.local_model_dir/'whisper'),local_files_only=True)
    parallel_load=time.perf_counter()-start;start=time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:parallel=list(pool.map(execute,requests))
    par=time.perf_counter()-start
    report={'beam_size':beam,'model_load_seconds':load,'parallel_model_load_seconds':parallel_load,'logical_cores':os.cpu_count(),'threads_per_passage':threads,'sequential_seconds':seq,'parallel_seconds':par,'parallel_beneficial':par<seq,'passages':parallel,
            'beam1_default_accepted':all(r['comparison']['eligible_for_default'] for r in parallel),
            'cached':'Source media, extracted audio, model files and beam-5 reference reused. Beam-1 ASR fresh; model remains loaded between sequential and parallel experiments.'}
    atomic_json(out/f'beam-{beam}-benchmark.json',report)
    atomic_json(Path('workflow/cpu-preparation-profile.json'),{k:report[k] for k in ('beam_size','logical_cores','threads_per_passage','sequential_seconds','parallel_seconds')})
    print(json.dumps({k:v for k,v in report.items() if k!='passages'}),flush=True)
if __name__=='__main__':main()
