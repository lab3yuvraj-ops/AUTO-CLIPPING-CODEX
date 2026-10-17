import json
from pathlib import Path
import pytest
from telegram_bridge.config import Config
from telegram_bridge.persistent import Conversation, safe_text

class API:
    def __init__(self):self.messages=[];self.videos=[]
    def text(self,owner,text):self.messages.append((owner,text))
    def video(self,owner,path):self.videos.append((owner,path))
def controller(tmp_path):
    cfg=Config(tmp_path,token='private',owner=42);api=API();c=Conversation(cfg,(42,43),api)
    c.data['thread']='new-persistent-thread';c.ready.set();return c,api
def message(i,text,owner=42):
    return {'update_id':i,'message':{'from':{'id':owner},'chat':{'id':owner,'type':'private'},'text':text}}
def test_messages_are_verbatim_queued_once_for_shared_conversation(tmp_path):
    c,api=controller(tmp_path);text='Hello\nclip this URL'
    c.handle(message(1,text));c.handle(message(1,text));c.handle(message(2,'Other user',43));c.handle(message(3,'Not allowed',99))
    assert [x['text'] for x in c.data['queue']]==[text,'Other user']
    assert [x[0] for x in api.messages]==[42,43]
    assert c.data['thread']=='new-persistent-thread'
def test_questions_return_to_initiator_without_tool_output_broadcast(tmp_path):
    c,api=controller(tmp_path);c.data['active']={'owner':43,'turn':'turn-1'}
    c.event({'method':'item/completed','params':{'threadId':c.data['thread'],'item':{'type':'commandExecution','output':'PRIVATE'}}})
    c.event({'method':'item/completed','params':{'threadId':c.data['thread'],'item':{'type':'agentMessage','phase':'final_answer','text':'How many clips?'}}})
    c.event({'method':'turn/completed','params':{'threadId':c.data['thread'],'turn':{'id':'turn-1','status':'completed'}}})
    assert api.messages==[(43,'How many clips?')] and c.data['active'] is None
    c.handle(message(4,'Two',43));assert c.data['queue'][0]['text']=='Two'
def test_disconnected_messages_not_accepted_and_active_restart_blocks(tmp_path):
    c,api=controller(tmp_path);c.ready.clear();c.handle(message(1,'Hello'));assert not c.data['queue']
    c.data['active']={'owner':42,'text':'prior task'};c.save()
    with pytest.raises(ValueError,match='interrupted'):Conversation(c.cfg,c.users,api)
def test_new_setup_creates_own_conversation_not_desktop_thread(tmp_path):
    c,api=controller(tmp_path);c.data['thread']=None;calls=[]
    class WS:
        def send(self,text):pass
    c.ws=WS()
    def rpc(method,params):
        calls.append((method,params))
        return {'thread':{'id':'created-own-thread','cwd':str(tmp_path)}} if method=='thread/start' else {}
    c.rpc=rpc;c.setup()
    assert c.data['thread']=='created-own-thread'
    assert [x[0] for x in calls]==['initialize','thread/start']
    params=calls[-1][1];assert params['sandbox']=='workspace-write' and params['modelProvider']=='openai'
    assert 'model' not in params and 'never publish' in params['developerInstructions'].lower()
def test_existing_own_conversation_resumes_exact_id(tmp_path):
    c,api=controller(tmp_path);calls=[]
    class WS:
        def send(self,text):pass
    c.ws=WS()
    def rpc(method,params):
        calls.append((method,params));return {'thread':{'id':c.data['thread'],'cwd':str(tmp_path)}} if method=='thread/resume' else {}
    c.rpc=rpc;c.setup()
    assert calls[-1][0]=='thread/resume' and calls[-1][1]['threadId']=='new-persistent-thread'
def test_secrets_removed_from_assistant_text():
    assert safe_text('Keep private secret-value here',('secret-value',))=='Keep private [redacted] here'
    assert 'ghp_' not in safe_text('ghp_'+'x'*30)

def test_actual_video_delivery_requires_hash_and_is_deduplicated_per_user(tmp_path):
    import hashlib
    c,api=controller(tmp_path);folder=tmp_path/'workflow/jobs/fresh-clip';folder.mkdir(parents=True)
    video=folder/'reel.mp4';video.write_bytes(b'real-test-media')
    record={'video':str(video.resolve()),'status':'Needs approval','render_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'checks':[{'status':'pass'}]}
    (folder/'job.json').write_text(json.dumps(record));c.reply='Preview: '+str(video.resolve())
    c.deliver_video(42);c.deliver_video(42);c.deliver_video(43)
    assert [x[0] for x in api.videos]==[42,43]
    video.write_bytes(b'changed');c.deliver_video(44);assert len(api.videos)==2


def test_no_video_for_failed_checks_or_outside_job(tmp_path):
    import hashlib
    c,api=controller(tmp_path);folder=tmp_path/'workflow/jobs/fresh-clip';folder.mkdir(parents=True)
    video=folder/'reel.mp4';video.write_bytes(b'test')
    record={'video':str(video.resolve()),'status':'Needs approval','render_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'checks':[{'status':'fail'}]}
    (folder/'job.json').write_text(json.dumps(record));c.reply=str(video.resolve());c.deliver_video(42)
    assert not api.videos
