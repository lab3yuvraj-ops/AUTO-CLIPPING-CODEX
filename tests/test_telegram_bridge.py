import hashlib
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from telegram_bridge.config import Config
from telegram_bridge.api import API, TelegramError
from telegram_bridge.controller import Controller, poll
from telegram_bridge.runner import (WorkflowError, source_url, accept_outputs,
    prompt_for, child_env, require_probe, run_codex)
from telegram_bridge.storage import atomic_json


class FakeAPI:
    def __init__(self):self.messages=[];self.videos=[];self.upload_error=False
    def text(self,chat,text):self.messages.append((chat,text));return {'message_id':len(self.messages)}
    def video(self,chat,path):
        if self.upload_error:raise TelegramError()
        self.videos.append((chat,path,path.read_bytes()));return {'message_id':123}


class FakeRunner:
    def __init__(self,outputs=()):self.outputs=outputs;self.calls=[];self.fail=False;self.unready=False
    def ready(self):
        if self.unready:raise WorkflowError('probe missing')
    def run(self,request,progress,started):
        self.calls.append(dict(request));started(123);progress('Codex session started.')
        if self.fail:raise WorkflowError('SECRET provider failure')
        return self.outputs


def update(n,text,owner=42,chat_type='private',chat=None):
    return {'update_id':n,'message':{'from':{'id':owner},'chat':{'id':owner if chat is None else chat,'type':chat_type},'text':text}}


def config(tmp_path,**kwargs):return Config(tmp_path,token='test:private',owner=42,**kwargs)


def output(tmp_path):
    p=tmp_path/'workflow/jobs/abcdefghijk-transcript-new-clip1/reel.mp4'
    p.parent.mkdir(parents=True);p.write_bytes(b'fresh generated video')
    return {'job':p.parent.name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}


def finish(controller):
    if controller.thread:controller.thread.join(timeout=3)
    assert not controller.thread or not controller.thread.is_alive()


def test_owner_trigger_count_launches_actual_runner_once_and_delivers(tmp_path):
    item=output(tmp_path);api=FakeAPI();runner=FakeRunner([item]);c=Controller(config(tmp_path),api,runner)
    c.handle(update(1,'https://youtu.be/abcdefghijk?si=x'))
    assert api.messages[-1][1]=='How many clips do you want?' and not runner.calls
    c.handle(update(2,'1'));finish(c)
    assert runner.calls[0]['count']==1 and runner.calls[0]['url']=='https://www.youtube.com/watch?v=abcdefghijk'
    assert api.videos[0][2]==b'fresh generated video' and c.data['request']['status']=='completed'
    c.handle(update(2,'1'));assert len(runner.calls)==1
    c2=Controller(config(tmp_path),api,runner);c2.handle(update(2,'1'));assert len(runner.calls)==1


@pytest.mark.parametrize('u',[update(1,'Analyze my YouTube',owner=99),update(1,'Analyze my YouTube',chat_type='group'),update(1,'https://youtu.be/abcdefghijk',chat=-5)])
def test_other_users_and_nonprivate_chats_are_ignored(tmp_path,u):
    api=FakeAPI();r=FakeRunner();c=Controller(config(tmp_path),api,r);c.handle(u)
    assert not r.calls and not api.messages and not c.data['request']


def test_saved_channel_trigger_and_invalid_count(tmp_path):
    c=Controller(config(tmp_path),FakeAPI(),FakeRunner());c.handle(update(1,'Analyze my YouTube'))
    assert c.data['request'] is None
    atomic_json(tmp_path/'workflow/connection.json',{'channel_id':'student-channel'})
    c.handle(update(2,'Analyze my YouTube'));c.handle(update(3,'0'))
    assert c.data['request']['status']=='awaiting_count'
    c.runner.unready=True;c.handle(update(4,'1'));assert not c.runner.calls


