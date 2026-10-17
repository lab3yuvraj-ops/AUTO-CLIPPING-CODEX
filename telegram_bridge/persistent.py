"""Persistent, private Telegram conversation on the official Codex app server."""
import hashlib
import json
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from .storage import atomic_json

INSTRUCTIONS='''Telegram is the human input/output interface for this persistent Codex conversation.
Work only in this project on performance-optimization and follow AGENTS.md's latest rules.
Use the existing reel.py/reel_engine workflow unchanged. Do not replace it, start a dashboard,
change source code/configuration, install services or use paid AI APIs for a clipping request.
A YouTube URL requests clips: ask the clip count in a normal text reply unless already supplied.
When clarification is needed, ask it as plain text and finish your turn; the next Telegram message
will be the human's answer. Do not use interactive question tools requiring a desktop client.
Use actual local media and inspection tools; never claim tool access or review without evidence.
If tools cannot do a necessary step, explain and stop. Mark real interactive phases and timings.
Never publish, create publication approval, or write to Instagram in this preview-only transport.
Show final local MP4 paths normally after technical checks; preserve caption/style/CTA/review rules.
Never print secrets, read authentication/password stores, or include private tool output in replies.
Do not mention hidden transport details unless there is a concrete connection failure.
'''


def safe_text(text,secrets=()):
    for secret in secrets:
        if secret and len(secret)>=8:text=text.replace(secret,'[redacted]')
    return re.sub(r'\b(?:[0-9]{8,12}:[A-Za-z0-9_-]{30,50}|gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b','[redacted]',text)


class Conversation:
    def __init__(self,cfg,users,api,secrets=()):
        self.cfg=cfg;self.users=tuple(users);self.api=api;self.secrets=secrets
        self.path=cfg.state/'persistent-conversation.json';self.lock=threading.RLock()
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'users':list(users),'cwd':str(cfg.root.resolve()),'thread':None,'offset':0,'initialized':False,'queue':[],'active':None,'ready':False}
        if self.data['users']!=list(users) or self.data['cwd']!=str(cfg.root.resolve()):raise ValueError('Persistent conversation binding changed; reconcile locally.')
        if self.data.get('active'):
            self.data['interrupted']=True;self.data['ready']=False;self.save()
            raise ValueError('Prior turn was interrupted. Reconcile before accepting more instructions.')
        self.inbox=queue.Queue();self.ready=threading.Event();self.failed=threading.Event()
        self.ws=None;self.rpc_id=10;self.reply='';self.stop=threading.Event()
    def save(self):atomic_json(self.path,self.data)
    def say(self,owner,text):
        text=safe_text(text,self.secrets)
        for i in range(0,len(text),3900):self.api.text(owner,text[i:i+3900])
    def handle(self,update):
        with self.lock:
            ident=update.get('update_id')
            if not isinstance(ident,int) or ident<self.data['offset']:return
            self.data['offset']=ident+1;self.save()
            m=update.get('message',{});sender=m.get('from',{});chat=m.get('chat',{});owner=sender.get('id')
            if (not isinstance(owner,int) or isinstance(owner,bool) or owner not in self.users or sender.get('is_bot')
                or chat.get('type')!='private' or chat.get('id')!=owner):return
            text=m.get('text')
            if not isinstance(text,str) or not text.strip():self.say(owner,'Send text or a YouTube URL. File attachments are not supported yet.');return
            if text=='/start':self.say(owner,'Connected to the persistent Codex conversation for this project. Send a message or YouTube URL. Reel previews only; nothing publishes to Instagram.');return
            if text=='/status':
                self.say(owner,'Codex is '+('working' if self.data.get('active') else 'ready')+'. Queued messages: '+str(len(self.data['queue'])));return
            if not self.ready.is_set() or self.failed.is_set():self.say(owner,'Codex is not connected. No instruction was accepted; check the local relay.');return
            item={'id':uuid.uuid4().hex,'owner':owner,'text':text,'at':time.time()}
            self.data['queue'].append(item);self.save()
            self.say(owner,'Message received by Codex.' if not self.data.get('active') else 'Queued after the current Codex response.')
    def rpc(self,method,params):
        self.rpc_id+=1;ident=self.rpc_id
        self.ws.send(json.dumps({'id':ident,'method':method,'params':params}))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            event=json.loads(self.ws.recv(timeout=max(.01,deadline-time.monotonic())))
            if event.get('id')==ident:
                if 'error' in event:
                    self.data['protocol_failure']={'method':method,'code':event['error'].get('code'),'at':time.time()};self.save()
                    raise RuntimeError('Codex protocol request rejected; no automatic retry.')
                return event.get('result',{})
            self.event(event)
        raise RuntimeError('Codex protocol request timed out.')
    def setup(self):
        self.rpc('initialize',{'clientInfo':{'name':'telegram_persistent_codex','title':'Telegram Codex Conversation','version':'1.0.0'}})
        self.ws.send(json.dumps({'method':'initialized','params':{}}))
        params={'cwd':str(self.cfg.root.resolve()),'approvalPolicy':'never','sandbox':'workspace-write',
            'modelProvider':'openai','developerInstructions':INSTRUCTIONS}
        if self.data.get('thread'):
            params['threadId']=self.data['thread'];thread=self.rpc('thread/resume',params)['thread']
        else:
            thread=self.rpc('thread/start',params)['thread']
            self.data['thread']=thread['id'];self.save()
        if thread['id']!=self.data['thread'] or Path(thread.get('cwd','')).resolve()!=self.cfg.root.resolve():
            raise RuntimeError('Codex conversation binding mismatch.')
        self.data['ready']=True;self.save();self.ready.set()
    def launch_next(self):
        with self.lock:
            if self.data.get('active') or not self.data['queue']:return
            item=self.data['queue'].pop(0);self.data['active']=item;self.reply='';self.save()
        result=self.rpc('turn/start',{'threadId':self.data['thread'],'clientUserMessageId':item['id'],
            'input':[{'type':'text','text':item['text']}],
            'sandboxPolicy':{'type':'workspaceWrite','writableRoots':[str(self.cfg.root.resolve())],'networkAccess':True}})
        with self.lock:
            if self.data.get('active'):
                self.data['active']['turn']=result['turn']['id'];self.save()
    def deliver_video(self,owner):
        # Only a hash-bound actual export under this project's jobs; no arbitrary path.
        jobs=(self.cfg.root/'workflow/jobs').resolve()
        for p in jobs.glob('*/job.json'):
            try:
                j=json.loads(p.read_text(encoding='utf-8'));path=Path(j.get('video','')).resolve()
                if (str(path) not in self.reply and path.as_posix() not in self.reply and p.parent.name not in self.reply):continue
                if j.get('status')!='Needs approval' or not j.get('checks') or any(c['status']=='fail' for c in j['checks']):continue
                if path!=(p.parent/'reel.mp4').resolve() or not path.is_relative_to(jobs) or not path.is_file():continue
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                delivery_key=str(owner)+':'+digest
                if digest!=j.get('render_sha256') or delivery_key in self.data.get('delivered_videos',[]):continue
                if path.stat().st_size>self.cfg.upload_bytes:
                    self.say(owner,'The completed preview exceeds Telegram’s configured upload limit. It remains available locally.');continue
                self.data.setdefault('delivered_videos',[]).append(delivery_key);self.save() # at most one automatic attempt
                from .api import TelegramError
                try:self.api.video(owner,path)
                except TelegramError:self.say(owner,'Video delivery was not confirmed. Check Telegram before requesting it again. The actual MP4 remains local.')
            except (OSError,ValueError,KeyError):continue
    def event(self,event):
        with self.lock:self._event(event)

    def _event(self,event):
        method=event.get('method');params=event.get('params',{})
        if 'id' in event and method:
            # No consent or permission is granted automatically by the transport.
            self.ws.send(json.dumps({'id':event['id'],'error':{'code':-32601,'message':'Interactive request needs local review.'}}))
            if self.data.get('active'):self.say(self.data['active']['owner'],'Codex needs a local interactive action. No permission was granted automatically.')
            return
        if params.get('threadId')!=self.data.get('thread'):return
        active=self.data.get('active')
        if not active:return
        if method=='item/completed':
            item=params.get('item',{})
            if item.get('type')=='agentMessage' and item.get('text'):
                if item.get('phase') not in ('commentary',):self.reply=item['text']
        if method=='turn/completed':
            turn=params.get('turn',{});status=turn.get('status')
            if active.get('turn') and turn.get('id')!=active['turn']:return
            owner=active['owner']
            self.data['last_turn']={'status':status,'finished':time.time(),'owner':owner}
            # Clear active before sending a response; no automatic job rerun on upload errors.
            self.data['active']=None;self.save()
            if status=='completed' and self.reply:
                self.say(owner,self.reply)
                self.data['last_delivery']={'turn':turn.get('id'),'telegram_reply_confirmed':True,'text_sha256':hashlib.sha256(self.reply.encode()).hexdigest(),'at':time.time()};self.save()
                self.deliver_video(owner)
            else:self.say(owner,'Codex stopped before completing this response. Check the local conversation; no automatic rerun.')
    def run(self):
        from telegram_relay import control_connection
        try:
            with control_connection(self.cfg.codex) as ws:
                self.ws=ws;self.setup()
                while not self.stop.is_set():
                    self.launch_next()
                    try:event=json.loads(ws.recv(timeout=.5))
                    except TimeoutError:continue
                    self.event(event)
        except Exception:
            self.failed.set();self.data['ready']=False;self.save()
        finally:self.ready.clear()


