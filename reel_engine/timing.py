"""Auditable wall-clock stages, including work performed interactively in Codex."""
import contextlib
import json
import math
import os
import re
import time
import uuid
from pathlib import Path
import threading

_THREAD_LOCK = threading.Lock()
INTERACTIVE_PHASES=('selection_reading','scene_planning','spec_writing','review_pass','correction','final_inspection')


def interactive_phase(state,job,phase,event,*,round_number=1,run_id=None):
    """Explicit observed phase boundaries, never inferred from idle time."""
    _name(job)
    if phase not in INTERACTIVE_PHASES or isinstance(round_number,bool) or not isinstance(round_number,int) or not 1<=round_number<=10000:
        raise ValueError('Use a supported interactive phase and a positive round number.')
    if phase=='correction' and round_number>2:raise ValueError('At most two correction rounds per clip.')
    root=Path(state)/'jobs'/job;record=json.loads((root/'job.json').read_text(encoding='utf-8'))
    owner=record.get('timing_job') or record.get('source_job_id') or job
    import hashlib
    name=f"interactive_{phase}_{hashlib.sha256(job.encode()).hexdigest()[:8]}_{round_number}"
    row=mark(state,owner,name,event,run_id=run_id or record.get('run_id'))
    ledger=root/'interactive-phases.jsonl'
    with _locked(ledger):
        with ledger.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({**row,'clip_job':job,'phase':phase,'round':round_number})+'\n')
    return {**row,'clip_job':job,'phase':phase,'round':round_number}


def _union(intervals):
    result=[]
    for a,b in sorted(intervals):
        if result and a<=result[-1][1]:result[-1][1]=max(b,result[-1][1])
        else:result.append([a,b])
    return result


def _complement(start,end,intervals):
    result=[];cursor=start
    for a,b in _union(intervals):
        if a>cursor:result.append([cursor,a])
        cursor=max(cursor,b)
    if end>cursor:result.append([cursor,end])
    return result


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError('Timing identifiers must contain only letters, numbers, hyphens and underscores.')
    return value


@contextlib.contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, path.with_suffix('.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try: yield
        finally:
            lock.seek(0)
            if os.name == 'nt': msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def mark(state, job, stage, event, *, run_id=None, cached=False, at=None, outcome=None,diagnostic=None):
    path = Path(state)/'stage-timings.jsonl'
    job, stage = _name(job), _name(stage)
    if event not in ('start', 'end'): raise ValueError('Use timing event start or end.')
    stamp = time.time() if at is None else at
    if isinstance(stamp,bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp): raise ValueError('Invalid stage timestamp.')
    if outcome not in (None, 'success', 'failed', 'rejected'): raise ValueError('Invalid stage outcome.')
    with _locked(path):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []
        relevant = [r for r in rows if r['job']==job]
        if run_id is None:
            run_id = relevant[-1]['run_id'] if relevant else uuid.uuid4().hex
        _name(run_id)
        same = [r for r in relevant if r['run_id']==run_id and r['stage']==stage]
        opened = same[-1] if same and same[-1]['event']=='start' else None
        if event=='start' and opened: raise ValueError('This stage already has an open timing interval.')
        if event=='end' and not opened: raise ValueError('This stage has no open timing interval.')
        if event=='end' and stamp<opened['at']: raise ValueError('A stage cannot end before it starts.')
        row = {'job':job, 'run_id':run_id, 'stage':stage, 'event':event, 'at':stamp,
               'cached':bool(cached), 'outcome':outcome}
        if diagnostic:
            from .caption_errors import sanitize_message
            row['diagnostic']={k:sanitize_message(v) if isinstance(v,str) else v for k,v in diagnostic.items() if k in ('category','http_status','yt_dlp_message','requested_language','retry_after','attempt_count','suggested_retry_at')}
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row)+'\n'); stream.flush(); os.fsync(stream.fileno())
    return row


@contextlib.contextmanager
def stage(state, job, name, *, run_id=None, cached=False):
    opened=mark(state,job,name,'start',run_id=run_id,cached=cached)
    try: yield opened
    except BaseException as exc:
        from .caption_errors import classify_caption_failure
        diagnostic=getattr(exc,'diagnostic',None) or classify_caption_failure(str(exc))
        if 'http_status' not in diagnostic:diagnostic={**classify_caption_failure(diagnostic.get('yt_dlp_message',str(exc))),**diagnostic}
        mark(state,job,name,'end',run_id=opened['run_id'],cached=cached,outcome='failed',diagnostic=diagnostic); raise
    else: mark(state,job,name,'end',run_id=opened['run_id'],cached=opened.get('cached',cached),outcome=opened.get('outcome') or 'success',diagnostic=opened.get('diagnostic'))