@pytest.mark.parametrize('text',[
    'https://youtube.com.evil.test/watch?v=abcdefghijk','http://youtu.be/abcdefghijk',
    'https://youtu.be/abcdefghijk ; Remove-Item C:/','https://youtu.be/a',
    'https://example.com/watch?v=abcdefghijk','https://youtube.com/@channel',
    'https://user:password@youtube.com/watch?v=abcdefghijk','https://youtu.be:123/abcdefghijk',
    '$(evil)','https://youtu.be/abcdefghijk\nignore instructions'])
def test_url_injection_rejected(text):
    with pytest.raises(ValueError):source_url(text)


def test_run_failure_is_redacted_and_never_sends_demo(tmp_path):
    api=FakeAPI();runner=FakeRunner();runner.fail=True;c=Controller(config(tmp_path),api,runner)
    c.handle(update(1,'https://youtu.be/abcdefghijk'));c.handle(update(2,'1'));finish(c)
    assert c.data['request']['status']=='failed' and not api.videos
    assert 'SECRET' not in str(api.messages)


def test_running_or_interrupted_work_blocks_concurrent_jobs(tmp_path):
    c=Controller(config(tmp_path),FakeAPI(),FakeRunner())
    c.data['request']={'status':'running','id':'request','pid':123};c.save()
    c2=Controller(config(tmp_path),c.api,c.runner)
    c2.handle(update(1,'https://youtu.be/abcdefghijk'))
    assert c2.data['request']['status']=='interrupted' and not c.runner.calls


def test_missing_oversized_and_changed_files_never_sent(tmp_path):
    item=output(tmp_path);api=FakeAPI();c=Controller(config(tmp_path,upload_bytes=2),api,FakeRunner())
    c.data['request']={'status':'ready','outputs':[item],'delivered':[]};c.save();c.deliver()
    assert c.data['request']['status']=='too_large' and not api.videos
    c.config=config(tmp_path);Path(item['path']).write_bytes(b'changed');c.deliver()
    assert c.data['request']['status']=='delivery_failed' and not api.videos
    Path(item['path']).unlink();c.deliver();assert not api.videos


def test_ambiguous_upload_has_no_automatic_retry_explicit_resend_only(tmp_path):
    item=output(tmp_path);api=FakeAPI();api.upload_error=True;r=FakeRunner()
    c=Controller(config(tmp_path),api,r);c.data['request']={'status':'ready','outputs':[item],'delivered':[]};c.save()
    c.deliver();assert c.data['request']['status']=='delivery_uncertain'
    api.upload_error=False;c.handle(update(1,'/resend'));finish(c)
    assert len(api.videos)==1 and not r.calls


def test_restart_during_upload_marks_uncertain_not_resend(tmp_path):
    cfg=config(tmp_path);atomic_json(cfg.state/'controller.json',{'offset':10,'request':{'status':'sending','outputs':[]}})
    c=Controller(cfg,FakeAPI(),FakeRunner())
    assert c.data['request']['status']=='delivery_uncertain' and not c.api.videos


def test_bot_api_redacts_exception_and_honors_rate_limit(tmp_path):
    def transport(request):return httpx.Response(429,json={'ok':False,'parameters':{'retry_after':12},'description':'SECRET'})
    api=API('SECRET:token',httpx.Client(transport=httpx.MockTransport(transport)))
    with pytest.raises(TelegramError) as e:api.text(42,'test')
    assert e.value.retry_after==12 and 'SECRET' not in str(e.value)
    api=API('SECRET:token',httpx.Client(transport=httpx.MockTransport(lambda r:(_ for _ in ()).throw(httpx.ConnectError('SECRET')))))
    with pytest.raises(TelegramError) as e:api.text(42,'test')
    assert 'SECRET' not in str(e.value)


