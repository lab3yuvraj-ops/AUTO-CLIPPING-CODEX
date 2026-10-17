import json
from types import SimpleNamespace
import pytest
import telegram_relay as mod
from telegram_bridge.config import Config

TID='12345678-1234-1234-1234-123456789abc'
class API:
    def __init__(self):self.messages=[]
    def text(self,owner,text):self.messages.append(text)
class Session:
    thread=TID
    def __init__(self):self.sent=[];self.fail=False
    def send(self,text):
        if self.fail:raise mod.RelayError('private error')
        self.sent.append(text)
def update(i,text,owner=42):
    return {'update_id':i,'message':{'from':{'id':owner},'chat':{'id':owner,'type':'private'},'text':text}}
def test_verbatim_fixed_session_duplicate_and_owner(tmp_path):
    cfg=Config(tmp_path,token='secret',owner=42);session=Session();api=API();relay=mod.Relay(cfg,session,api)
    text='Please clip this. How many?\nNo template changes.'
    relay.handle(update(1,text));relay.handle(update(1,text));relay.handle(update(2,'bad',99))
    assert session.sent==[text] and relay.data['last_delivery']=='queued'
    assert text not in relay.path.read_text() and 'secret' not in relay.path.read_text()
    restored=mod.Relay(cfg,session,api);restored.handle(update(1,text));assert len(session.sent)==1

def test_failure_never_retries_or_claims_delivery(tmp_path):
    session=Session();session.fail=True;api=API();relay=mod.Relay(Config(tmp_path,owner=42),session,api)
    relay.handle(update(1,'hello'));relay.handle(update(1,'hello'))
    assert not session.sent and relay.data['last_delivery']=='unconfirmed'
    assert 'not confirmed' in api.messages[-1] and 'private error' not in str(api.messages)

def test_queue_only_after_readiness_preserves_options_and_raw_text(monkeypatch):
    monkeypatch.setattr(mod.shutil,'which',lambda _: 'codex.exe')
    session=mod.Session('codex',TID);checks=[];runs=[]
    monkeypatch.setattr(session,'check',lambda:checks.append(True))
    monkeypatch.setattr(mod.subprocess,'run',lambda args,**kw:runs.append((args,kw)) or SimpleNamespace(returncode=0))
    session.send('--never change captions\nhello')
    assert checks==[True]
    args,kw=runs[0];assert args==['codex.exe','queue','--thread',TID,'--message=--never change captions\nhello']
    assert not kw.get('shell') and 'exec' not in args
    monkeypatch.setattr(session,'check',lambda:(_ for _ in ()).throw(mod.RelayError('offline')))
    with pytest.raises(mod.RelayError):session.send('test')
    assert len(runs)==1

def test_thread_configuration_is_required_and_never_guessed(monkeypatch):
    monkeypatch.setattr(mod.shutil,'which',lambda _: 'codex.exe')
    for value in ('','latest','other; command'):
        with pytest.raises(mod.RelayError):mod.Session('codex',value)

def test_readonly_check_uses_exact_thread_without_resume_or_generation(monkeypatch):
    import io
    monkeypatch.setattr(mod.shutil,'which',lambda _: 'codex.exe')
    class Pipe(io.StringIO):
        pass
    class Proc:
        def __init__(self):
            self.stdin=Pipe();self.stdout=iter([json.dumps({'id':1,'result':{}})+'\n',json.dumps({'id':2,'result':{'thread':{'id':TID}}})+'\n']);self.stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self,timeout):return 0
    p=Proc();calls=[]
    monkeypatch.setattr(mod.subprocess,'Popen',lambda args,**kwargs:calls.append(args) or p)
    assert mod.Session('codex',TID).check()
    assert calls==[['codex.exe','app-server','proxy']]
    sent=[json.loads(x) for x in p.stdin.getvalue().splitlines()]
    assert [x['method'] for x in sent]==['initialize','initialized','thread/read']
    assert sent[-1]['params']['threadId']==TID

def test_all_allowlisted_users_forward_verbatim_without_cross_chat_notifications(tmp_path):
    class DestAPI(API):
        def __init__(self):super().__init__();self.recipients=[]
        def text(self,owner,text):self.recipients.append(owner);super().text(owner,text)
    users=(42,43,44,45);session=Session();api=DestAPI();relay=mod.Relay(Config(tmp_path),session,api,users)
    for i,owner in enumerate(users,1):relay.handle(update(i,'hello '+str(owner),owner))
    assert session.sent==['hello '+str(x) for x in users]
    assert api.recipients==list(users)
    relay.handle(update(5,'not allowed',99));assert len(session.sent)==4
    u=update(6,'group',42);u['message']['chat']['type']='group';relay.handle(u)
    u=update(7,'spoof',42);u['message']['chat']['id']=43;relay.handle(u)
    assert len(session.sent)==4
    assert mod.Relay(Config(tmp_path),session,api,users).data['offset']==8
    with pytest.raises(mod.RelayError):mod.Relay(Config(tmp_path),session,api,(42,43))


def test_allowlist_parsing_is_explicit_bounded_and_defaults_to_single_owner():
    assert mod.allowed_users({},42)==(42,)
    assert mod.allowed_users({'TELEGRAM_ALLOWED_USER_IDS':'43, 42,43'},99)==(42,43)
    assert mod.allowed_users({},0)==()
    for raw in ('42,','0','-4','true','42; command',str(2**63),','.join(str(x) for x in range(1,22))):
        with pytest.raises(mod.RelayError):mod.allowed_users({'TELEGRAM_ALLOWED_USER_IDS':raw})
