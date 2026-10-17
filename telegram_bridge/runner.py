"""Execute Codex, not a replacement Python editor. No generation during doctor."""
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.request import url2pathname
from .storage import atomic_json


class WorkflowError(Exception): pass


def source_url(text):
    """Return canonical video URL; accept no arbitrary prompt/shell payload."""
    if not isinstance(text,str) or len(text)>512 or any(c.isspace() for c in text):
        raise ValueError('Supply one YouTube video URL.')
    p=urlsplit(text)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):
        raise ValueError('Use an HTTPS YouTube video URL.')
    host=(p.hostname or '').lower()
    if host=='youtu.be': ident=p.path.strip('/')
    elif host in ('youtube.com','www.youtube.com','m.youtube.com'):
        if p.path=='/watch': ident=parse_qs(p.query).get('v',[''])[0]
        elif re.fullmatch(r'/(shorts|live)/[A-Za-z0-9_-]{11}/?',p.path):ident=p.path.strip('/').split('/')[1]
        else:raise ValueError('Use a video URL, not a channel or other website.')
    else:raise ValueError('Use a YouTube video URL.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):raise ValueError('Invalid YouTube video ID.')
    return 'https://www.youtube.com/watch?v='+ident


def child_env():
    env=os.environ.copy()
    for key in list(env):
        if key.startswith('TELEGRAM_') or key in ('OPENAI_API_KEY','CODEX_API_KEY','OPENAI_BASE_URL','CODEX_THREAD_ID','CODEX_INTERNAL_ORIGINATOR_OVERRIDE'):
            env.pop(key,None)
    env.update(REEL_PUBLICATION_DISABLED='true',SEMANTIC_VISION_URL='',SEMANTIC_ALLOW_REMOTE='false')
    return env


def executable(config):
    path=shutil.which(config.codex)
    if not path or Path(path).suffix.lower() in ('.cmd','.bat','.ps1'):
        raise WorkflowError('Configure TELEGRAM_CODEX_PATH with the actual Codex executable, not a shell wrapper.')
    return path


def fingerprint(config):
    exe=executable(config)
    version=subprocess.run([exe,'--version'],capture_output=True,text=True,timeout=15,env=child_env())
    login=subprocess.run([exe,'login','status'],capture_output=True,text=True,timeout=15,env=child_env())
    if login.returncode or 'ChatGPT' not in login.stdout+login.stderr:
        raise WorkflowError('Codex CLI must be logged in using ChatGPT; API-key billing is not enabled by this bridge.')
    help_result=subprocess.run([exe,'exec','--help'],capture_output=True,text=True,timeout=15,env=child_env())
    if help_result.returncode or any(flag not in help_result.stdout for flag in ('--json','--output-schema','--output-last-message','--sandbox')):
        raise WorkflowError('Installed Codex CLI lacks required structured execution options.')
    h=hashlib.sha256()
    for p in sorted([config.root/'AGENTS.md',config.root/'reel.py',* (config.root/'reel_engine').glob('*.py')]):
        h.update(p.name.encode());h.update(p.read_bytes())
    # A tool/model/config change invalidates the proof even when the project
    # files and reported executable version have not changed.
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    for p in (home/'config.toml',config.root/'.codex/config.toml'):
        if p.is_file():h.update(p.read_bytes())
    return {'executable':str(Path(exe).resolve()),'version':version.stdout.strip(),'workflow_hash':h.hexdigest()}


def require_probe(config):
    if (config.state/'worker-unconfirmed.json').exists():
        raise WorkflowError('Prior worker termination is unconfirmed; reconcile locally before another run.')
    path=config.state/'capability.json'
    if not path.is_file():raise WorkflowError('Headless tool probe is required before running Telegram jobs. See docs/TELEGRAM.md.')
    proof=json.loads(path.read_text())
    if proof.get('binding')!=fingerprint(config) or not proof.get('image_review_observed') or not proof.get('shell_observed'):
        raise WorkflowError('Tool capability proof is missing or stale. Run the explicitly authorized probe again.')


def session_tool_evidence(config, thread_id, required_image=None):
    """Read only this invocation's own CLI audit, never auth or other sessions.

    Current code-mode CLI omits ImageView from exec JSONL while retaining the
    actual tool event in its local session audit. Agent prose is not evidence.
    """
    empty={'shell_observed':False,'image_review_observed':False}
    if not re.fullmatch(r'[0-9a-f-]{36}',thread_id or ''):return empty
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    matches=list((home/'sessions').rglob('*'+thread_id+'*.jsonl'))
    if len(matches)!=1:return empty
    session_ok=False;shell=False;image=False
    try:
        with matches[0].open(encoding='utf-8') as stream:
            for line in stream:
                d=json.loads(line);payload=d.get('payload',{})
                if d.get('type')=='session_meta':
                    session_ok=(payload.get('id')==thread_id and Path(payload.get('cwd','')).resolve()==config.root.resolve())
                if d.get('type')!='event_msg' or payload.get('type')!='item_completed':continue
                item=payload.get('item',{});kind=item.get('type')
                if kind=='CommandExecution' and item.get('exit_code')==0:shell=True
                if kind=='ImageView' and item.get('path'):
                    raw=item['path'];uri=urlsplit(raw)
                    if uri.scheme=='file':
                        if uri.netloc not in ('','localhost'):continue
                        raw=url2pathname(uri.path)
                    viewed=Path(raw).resolve()
                    if required_image is not None:image=image or viewed==Path(required_image).resolve()
                    else:image=image or viewed.is_relative_to((config.root/'workflow/jobs').resolve())
        return {'shell_observed':session_ok and shell,'image_review_observed':session_ok and image}
    except (OSError,ValueError,TypeError):return empty


def stop_tree(process):
    if process.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=20)
    else:process.kill()
    try:process.wait(timeout=20)
    except subprocess.TimeoutExpired:raise WorkflowError('Worker termination unconfirmed; do not launch another job.') from None