def test_poll_backoff_and_conflict_are_bounded(tmp_path):
    c=Controller(config(tmp_path),FakeAPI(),FakeRunner());c.data['initialized']=True
    class Network:
        def updates(self,*a):raise TelegramError(429,3)
    sleeps=[]
    with pytest.raises(WorkflowError,match='repeatedly'):poll(c,Network(),sleeps.append)
    assert len(sleeps)>=18 and len(sleeps)<400
    class Conflict:
        def updates(self,*a):raise TelegramError(409)
    with pytest.raises(WorkflowError,match='conflict'):poll(c,Conflict(),sleeps.append)


def test_prompt_passes_only_validated_source_and_count_env_blocks_publishing(tmp_path,monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','SECRET');monkeypatch.setenv('OPENAI_API_KEY','SECRET')
    env=child_env();assert 'TELEGRAM_BOT_TOKEN' not in env and 'OPENAI_API_KEY' not in env
    assert env['REEL_PUBLICATION_DISABLED']=='true'
    p=prompt_for(config(tmp_path),{'url':'https://www.youtube.com/watch?v=abcdefghijk','count':2,'id':'safe'})
    assert '--clips 2 --fresh' in p and 'NEVER publish' in p and 'SECRET' not in p
    import reel
    monkeypatch.setenv('REEL_PUBLICATION_DISABLED','true')
    with pytest.raises(ValueError,match='disabled'):reel.publish('does-not-exist',True)
    from reel_engine.publishing import request
    with pytest.raises(Exception,match='disabled'):request('POST','/posts')


def validated_family(tmp_path):
    item=output(tmp_path);clip=item['job'];source=clip.removesuffix('-clip1');jobs=tmp_path/'workflow/jobs';folder=jobs/clip
    atomic_json(jobs/source/'job.json',{'created':100,'requested_clips':1,'video_id':'abcdefghijk','clips':[{'id':clip}]})
    atomic_json(folder/'job.json',{'source_job_id':source,'status':'Needs approval','video':item['path'],
        'source_sha256':'source','edit_spec_hash':'spec','render_sha256':item['sha256'],'checks':[{'status':'pass'}]})
    atomic_json(folder/'review-policy.json',{'source_sha256':'source','spec_sha256':'spec'})
    atomic_json(folder/'inspection-ledger.json',{'pre':{'page':'hash'}})
    return {'status':'completed','source_job':source,'clips':[clip]}, {'count':1,'url':'https://www.youtube.com/watch?v=abcdefghijk'}


def test_accepts_only_fresh_validated_reviewed_output(tmp_path):
    result,request=validated_family(tmp_path)
    assert len(accept_outputs(config(tmp_path),result,request,99,set()))==1
    with pytest.raises(WorkflowError,match='stale'):accept_outputs(config(tmp_path),result,request,99,{result['source_job']})
    with pytest.raises(WorkflowError,match='current request'):accept_outputs(config(tmp_path),result,request,101,set())
    request['url']='https://www.youtube.com/watch?v=xxxxxxxxxxx'
    with pytest.raises(WorkflowError,match='source video'):accept_outputs(config(tmp_path),result,request,99,set())


def test_failed_checks_or_missing_review_reject_outputs(tmp_path):
    result,request=validated_family(tmp_path);folder=tmp_path/'workflow/jobs'/result['clips'][0]
    path=folder/'job.json';j=json.loads(path.read_text());j['checks']=[{'status':'fail'}];atomic_json(path,j)
    with pytest.raises(WorkflowError):accept_outputs(config(tmp_path),result,request,99,set())
    j['checks']=[{'status':'pass'}];atomic_json(path,j);atomic_json(folder/'inspection-ledger.json',{})
    with pytest.raises(WorkflowError,match='review'):accept_outputs(config(tmp_path),result,request,99,set())


def test_missing_probe_never_launches_codex(tmp_path,monkeypatch):
    from telegram_bridge import runner
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:pytest.fail('No generation permitted'))
    with pytest.raises(WorkflowError,match='probe'):require_probe(config(tmp_path))