def run(cfg,users,secrets=()):
    from .api import API
    from telegram_relay import Session
    # Uses existing ChatGPT login only. Never enable API-key or other paid providers.
    check=subprocess.run([Session(cfg.codex,'00000000-0000-0000-0000-000000000000').executable,'login','status'],capture_output=True,text=True,timeout=15)
    if check.returncode or 'ChatGPT' not in check.stdout+check.stderr:raise ValueError('Use the existing ChatGPT Codex login, not API-key authentication.')
    api=API(cfg.token);controller=Conversation(cfg,users,api,secrets)
    worker=threading.Thread(target=controller.run,daemon=True);worker.start()
    deadline=time.monotonic()+25
    while not controller.ready.wait(.1):
        if controller.failed.is_set() or time.monotonic()>deadline:raise RuntimeError('Persistent Codex startup failed; no Telegram jobs started.')
    if not controller.data['initialized']:
        old=api.updates(-1,0);controller.data['offset']=max([u['update_id']+1 for u in old]+[controller.data['offset']]);controller.data['initialized']=True;controller.save()
    from .api import TelegramError
    errors=0
    try:
        while not controller.failed.is_set():
            try:
                for update in api.updates(controller.data['offset']):controller.handle(update)
                errors=0
            except TelegramError as error:
                errors+=1
                if error.status in (401,403,409) or errors>6:raise
                delay=max(error.retry_after,min(60,2**errors))
                for _ in range(delay):
                    if controller.failed.is_set():break
                    time.sleep(1)
    finally:
        controller.stop.set();worker.join(timeout=5)
