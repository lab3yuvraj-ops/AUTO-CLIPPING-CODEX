"""Best-effort sampled CPU/RAM metrics; no argument, credential or payload logging."""
import contextlib
import importlib.util
import json
import threading
import time
from pathlib import Path


@contextlib.contextmanager
def measure(root,stage,interval=.2):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    result={'stage':stage,'resource_metrics_available':False,'cpu_seconds_sampled':None,
            'peak_rss_bytes_sampled':None,'full_render_attempts':int(stage=='render'),
            'api_calls':0,'api_cost':0,'api_cost_scope':'This local CPU stage only, excluding hardware/electricity'}
    stop=threading.Event();thread=None;start=time.perf_counter()
    if importlib.util.find_spec('psutil'):
        import psutil
        owner=psutil.Process();cpu={};initial={};peak=[0]
        def sample():
            try:processes=[owner,*owner.children(recursive=True)]
            except psutil.Error:return
            rss=0
            for process in processes:
                try:
                    key=(process.pid,process.create_time());t=process.cpu_times();value=t.user+t.system
                    initial.setdefault(key,value if process.pid==owner.pid else 0.)
                    cpu[key]=max(cpu.get(key,0),value-initial[key]);rss+=process.memory_info().rss
                except psutil.Error:continue
            peak[0]=max(peak[0],rss)
        def watch():
            while not stop.wait(interval):sample()
        sample();thread=threading.Thread(target=watch,daemon=True);thread.start()
        result['resource_metrics_available']=True
    try:
        yield result
        result['succeeded']=True
    except BaseException:
        result['succeeded']=False
        raise
    finally:
        stop.set()
        if thread:
            thread.join(timeout=2);sample()
            result.update(cpu_seconds_sampled=sum(cpu.values()),peak_rss_bytes_sampled=peak[0])
        result['wall_seconds']=time.perf_counter()-start
        result['resource_note']='Sampled process-tree RSS/CPU; short-lived processes between samples may be missed. Not an OS peak-memory guarantee.'
        with (root/'performance-metrics.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(result)+'\n')


def summarize(root):
    root=Path(root)
    path=Path(root)/'performance-metrics.jsonl'
    records=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()] if path.exists() else []
    semantic_path=root/'gemini-attempts.jsonl'
    semantic=[json.loads(line) for line in semantic_path.read_text(encoding='utf8').splitlines() if line.strip()] if semantic_path.exists() else []
    semantic_usage={}
    for record in semantic:
        for key,value in record.get('provider_usage',{}).items():semantic_usage[key]=semantic_usage.get(key,0)+value
    rounds=root/'correction-rounds.json';reviews=root/'interactive-phases.jsonl'
    versions=json.loads(rounds.read_text(encoding='utf8')).get('versions',[]) if rounds.exists() else []
    passes=[json.loads(line) for line in reviews.read_text(encoding='utf8').splitlines() if line.strip()] if reviews.exists() else []
    artifacts={}
    for name in ('review/review.json','final-mp4-review/review.json'):
        p=root/name
        if p.exists():
            d=json.loads(p.read_text(encoding='utf8'));artifacts[name]={'pages':len(d.get('pages',[])),'samples':len(d.get('samples',d.get('sample_seconds',[]))),
                'cache_reused':d.get('cache_reused'),'scope':'Most recent artifact, not historical frame-view count'}
    return {'records':records,'gemini':{'invocations':len(semantic),
            'inference_calls':sum(r.get('api_calls_this_run',0) for r in semantic),
            'management_requests':sum(r.get('management_requests',0) for r in semantic),
            'api_latency_seconds':sum(r.get('api_latency_seconds',0) for r in semantic),
            'backoff_seconds':sum(r.get('backoff_seconds',0) for r in semantic),
            'cache_hits':sum(bool(r.get('cache_reused')) for r in semantic),'provider_usage':semantic_usage,
            'estimated_api_cost':sum(r.get('estimated_api_cost',0) for r in semantic),
            'quality_pass_claimed':False},'full_render_attempts':sum(r['full_render_attempts'] for r in records),
            'correction_rounds':max(0,len(versions)-1),'review_phases_completed':sum(p.get('phase')=='review_pass' and p.get('event')=='end' for p in passes),
            'review_artifacts':artifacts,
            'peak_rss_bytes_sampled':max((r.get('peak_rss_bytes_sampled') or 0 for r in records),default=0) or None,
            'note':'Stage wall times may overlap; do not sum as total workflow wall time.'}