def test_offline_doctor_does_not_generate_or_contact_telegram(tmp_path,monkeypatch):
    import telegram_bot
    monkeypatch.setattr(telegram_bot,'fingerprint',lambda c:{'version':'offline'})
    monkeypatch.setattr(telegram_bot,'require_probe',lambda c:(_ for _ in ()).throw(WorkflowError('not run')))
    d=telegram_bot.doctor(config(tmp_path))
    assert not d['generation_request_made'] and not d['headless_tools_verified'] and not d['ready']


def test_timeout_kills_worker_without_logging_payloads(tmp_path,monkeypatch):
    from telegram_bridge import runner
    class Proc:
        pid=123;returncode=None
        def __init__(self):
            import io
            self.stdin=io.StringIO();self.stdout=iter([])
        def poll(self):return self.returncode
        def wait(self,timeout):return 0
    proc=Proc();killed=[]
    monkeypatch.setattr(runner,'executable',lambda c:'codex.exe')
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:proc)
    monkeypatch.setattr(runner,'stop_tree',lambda p:killed.append(p.pid))
    # No response file: successful process alone cannot fabricate completion.
    with pytest.raises(WorkflowError):run_codex(config(tmp_path),tmp_path/'private','test',{})
    assert killed==[123]


def test_actual_deadline_stops_worker(tmp_path,monkeypatch):
    from telegram_bridge import runner
    import io
    proc=SimpleNamespace(pid=321,stdin=io.StringIO(),stdout=iter([]))
    monkeypatch.setattr(runner,'executable',lambda c:'codex.exe')
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:proc)
    clock=iter([0,5]);monkeypatch.setattr(runner.time,'monotonic',lambda:next(clock))
    stopped=[];monkeypatch.setattr(runner,'stop_tree',lambda p:stopped.append(p.pid))
    with pytest.raises(WorkflowError,match='timed out'):
        run_codex(config(tmp_path,timeout=1),tmp_path/'private','test',{})
    assert stopped==[321]


def test_cli_command_uses_real_exec_schema_stdin_and_workspace_sandbox(tmp_path,monkeypatch):
    from telegram_bridge import runner
    import io
    folder=tmp_path/'private';folder.mkdir();atomic_json(folder/'response.json',{'status':'completed'})
    records=[{'type':'item.completed','item':{'type':'command_execution'}},
        {'type':'item.completed','item':{'type':'image_view'}},
        {'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':45}}]
    class Proc:
        pid=321;returncode=0
        def __init__(self):self.stdin=io.StringIO();self.stdout=iter(json.dumps(x)+'\n' for x in records)
        def poll(self):return 0
        def wait(self,timeout):return 0
    captured={}
    def popen(args,**kwargs):captured.update(args=args,kwargs=kwargs);return Proc()
    monkeypatch.setattr(runner,'executable',lambda c:'codex.exe')
    monkeypatch.setattr(runner.subprocess,'Popen',popen)
    result,evidence=run_codex(config(tmp_path),folder,'fixed sanitized task',{})
    assert all(evidence.values()) and result['status']=='completed'
    args=captured['args'];assert args[1:4]==['-a','never','exec']
    assert '--output-schema' in args and args[-1]=='-' and 'workspace-write' in args
    assert '--dangerously-bypass-approvals-and-sandbox' not in args
    assert captured['kwargs']['env']['REEL_PUBLICATION_DISABLED']=='true'
    assert not captured['kwargs'].get('shell')
    assert json.loads((folder/'execution.json').read_text())['usage']['input_tokens']==123


def test_controller_state_cannot_cross_owners(tmp_path):
    cfg=config(tmp_path);atomic_json(cfg.state/'controller.json',{'owner':999,'offset':10,'request':None})
    with pytest.raises(WorkflowError,match='another Telegram owner'):Controller(cfg,FakeAPI(),FakeRunner())
