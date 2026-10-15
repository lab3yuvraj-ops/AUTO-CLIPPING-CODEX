"""Build a bounded cleanup plan. Native PowerShell performs approved deletion.

Never removes code, connection/credentials, models, caption cache, approved
reference or publication records. Old media loss is explicit; small evidence
records move out of the active job namespace instead of faking resumability.
"""
import json
from pathlib import Path

MEDIA={'.mp4','.mkv','.webm','.mov','.avi','.m4v','.wav','.mp3','.flac','.aac','.m4a','.png','.jpg','.jpeg','.gif','.npy','.npz','.part','.ytdl','.aria2'}

def inside(path,root):
    path=Path(path).resolve();root=Path(root).resolve()
    if path==root or not path.is_relative_to(root):raise ValueError('Cleanup target escapes workspace or equals workspace root')
    return path

def tree_bytes(path):return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())

def plan_cleanup(root,cleanup_id,model_dirs=(),protected_paths=()):
    root=Path(root).resolve()
    if not cleanup_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in cleanup_id):raise ValueError('Invalid cleanup identifier')
    history=root/'workflow/history'/cleanup_id
    protected_dirs=[root/'assets',root/'.venv',root/'data/models',root/'release',*[Path(p).resolve() for p in model_dirs]]
    protected_files={Path(p).resolve() for p in protected_paths if p and Path(p).is_file()}
    reference=root/'workflow/approved-reference.json'
    def refs(value):
        if isinstance(value,str):
            p=Path(value)
            if p.is_absolute() and p.is_file():protected_files.add(p.resolve())
        elif isinstance(value,dict):
            for v in value.values():refs(v)
        elif isinstance(value,list):
            for v in value:refs(v)
    if reference.exists():refs(json.loads(reference.read_text(encoding='utf-8')))
    def protected(p):
        p=p.resolve()
        return p in protected_files or any(p==d.resolve() or p.is_relative_to(d.resolve()) for d in protected_dirs)
    moves=[];candidates=[]
    jobs=root/'workflow/jobs'
    if jobs.exists():
        for folder in jobs.iterdir():
            if not folder.is_dir():continue
            record=folder/'job.json'
            if not record.exists():continue
            job=json.loads(record.read_text(encoding='utf-8'))
            if folder.name=='web3approved' or job.get('publishing') or job.get('post_id'):
                protected_dirs.append(folder);continue
            candidates.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in MEDIA)
            moves.append({'source':str(inside(folder,root)),'destination':str(inside(history/'jobs'/folder.name,root))})
    benchmarks=root/'workflow/benchmarks'
    if benchmarks.exists():candidates.extend(p for p in benchmarks.rglob('*') if p.is_file() and p.suffix.lower() in MEDIA)
    candidates.extend(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in MEDIA)
    trees=[]
    data=root/'data'
    if data.exists():
        for p in data.iterdir():
            if p.is_dir() and not protected(p):
                if any(f.is_relative_to(p.resolve()) for f in protected_files):
                    candidates.extend(f for f in p.rglob('*') if f.is_file() and f.suffix.lower() in MEDIA)
                else:trees.append(p)
    for name in ('.venv-gpu','.pytest_cache','__pycache__','reel_engine/__pycache__','tests/__pycache__','tools/__pycache__'):
        p=root/name
        if p.is_dir() and not protected(p):trees.append(p)
    trees=[inside(p,root) for p in trees]
    files=sorted({inside(p,root) for p in candidates if not protected(p) and not any(p.resolve().is_relative_to(t) for t in trees)})
    for p in trees:
        if any(d.resolve().is_relative_to(p) for d in protected_dirs):raise ValueError('Cleanup tree contains a protected directory')
    return {'workspace':str(root),'cleanup_id':cleanup_id,'history':str(history.resolve()),'delete_files':[str(p) for p in files],
        'delete_trees':[str(p) for p in trees],'archive_moves':moves,
        'bytes_to_delete':sum(p.stat().st_size for p in files)+sum(tree_bytes(p) for p in trees),
        'protected_files':[str(p) for p in protected_files],
        'protected_directories':[str(p.resolve()) for p in protected_dirs],
        'note':'Old media is permanently removed. Job evidence/decisions move to inactive history. Original source files in Downloads outside this workspace are untouched.'}
