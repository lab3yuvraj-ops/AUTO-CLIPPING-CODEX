"""One bounded download process for the current run, never a scheduler."""
import json,os,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace
from .youtube_transcript import atomic_json


def start(state,job,info):
    root=Path(state)/'jobs'/job['id'];run=job['run_id']
    log=(root/'eager-download.log').open('ab')
    try:
        process=subprocess.Popen([sys.executable,'-m','reel_engine.eager_download',str(Path(state).resolve()),job['id'],run],stdin=subprocess.PIPE,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        process.stdin.write(json.dumps(info).encode('utf-8'));process.stdin.close()
    finally:log.close()
    return {'run_id':run,'pid':process.pid,'status':'started','result':str((root/f'eager-full-{run}.json').resolve())}


def await_result(receipt,timeout=960):
    deadline=time.monotonic()+timeout;path=Path(receipt['result'])
    while not path.exists():
        if time.monotonic()>=deadline:raise RuntimeError('Full-quality transfer did not finish within its bounded wait; inspect eager-download.log.')
        time.sleep(.2)
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('failure'):raise RuntimeError(result['failure'])
    return result


def work(state,ident,run,info):
    from .config import settings
    from . import youtube
    from .render import file_hash
    from .timing import stage
    from .caption_errors import sanitize_message
    root=Path(state)/'jobs'/ident;path=root/f'eager-full-{run}.json'
    try:
        accepted_path=root/'full-quality'/'accepted-full.json'
        height=max((f.get('height') or 0 for f in info.get('formats',[]) if f.get('vcodec') not in (None,'none')),default=0)
        signature={'video_id':info['id'],'duration':info['duration'],'height':height}
        if accepted_path.is_file():
            old=json.loads(accepted_path.read_text(encoding='utf-8'))
            source=Path(old.get('source',''))
            if old.get('signature')==signature and source.is_file() and file_hash(source)==old.get('source_sha256'):
                with stage(state,ident,'full_quality_download',run_id=run,cached=True):
                    atomic_json(path,{**old,'cached':True,'run_id':run})
                return
        with stage(state,ident,'full_quality_download',run_id=run):
            accepted=youtube.download(SimpleNamespace(video_id=info['id'],config={'min_source_height':settings.min_source_height},created=time.time()),root/'full-quality',info=info,no_retries=True)
            result={'source':accepted['source'],'source_sha256':file_hash(accepted['source']),'height':accepted['metadata']['best_available_height'],'kind':'full','cached':False,'run_id':run,'signature':signature}
        accepted_path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(accepted_path,result)
        atomic_json(path,result)
    except Exception as exc:atomic_json(path,{'failure':sanitize_message(str(exc)),'run_id':run})


if __name__=='__main__':work(*sys.argv[1:4],json.loads(sys.stdin.buffer.read()))
