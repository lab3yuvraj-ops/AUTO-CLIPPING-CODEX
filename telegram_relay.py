"""Owner-only Telegram text input for ONE existing Codex session; no editor."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
from dotenv import dotenv_values
from telegram_bridge.api import API, TelegramError
from telegram_bridge.config import Config
from telegram_bridge.storage import atomic_json
from telegram_bot import singleton

ROOT=Path(__file__).resolve().parent

class RelayError(Exception):pass

class Session:
    def __init__(self, executable, thread):
        self.executable=shutil.which(executable)
        if not self.executable or Path(self.executable).suffix.lower() in ('.bat','.cmd','.ps1'):
            raise RelayError('Configure the actual Codex executable privately.')
        if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',thread or ''):
            raise RelayError('Configure the exact existing Codex session UUID privately.')
        self.thread=thread

    def env(self):
        return {k:v for k,v in os.environ.items() if not k.startswith('TELEGRAM_')}

    def check(self):
        # Proxy connects to an ALREADY RUNNING shared server; never starts one.
        p=subprocess.Popen([self.executable,'app-server','proxy'],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
            env=self.env(),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        lines=queue.Queue()
        def read():
            for line in p.stdout:lines.put(line)
            lines.put(None)
        threading.Thread(target=read,daemon=True).start()
        def receive(ident):
            import time
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                try:line=lines.get(timeout=max(.01,deadline-time.monotonic()))
                except queue.Empty:break
                if line is None:break
                try:result=json.loads(line)
                except ValueError:continue
                if result.get('id')==ident:
                    if 'error' in result:raise RelayError('Existing session is unavailable on the shared Codex server.')
                    return result.get('result',{})
            raise RelayError('Cannot reach the existing session on the shared Codex server. No separate session started.')
        def send(obj):p.stdin.write(json.dumps(obj)+'\n');p.stdin.flush()
        try:
            send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'private_telegram_relay','version':'1.0.0'}}})
            receive(1);send({'method':'initialized'})
            send({'id':2,'method':'thread/read','params':{'threadId':self.thread,'includeTurns':False}})
            thread=receive(2).get('thread',{})
            if thread.get('id')!=self.thread:raise RelayError('The server did not confirm the exact configured session.')
            return True
        except (OSError,ValueError):
            raise RelayError('Shared Codex server connection failed; nothing was forwarded.') from None
        finally:
            if p.poll() is None:p.terminate()
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)

    def send(self,text):
        self.check()
        # Exact existing session, literal text, no shell, model/permission overrides,
        # exec fallback, editorial template or source-code changes.
        try:
            r=subprocess.run([self.executable,'queue','--thread',self.thread,'--message='+text],
                capture_output=True,text=True,encoding='utf-8',timeout=20,env=self.env(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except subprocess.TimeoutExpired:
            raise RelayError('Delivery is uncertain. Check the Codex chat before resending; no automatic retry.') from None
        if r.returncode:raise RelayError('Codex did not confirm queue delivery. Check the chat before resending; no automatic retry.')

class Relay:
    def __init__(self,cfg,session,api):
        self.cfg=cfg;self.session=session;self.api=api;self.path=cfg.state/'relay.json'
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'owner':cfg.owner,'thread':session.thread,'offset':0,'initialized':False}
        if self.data['owner']!=cfg.owner or self.data['thread']!=session.thread:raise RelayError('Relay state belongs to a different owner/session. Reconcile locally.')
    def save(self):atomic_json(self.path,self.data)
    def handle(self,u):
        ident=u.get('update_id')
        if not isinstance(ident,int) or ident<self.data['offset']:return
        self.data['offset']=ident+1;self.save()
        m=u.get('message',{});chat=m.get('chat',{});sender=m.get('from',{})
        if sender.get('id')!=self.cfg.owner or sender.get('is_bot') or chat.get('id')!=self.cfg.owner or chat.get('type')!='private':return
        text=m.get('text')
        if not isinstance(text,str) or not text.strip():
            self.api.text(self.cfg.owner,'This relay supports text only. Attach files directly in Codex.');return
        if text=='/start':
            self.api.text(self.cfg.owner,'Private text relay to your fixed Codex session. Messages are queued verbatim. Replies and approvals remain in Codex for this first version.');return
        self.data['last_delivery']='attempting';self.save()
        try:self.session.send(text)
        except RelayError:
            self.data['last_delivery']='unconfirmed';self.save()
            self.api.text(self.cfg.owner,'Message delivery was not confirmed. Check Codex before resending. No separate session or clipping job was started by this relay.');return
        self.data['last_delivery']='queued';self.save()
        self.api.text(self.cfg.owner,'Queued to your existing Codex session. Read the reply in Codex.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['doctor','run']);args=parser.parse_args()
    trust=Path(os.sys.executable).parent/'ca.pem'
    if trust.is_file():os.environ.setdefault('SSL_CERT_FILE',str(trust))
    try:
        cfg=Config.load(ROOT);values={**dotenv_values(ROOT/'.env'),**os.environ}
        session=Session(cfg.codex,values.get('TELEGRAM_CODEX_THREAD_ID',''));session.check()
        if args.command=='doctor':
            print(json.dumps({'existing_session_reachable':True,'telegram_configured':bool(cfg.token and cfg.owner),'message_sent':False,'generation_started':False}));return
        cfg.require_private_owner()
        # Reuse the old lock to prevent running both Telegram transports.
        with singleton(cfg.state/'bot.lock'):
            api=API(cfg.token);relay=Relay(cfg,session,api)
            if not relay.data['initialized']:
                old=api.updates(-1,0);relay.data['offset']=max([u['update_id']+1 for u in old]+[relay.data['offset']]);relay.data['initialized']=True;relay.save()
            while True:
                for update in api.updates(relay.data['offset']):relay.handle(update)
    except (RelayError,TelegramError,OSError,ValueError):
        print('Relay not connected. Check private configuration and the existing shared Codex server. No automatic restart or alternate session.')
        return 1

if __name__=='__main__':raise SystemExit(main())