def run_codex(config, folder, prompt, schema, progress=lambda _:None, started=lambda _:None, required_image=None):
    folder.mkdir(parents=True,exist_ok=True)
    schema_path=folder/'response.schema.json'; atomic_json(schema_path,schema)
    output=folder/'response.json'
    args=[executable(config),'-a','never','exec','--cd',str(config.root),'--sandbox','workspace-write',
          '-c','model_provider="openai"',
          '-c','sandbox_workspace_write.network_access=true','-c','tools.view_image=true',
          '--json','--color','never','--output-schema',str(schema_path),'-o',str(output),'-']
    process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,encoding='utf-8',errors='replace',env=child_env(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    started(process.pid)
    events=queue.Queue(maxsize=1000)
    def reader():
        for line in process.stdout:events.put(line)
        events.put(None)
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    process.stdin.write(prompt);process.stdin.close()
    end=time.monotonic()+config.timeout; usage={}; image=False;shell=False;failed=False;thread_id=None
    try:
        while True:
            if time.monotonic()>end:raise WorkflowError('Codex workflow timed out. Artifacts retained; no automatic rerun.')
            try:line=events.get(timeout=.5)
            except queue.Empty:continue
            if line is None:break
            try:event=json.loads(line)
            except ValueError:continue
            kind=event.get('type');item=event.get('item',{});typ=item.get('type','')
            if kind=='thread.started':thread_id=event.get('thread_id')
            if typ=='command_execution':shell=True
            if typ in ('image_view','image_viewing','view_image'):image=True
            # Code-mode tools may nest view_image in a tool call. Exact tool
            # names only; prose saying "I viewed" never establishes inspection.
            if item.get('tool') in ('view_image','functions.view_image') or item.get('name')=='view_image':image=True
            if kind=='turn.completed':usage=event.get('usage',{})
            if kind in ('turn.failed','error'):failed=True
            if kind in ('thread.started','turn.started'):progress('Codex session started.')
        process.wait(timeout=10)
        audit=session_tool_evidence(config,thread_id,required_image)
        image=image or audit['image_review_observed'];shell=shell or audit['shell_observed']
        atomic_json(folder/'execution.json',{'returncode':process.returncode,'shell_observed':shell,
            'image_review_observed':image,'usage':usage,'finished':time.time(),
            'thread_id':thread_id,'local_tool_audit_used':bool(audit['image_review_observed']),
            'note':'Raw Codex commands/messages/stderr intentionally not stored or forwarded.'})
        if process.returncode or failed or not output.is_file():
            raise WorkflowError('Codex did not complete successfully. No video was accepted; inspect the local workflow.')
        return json.loads(output.read_text(encoding='utf-8')), {'shell_observed':shell,'image_review_observed':image}
    finally:
        try:stop_tree(process)
        except (WorkflowError,OSError,subprocess.SubprocessError):
            atomic_json(config.state/'worker-unconfirmed.json',{'pid':process.pid,'at':time.time()})
            raise WorkflowError('Worker termination unconfirmed; controller is blocked pending local reconciliation.') from None


RESULT_SCHEMA={'type':'object','additionalProperties':False,'required':['status','source_job','clips'],
    'properties':{'status':{'type':'string','enum':['completed','needs_attention']},
        'source_job':{'type':'string'},'clips':{'type':'array','items':{'type':'string'}}}}


def prompt_for(config, request):
    source=request['url'] or "the latest released upload on this checkout's saved YouTube channel"
    return f'''Execute the existing real Reel workflow in this project, following AGENTS.md's latest rules.
This is a private Telegram clipping request. Clip count already answered: {request['count']}.
Source: {source}. Request id: {request['id']}.
Do not ask the count again. Use this project's existing .env indirectly through the Python commands,
channel connection, CPU models, tools, assets, actual image inspection, FFmpeg and review safeguards.
Do not replace this workflow with an ad-hoc editor. Start standard analyze with --clips {request['count']} --fresh.
Use only newly created source/child job records for this request; never return a previous demo or old video.
Select complete 30-60s moments; return fewer only when justified in the saved selection report.
Prepare actual selected footage and verified speech. Build the reviewed camera/spec, inspect actual
required pre-render images once, record inspection only after viewing, render once and run technical checks.
Preserve all captions, full-height crop, easing, audio, four-second CTA, timing phases and timing-report.
No post-render screenshot loop, no automatic correction loop. Use the existing uncertainty rules:
if human evidence/consent is required, return needs_attention; never forge evidence to avoid a question.
Do not modify source code, settings, .env, accounts, Git or branch. No installation/onboarding in this run.
NEVER publish to Instagram, call publishing endpoints, or create publication approval; Telegram preview only.
Do not use paid APIs or external AI endpoints. Do not print credentials or read auth stores.
The CLI has local execution/image tools; if unavailable, stop needs_attention, never claim reviewed.
Wait for all media subprocesses; do not leave work running after returning. Return the schema with
the actual new source_job id and actual new clip job IDs only, after all safeguards pass.
'''


def accept_outputs(config, result, request, launched, previous):
    if result.get('status')!='completed':raise WorkflowError('Workflow needs human attention in Codex; no clip delivered or published.')
    jobs=config.root/'workflow/jobs';ident=result.get('source_job','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}',ident) or ident in previous:
        raise WorkflowError('Rejected stale or invalid source job.')
    parent=json.loads((jobs/ident/'job.json').read_text())
    if parent.get('created',0)<launched or parent.get('requested_clips')!=request['count']:
        raise WorkflowError('Output does not belong to the current request.')
    if request['url'] and parent.get('video_id')!=request['url'].split('v=')[1]:
        raise WorkflowError('Output source video does not match this request.')
    if not request['url']:
        connection=json.loads((config.root/'workflow/connection.json').read_text())
        if parent.get('metadata',{}).get('channel_id')!=connection.get('channel_id'):
            raise WorkflowError('Output channel does not match the saved connection.')
    clips=result.get('clips',[])
    if not 1<=len(clips)<=request['count'] or len(set(clips))!=len(clips):raise WorkflowError('Invalid output clip count.')
    selected={x['id'] for x in parent.get('clips',[])}; outputs=[]
    if set(clips)!=selected:raise WorkflowError('Not all selected clips have finished.')
    for clip in clips:
        if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}',clip) or clip in previous:raise WorkflowError('Rejected stale clip.')
        folder=jobs/clip; record=json.loads((folder/'job.json').read_text())
        video=Path(record.get('video','')).resolve()
        if (record.get('source_job_id')!=ident or record.get('status')!='Needs approval'
            or record.get('post_id') or record.get('publishing') or record.get('approval')
            or not record.get('checks') or any(c['status']=='fail' for c in record['checks'])
            or not video.is_relative_to(jobs.resolve())
            or video!= (folder/'reel.mp4').resolve() or not video.is_file()):
            raise WorkflowError('Final file/state failed request-bound validation.')
        # Review records survive automatic media cleanup. Preserve the same
        # current-spec/source bindings checked by the existing render guard.
        policy=json.loads((folder/'review-policy.json').read_text())
        ledger=json.loads((folder/'inspection-ledger.json').read_text())
        if (not ledger.get('pre') or policy.get('source_sha256')!=record.get('source_sha256')
            or policy.get('spec_sha256')!=record.get('edit_spec_hash')):
            raise WorkflowError('Missing real review evidence for this render.')
        with video.open('rb') as stream:fingerprint=hashlib.file_digest(stream,'sha256').hexdigest()
        if fingerprint!=record.get('render_sha256'):raise WorkflowError('Final MP4 changed after validation.')
        outputs.append({'job':clip,'path':str(video),'sha256':fingerprint})
    return outputs