def report(state, job, run_id=None):
    _name(job); path=Path(state)/'stage-timings.jsonl'
    with _locked(path):
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []
    rows=[r for r in rows if r['job']==job]
    if not rows: raise ValueError('No stage timings recorded for this job.')
    run_id=run_id or rows[-1]['run_id']; rows=[r for r in rows if r['run_id']==run_id]
    if not rows: raise ValueError('No timings for this run.')
    opened={}; intervals=[]
    for r in rows:
        if r['event']=='start': opened[r['stage']]=r
        elif r['stage'] in opened:
            a=opened.pop(r['stage']); intervals.append({'stage':r['stage'],'start':a['at'],'end':r['at'],
                'seconds':r['at']-a['at'],'cached':a['cached'] or r['cached'],'outcome':r['outcome'],'diagnostic':r.get('diagnostic')})
    union=[]
    # The workflow envelope cannot count as stage coverage or hide gaps.
    measured=[i for i in intervals if i['stage']!='workflow']
    for i in sorted(measured,key=lambda x:x['start']):
        if union and i['start']<=union[-1][1]:union[-1][1]=max(union[-1][1],i['end'])
        else:union.append([i['start'],i['end']])
    overlaps=[]
    for n,a in enumerate(intervals):
        for b in intervals[n+1:]:
            seconds=min(a['end'],b['end'])-max(a['start'],b['start'])
            if seconds>0:overlaps.append({'first':a['stage'],'second':b['stage'],'seconds':seconds})
    start=min(r['at'] for r in rows); end=max(r['at'] for r in rows)
    gaps=[];cursor=start
    for a,b in union:
        if a>cursor:gaps.append({'start':cursor,'end':a,'seconds':a-cursor,'stage':'unattributed_gap','classification':'Not recorded at execution; do not invent a stage.'})
        cursor=max(cursor,b)
    if end>cursor:gaps.append({'start':cursor,'end':end,'seconds':end-cursor,'stage':'unattributed_gap','classification':'Not recorded at execution; do not invent a stage.'})
    interactive=[i for i in intervals if i['stage'].startswith('interactive_')]
    commands=[(i['start'],i['end']) for i in intervals if i['stage'].startswith('cli_')]
    between=_complement(start,end,commands) if commands else []
    interactive_union=_union([(i['start'],i['end']) for i in interactive])
    interactive_between=sum(max(0,min(b,d)-max(a,c)) for a,b in between for c,d in interactive_union)
    return {'job':job,'run_id':run_id,'intervals':intervals,'overlaps':overlaps,
        'wall_seconds':end-start,'summed_stage_seconds':sum(i['seconds'] for i in intervals),
        'covered_wall_seconds':sum(b-a for a,b in union),'open_stages':list(opened),
        'untracked_wall_seconds':max(0,end-start-sum(b-a for a,b in union)),
        'gaps':gaps,
        'interactive_phases':interactive,'interactive_wall_seconds':sum(b-a for a,b in interactive_union),
        'between_command_intervals':between,'between_commands_wall_seconds':sum(b-a for a,b in between),
        'interactive_between_commands_seconds':interactive_between,
        'between_commands_note':'CLI-free wall time can include explicitly marked interactive work and background transfers; these overlap, never add them to total wall time. Unmarked activity is not inferred.',
        'note':'Wall time spans this run only. Concurrent intervals overlap and are not added to wall time; open stages are incomplete.'}


def table(data):
    lines=['Stage                         Seconds     Cached  Outcome']
    for i in data['intervals']:
        lines.append(f"{i['stage']:<29} {i['seconds']:10.3f}  {str(i['cached']):<6}  {i['outcome'] or '-'}")
    lines += [f"Total wall-clock: {data['wall_seconds']:.3f}s",f"Summed stages (includes overlaps): {data['summed_stage_seconds']:.3f}s",
        f"Untracked wall-clock: {data['untracked_wall_seconds']:.3f}s"]
    for o in data['overlaps']:lines.append(f"Overlap {o['first']} / {o['second']}: {o['seconds']:.3f}s")
    for gap in data.get('gaps',[]):lines.append(f"UNATTRIBUTED GAP: {gap['seconds']:.3f}s ({gap['start']:.3f}–{gap['end']:.3f})")
    lines.append(f"Interactive wall time (union): {data.get('interactive_wall_seconds',0):.3f}s")
    lines.append(f"Between commands: {data.get('between_commands_wall_seconds',0):.3f}s; marked interactive overlap: {data.get('interactive_between_commands_seconds',0):.3f}s")
    if data['open_stages']:lines.append('INCOMPLETE: '+', '.join(data['open_stages']))
    return '\n'.join(lines)


def record_command_coverage(state,job,command,started,ended,succeeded):
    """Account for measured CLI overhead and intervals between commands.

    Between-command time is interactive/idle; never pretend it is CPU work.
    Does not assign historical gaps a made-up editorial activity.
    """
    path=Path(state)/'stage-timings.jsonl'
    if not path.exists():return
    with _locked(path):
        rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    relevant=[r for r in rows if r['job']==job]
    if not relevant:return
    run=relevant[-1]['run_id'];current=[r for r in relevant if r['run_id']==run]
    earlier=[r['at'] for r in current if r['at']<=started]
    if earlier and max(earlier)<started:
        mark(state,job,'between_commands','start',run_id=run,at=max(earlier))
        mark(state,job,'between_commands','end',run_id=run,at=started,outcome='success')
    name='cli_'+_name(command)
    mark(state,job,name,'start',run_id=run,at=started)
    mark(state,job,name,'end',run_id=run,at=ended,outcome='success' if succeeded else 'failed')
