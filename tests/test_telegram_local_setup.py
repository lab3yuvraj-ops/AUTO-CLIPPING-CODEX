import json
from pathlib import Path
from types import SimpleNamespace
from telegram_bridge.local_setup import inspect_setup,instructions
from telegram_bridge.config import Config
from telegram_bridge.persistent import Conversation

def test_only_current_clone_env_is_read_and_values_never_enter_context(tmp_path,monkeypatch):
    monkeypatch.delenv('HF_TOKEN',raising=False);monkeypatch.delenv('ZERNIO_API_KEY',raising=False)
    (tmp_path/'.env').write_text('HF_TOKEN=do-not-copy-parent-secret\n')
    root=tmp_path/'student';root.mkdir();(root/'.env').write_text('ZERNIO_API_KEY=private-student-key\n')
    report,secrets=inspect_setup(root)
    assert report['configured']['ZERNIO_API_KEY'] is True and report['configured']['HF_TOKEN'] is False
    context,secrets=instructions(root)
    assert 'private-student-key' not in context and 'do-not-copy-parent-secret' not in context
    assert 'private-student-key' in secrets and 'do-not-copy-parent-secret' not in secrets
    assert 'Never request keys' in context

def test_existing_project_runtime_and_cached_models_are_detected(tmp_path):
    python=tmp_path/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.write_bytes(b'fixture')
    (tmp_path/'.env').write_text('HF_TOKEN=private-hf-key\nZERNIO_INSTAGRAM_ID=account-id\n')
    calls=[]
    def run(args,**kwargs):
        calls.append((args,kwargs));return SimpleNamespace(returncode=0,stdout=json.dumps({'ready_for_media':True,'missing_packages':[],'whisper_model_cached':True,'cpu_only':True}))
    report,_=inspect_setup(tmp_path,run=run)
    assert report['media_ready'] and report['models_cached'] and report['missing_packages']==[]
    assert report['configured']['HF_TOKEN'] and report['configured']['ZERNIO_INSTAGRAM_ID']
    assert calls[0][0]==[str(python.resolve()),str(tmp_path/'reel.py'),'doctor']
    assert calls[0][1]['cwd']==tmp_path.resolve()

def test_config_updates_are_detected_without_a_new_conversation(tmp_path,monkeypatch):
    monkeypatch.delenv('HF_TOKEN',raising=False)
    env=tmp_path/'.env';env.write_text('HF_TOKEN=\n')
    before,_=inspect_setup(tmp_path);assert not before['configured']['HF_TOKEN']
    env.write_text('HF_TOKEN=new-private-key\n')
    after,_=inspect_setup(tmp_path);assert after['configured']['HF_TOKEN']

def test_next_message_refreshes_setup_and_keeps_text_verbatim(tmp_path):
    class API:
        def text(self,*args):pass
    c=Conversation(Config(tmp_path),(42,),API());c.data['thread']='own-thread';c.data['queue']=[{'id':'message-id','owner':42,'text':'One'}]
    c.thread_params=lambda:{'developerInstructions':'setup refreshed','cwd':str(tmp_path)}
    calls=[]
    def rpc(method,params):
        calls.append((method,params));return {'turn':{'id':'new-turn'}} if method=='turn/start' else {}
    c.rpc=rpc;c.launch_next()
    assert [m for m,_ in calls]==['thread/resume','turn/start']
    assert calls[0][1]['threadId']=='own-thread'
    assert calls[1][1]['input']==[{'type':'text','text':'One'}]
    assert c.data['active']['turn']=='new-turn'
