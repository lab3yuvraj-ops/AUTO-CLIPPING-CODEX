"""Durable owner-only dialogue and at-most-once job launch/upload attempts."""
import json
import threading
import time
import uuid
from pathlib import Path
from .storage import atomic_json
from .runner import source_url, WorkflowError
from .api import TelegramError

TRIGGERS={'analyze my youtube','analyse my youtube','analyze youtube','youtube analyze'}


class Controller:
    def __init__(self, config, api, runner):
        self.config=config;self.api=api;self.runner=runner;self.lock=threading.RLock()
        self.path=config.state/'controller.json'
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'offset':0,'request':None,'owner':config.owner}
        if self.data.get('owner',config.owner)!=config.owner:
            raise WorkflowError('Controller state belongs to another Telegram owner. Preserve it and configure a separate checkout.')
        self.thread=None
        # Never blindly restart a CLI after a bot crash: it could still be
        # processing. Retain its PID and require local operator reconciliation.
        request=self.data.get('request')
        if request and request['status']=='running':
            request['status']='interrupted';self.save()
        elif request and request['status']=='sending':
            request['status']='delivery_uncertain';self.save()

    def save(self):atomic_json(self.path,self.data)

    def say(self,text):
        try:self.api.text(self.config.owner,text)
        except TelegramError:pass  # /status can recover a failed notification.

    def handle(self, update):
        with self.lock:
            uid=update.get('update_id')
            if not isinstance(uid,int) or uid<self.data['offset']:return
            # Persist before acting: Telegram redelivery cannot spawn twice.
            self.data['offset']=uid+1;self.save()
            m=update.get('message',{});chat=m.get('chat',{});sender=m.get('from',{})
            if (sender.get('id')!=self.config.owner or chat.get('id')!=self.config.owner
                or chat.get('type')!='private' or sender.get('is_bot')):return
            text=(m.get('text') or '').strip();request=self.data.get('request')
            if text.lower() in ('/start','/help'):
                self.say('Send Analyze my YouTube or one HTTPS YouTube URL. I will ask how many clips. /status shows the current request. Preview only; Instagram publishing is disabled.')
                return
            if text.lower()=='/status':
                status=request['status'] if request else 'idle'
                self.say('Current request: '+status+'.'+(' Reconcile the recorded worker locally before starting another job.' if status=='interrupted' else ''))
                return
            if request and request['status'] in ('running','interrupted','sending'):
                self.say('A workflow or delivery is already active or awaiting local reconciliation. No second job was launched.')
                return
            if text.lower()=='/cancel' and request and request['status']=='awaiting_count':
                request['status']='cancelled';self.save();self.say('Pending request cancelled.');return
            if text.lower()=='/resend' and request and request.get('outputs'):
                # An explicit resend is allowed after an ambiguous upload.
                # It may create a duplicate Telegram message, never a new job.
                if request['status']=='delivery_uncertain':
                    self.say('Retrying delivery on your explicit request; an earlier upload may already be visible. No clipping rerun.')
                request['delivered']=[];self.save();self.start_delivery();return
            if request and request['status']=='awaiting_count' and text.isascii() and text.isdigit():
                count=int(text)
                if not 1<=count<=self.config.max_clips:
                    self.say(f'Choose a clip count from 1 to {self.config.max_clips}.');return
                try:self.runner.ready()
                except WorkflowError:
                    self.say('Local Codex execution is not ready. Complete the tool probe/setup in docs/TELEGRAM.md, then send the count again. No workflow started.');return
                request.update(count=count,status='running',started=time.time());self.save()
                self.say('Clip count received. Starting the existing Codex workflow on your PC. Nothing will be published.')
                self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start();return
            url=None
            if text.lower() in TRIGGERS:
                if not (self.config.root/'workflow/connection.json').is_file():
                    self.say('No channel is connected in this checkout. Complete local onboarding or send a YouTube video URL.');return
            else:
                try:url=source_url(text)
                except (ValueError,TypeError):
                    self.say('Send Analyze my YouTube, one valid YouTube URL, or the requested numeric clip count. Arbitrary commands are not accepted.');return
            self.data['request']={'id':uuid.uuid4().hex,'url':url,'status':'awaiting_count','created':time.time()}
            self.save();self.say('How many clips do you want?')

    def progress(self,text):
        # Only controller-owned constant strings, never unrestricted model text.
        allowed={'Codex session started.','Workflow: retrieving the selection transcript.',
            'Workflow: transcript ready; Codex is selecting the moment.',
            'Workflow: selected footage and speech preparation finished.',
            'Workflow: final rendering started.'}
        with self.lock:
            request=self.data['request'];seen=request.setdefault('progress',[])
            if text in allowed and text not in seen:
                seen.append(text);self.save();self.say(text)

    def pid(self,pid):
        with self.lock:self.data['request']['pid']=pid;self.save()

    def work(self):
        try:
            with self.lock:request=dict(self.data['request'])
            outputs=self.runner.run(request,self.progress,self.pid)
            with self.lock:
                self.data['request'].update(outputs=outputs,status='sending',delivered=[]);self.save()
            self.deliver()
        except Exception as error:
            # No exception payload, paths, stderr or provider body in Telegram.
            with self.lock:
                r=self.data['request']
                if r['status'] not in ('delivery_uncertain','sending'):
                    r['status']='failed';r['failure_category']=type(error).__name__;self.save()
            self.say('Workflow failed or requires human attention. No result was accepted or published. Check the private request and job records locally; /status is available. No automatic rerun.')

    def start_delivery(self):
        self.data['request']['status']='sending';self.save()
        self.thread=threading.Thread(target=self.deliver,daemon=True);self.thread.start()

    def deliver(self):
        import hashlib
        with self.lock:request=self.data['request'];outputs=list(request['outputs'])
        for i,item in enumerate(outputs):
            with self.lock:
                if i in request.get('delivered',[]):continue
            path=Path(item['path']).resolve()
            expected=(self.config.root/'workflow/jobs'/item['job']/'reel.mp4').resolve()
            if path!=expected or not path.is_file():
                with self.lock:request['status']='delivery_failed';self.save()
                self.say('The validated final MP4 is missing. No placeholder was sent.');return
            with path.open('rb') as stream:hash_value=hashlib.file_digest(stream,'sha256').hexdigest()
            if hash_value!=item['sha256']:
                with self.lock:request['status']='delivery_failed';self.save()
                self.say('The final MP4 changed after validation. Delivery stopped.');return
            if path.stat().st_size>self.config.upload_bytes:
                with self.lock:request['status']='too_large';self.save()
                self.say('Reel completed locally but exceeds the configured Telegram upload limit (up to 49 MB). Retrieve workflow/jobs/'+item['job']+'/reel.mp4 on your PC. Quality was not reduced.');return
            with self.lock:request['status']='sending';request['sending_index']=i;self.save()
            try:message=self.api.video(self.config.owner,path)
            except TelegramError:
                with self.lock:request['status']='delivery_uncertain';self.save()
                self.say('Video delivery failed or its acknowledgement was lost. Check Telegram first; /resend explicitly retries delivery and may duplicate a message. The local MP4 is retained.');return
            with self.lock:
                request.setdefault('delivered',[]).append(i)
                request.setdefault('telegram_message_ids',[]).append(message.get('message_id'))
                request['status']='ready';self.save()
        with self.lock:request.update(status='completed',finished=time.time());self.save()
        self.say('Validated Reel preview delivered. Instagram publishing remains disabled.')


def poll(controller, api, sleep=time.sleep):
    # A brand-new controller ignores historical queued commands once. After
    # that its durable offset survives restarts. Never delete a webhook silently.
    if not controller.data.get('initialized'):
        old=api.updates(-1,0)
        controller.data['offset']=max([u['update_id']+1 for u in old]+[controller.data['offset']])
        controller.data['initialized']=True;controller.save()
    errors=0
    while True:
        try:
            updates=api.updates(controller.data['offset'])
            for update in updates:controller.handle(update)
            errors=0
        except TelegramError as exc:
            if exc.status in (401,403,409):
                raise WorkflowError('Telegram authorization or polling conflict: verify token and stop other pollers/webhook. No automatic webhook deletion.') from None
            errors+=1
            if errors>6:raise WorkflowError('Telegram polling failed repeatedly. Restart after network recovery; state is retained.') from None
            # Respect Retry-After without busy-looping; split waits so the
            # process remains interruptible and never repeatedly retries upload.
            delay=max(exc.retry_after,min(60,2**errors))
            for _ in range(delay):sleep(1)