class Runner:
    def __init__(self, config):self.config=config

    def ready(self):require_probe(self.config)

    def run(self, request, progress, started):
        self.ready();config=self.config
        previous={p.parent.name for p in (config.root/'workflow/jobs').glob('*/job.json')}
        launched=time.time();folder=config.state/'requests'/request['id']
        stopped=threading.Event()
        def observe():
            seen=set()
            phases={'Retrieving selection transcript':'Workflow: retrieving the selection transcript.',
                'Transcript ready; select moments before downloading video':'Workflow: transcript ready; Codex is selecting the moment.',
                'Clips awaiting edit':'Workflow: selected footage and speech preparation finished.',
                'Rendering':'Workflow: final rendering started.'}
            while not stopped.wait(5):
                for path in (config.root/'workflow/jobs').glob('*/job.json'):
                    if path.parent.name in previous:continue
                    try:
                        j=json.loads(path.read_text());status=j.get('status');message=phases.get(status)
                        if message and message not in seen:
                            seen.add(message);progress(message)
                    except (OSError,ValueError):pass
        watcher=threading.Thread(target=observe,daemon=True);watcher.start()
        try:result, evidence=run_codex(config,folder,prompt_for(config,request),RESULT_SCHEMA,progress,started)
        finally:stopped.set();watcher.join(timeout=6)
        if not evidence['shell_observed'] or not evidence['image_review_observed']:
            raise WorkflowError('Required shell/image-review tool calls were not observed; open Codex for review.')
        return accept_outputs(config,result,request,launched,previous)
