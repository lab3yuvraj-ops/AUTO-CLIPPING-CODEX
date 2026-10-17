"""Allowlisted private Telegram text input for ONE existing Codex session; no editor."""
import argparse
import json
import os
from pathlib import Path
import socket
from contextlib import contextmanager
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

def allowed_users(values, owner=0):
    raw=values.get('TELEGRAM_ALLOWED_USER_IDS')
    if raw is None or not str(raw).strip():
        return (owner,) if isinstance(owner,int) and not isinstance(owner,bool) and owner>0 else ()
    parts=str(raw).split(',')
    if len(parts)>20 or any(not re.fullmatch(r'[1-9][0-9]{0,18}',x.strip()) for x in parts):
        raise RelayError('Configure a comma-separated private numeric user allowlist.')
    ids=tuple(sorted(set(int(x.strip()) for x in parts)))
    if any(x>=2**63 for x in ids):raise RelayError('Invalid Telegram numeric user ID.')
    return ids


@contextmanager
def control_connection(executable):
    """The official proxy carries raw WebSocket bytes, NOT JSONL.

    socketpair bridges a WebSocket client to the official proxy on Windows
    Python builds without AF_UNIX. No listener or public TCP port is opened.
    """
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise RelayError('Install optional requirements-telegram.txt for the WebSocket transport.') from None
    process=subprocess.Popen([executable,'app-server','proxy'],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        env={k:v for k,v in os.environ.items() if not k.startswith('TELEGRAM_')},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    client,bridge=socket.socketpair()
    def upstream():
        try:
            while True:
                data=bridge.recv(65536)
                if not data:break
                process.stdin.write(data);process.stdin.flush()
        except OSError:pass
        finally:
            try:process.stdin.close()
            except OSError:pass
    def downstream():
        try:
            while True:
                data=os.read(process.stdout.fileno(),65536)
                if not data:break
                bridge.sendall(data)
        except OSError:pass
        finally:
            try:bridge.shutdown(socket.SHUT_WR)
            except OSError:pass
    threads=[threading.Thread(target=f,daemon=True) for f in (upstream,downstream)]
    for thread in threads:thread.start()
    try:
        with connect('ws://localhost/',sock=client,proxy=None,open_timeout=5,close_timeout=1,max_size=2**20) as connection:
            yield connection
    finally:
        client.close();bridge.close()
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        for thread in threads:thread.join(timeout=1)


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
        def receive(connection,ident):
            import time
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                result=json.loads(connection.recv(timeout=max(.01,deadline-time.monotonic())))
                if result.get('id')==ident:
                    if 'error' in result:raise RelayError('Existing session is unavailable on the shared Codex server.')
                    return result.get('result',{})
            raise RelayError('Shared Codex server handshake timed out; no message sent.')
        try:
            with control_connection(self.executable) as connection:
                connection.send(json.dumps({'id':1,'method':'initialize','params':{'clientInfo':{'name':'private_telegram_relay','title':'Private Telegram Relay','version':'1.0.0'}}}))
                receive(connection,1)
                connection.send(json.dumps({'method':'initialized','params':{}}))
                connection.send(json.dumps({'id':2,'method':'thread/read','params':{'threadId':self.thread,'includeTurns':False}}))
                thread=receive(connection,2).get('thread',{})
                if thread.get('id')!=self.thread:raise RelayError('The server did not confirm the exact configured session.')
                status=thread.get('status',{}).get('type')
                if status not in ('idle','active'):
                    raise RelayError('The saved chat is not live on this shared server. Reopening it here would create a second execution context; no message sent.')
                return True
        except RelayError:raise
        except Exception:
            # Protocol/network exceptions can contain addresses or payloads.
            raise RelayError('Shared Codex WebSocket connection failed; nothing was forwarded.') from None

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
    def __init__(self,cfg,session,api,users=None):
        self.users=allowed_users({},cfg.owner) if users is None else allowed_users({'TELEGRAM_ALLOWED_USER_IDS':','.join(str(x) for x in users)})
        if not self.users:raise RelayError('Configure at least one private allowed user.')
        self.cfg=cfg;self.session=session;self.api=api;self.path=cfg.state/'relay.json'
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'allowed_users':list(self.users),'thread':session.thread,'offset':0,'initialized':False}
        saved=self.data.get('allowed_users',[self.data.get('owner')])
        if saved!=list(self.users) or self.data['thread']!=session.thread:raise RelayError('Relay state belongs to a different allowlist/session. Reconcile locally.')
    def save(self):atomic_json(self.path,self.data)
    def handle(self,u):
        ident=u.get('update_id')
        if not isinstance(ident,int) or ident<self.data['offset']:return
        self.data['offset']=ident+1;self.save()
        m=u.get('message',{});chat=m.get('chat',{});sender=m.get('from',{})
        sender_id=sender.get('id')
        if (not isinstance(sender_id,int) or isinstance(sender_id,bool) or sender_id not in self.users
            or sender.get('is_bot') or chat.get('id')!=sender_id or chat.get('type')!='private'):return
        text=m.get('text')
        if not isinstance(text,str) or not text.strip():
            self.api.text(sender_id,'This relay supports text only. Attach files directly in Codex.');return
        if text=='/start':
            self.api.text(sender_id,'Private text relay to the shared fixed Codex session. Messages are queued verbatim. Replies and approvals remain in Codex for this first version.');return
        self.data['last_delivery']='attempting';self.data['last_sender']=sender_id;self.save()
        try:self.session.send(text)
        except RelayError:
            self.data['last_delivery']='unconfirmed';self.save()
            self.api.text(sender_id,'Message delivery was not confirmed. Check Codex before resending. No separate session or clipping job was started by this relay.');return
        self.data['last_delivery']='queued';self.save()
        self.api.text(sender_id,'Queued to your existing Codex session. Read the reply in Codex.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['doctor','run']);parser.add_argument('--persistent',action='store_true');args=parser.parse_args()
    interpreter_dir=Path(os.sys.executable).parent
    for trust in (interpreter_dir/'ca.pem',interpreter_dir.parent/'ca.pem'):
        if trust.is_file():
            os.environ.setdefault('SSL_CERT_FILE',str(trust));break
    try:
        cfg=Config.load(ROOT);values={**dotenv_values(ROOT/'.env'),**os.environ}
        users=allowed_users(values,cfg.owner)
        if args.persistent and args.command=='run':
            if not cfg.token or not users:raise RelayError('Configure the bot token and allowed users first.')
            from telegram_bridge.persistent import run
            secrets=tuple(v for k,v in values.items() if v and any(tag in k.upper() for tag in ('KEY','TOKEN','PASSWORD','SECRET')))
            with singleton(cfg.state/'bot.lock'):run(cfg,users,secrets)
            return
        thread=values.get('TELEGRAM_CODEX_THREAD_ID','')
        if args.persistent:
            receipt=cfg.state/'persistent-conversation.json'
            if not receipt.exists():raise RelayError('Persistent conversation has not been created yet.')
            record=json.loads(receipt.read_text(encoding='utf-8'))
            if record.get('users')!=list(users) or record.get('cwd')!=str(ROOT.resolve()):raise RelayError('Persistent conversation binding mismatch.')
            thread=record.get('thread','')
        session=Session(cfg.codex,thread);session.check()
        if args.command=='doctor':
            print(json.dumps({'existing_session_reachable':True,'telegram_configured':bool(cfg.token and users),'allowed_user_count':len(users),'message_sent':False,'generation_started':False}));return
        if not cfg.token or not users:raise RelayError('Configure the bot token and private allowed users first.')
        # Reuse the old lock to prevent running both Telegram transports.
        with singleton(cfg.state/'bot.lock'):
            api=API(cfg.token);relay=Relay(cfg,session,api,users)
            if not relay.data['initialized']:
                old=api.updates(-1,0);relay.data['offset']=max([u['update_id']+1 for u in old]+[relay.data['offset']]);relay.data['initialized']=True;relay.save()
            while True:
                for update in api.updates(relay.data['offset']):relay.handle(update)
    except RelayError as error:
        print('Relay not connected: '+str(error))
        return 1
    except (TelegramError,OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        print('Relay not connected. Check private configuration and the existing shared Codex server. No automatic restart or alternate session.')
        return 1

if __name__=='__main__':raise SystemExit(main())
