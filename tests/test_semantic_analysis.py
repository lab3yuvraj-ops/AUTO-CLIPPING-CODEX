import copy
import hashlib
import json
from PIL import Image
import pytest
from reel_engine import semantic_analysis as semantic


def data(tmp_path):
    p=tmp_path/'frame.jpg';Image.new('RGB',(80,45),'blue').save(p)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    details={'source_sha256':'source','frames':[{'file':str(p),'sha256':sha,'source_seconds':10.}]}
    base={'candidate':{'start':10.,'end':45.},'words':[],'tracking':{}}
    proposal={'source_sha256':'source','model_version':'local-v1','scenes':[{'id':'river','start':10.,'end':45.,'center':.6,
        'kind':'object','confidence':.9,'evidence':'Full shadow independently located in frame','evidence_frames':[sha],
        'subject_boxes':[{'t':10.,'box':[.5,.2,.2,.5],'visible_subject_box':[.5,.2,.2,.5],'bounds_evidence':'Visible shadow bounds'}]}]}
    return base,details,proposal


def test_disabled_vision_makes_no_requests_and_records_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(semantic.httpx,'post',lambda *a,**kw:pytest.fail('Disabled provider must not run'))
    b,d,_=data(tmp_path);r=semantic.analyze(b,d,{},tmp_path/'out')
    assert r['status']=='needs_review' and r['api_calls']==0


def test_grounded_vision_cache_validates_content_and_transcript_changes(tmp_path,monkeypatch):
    b,d,p=data(tmp_path);calls=[]
    class Response:
        status_code=200;content=b'{}'
        def json(self):return {'choices':[{'message':{'content':json.dumps(p)}}]}
    def post(*args,**kwargs):calls.append(kwargs);return Response()
    monkeypatch.setattr(semantic.httpx,'post',post)
    kw=dict(endpoint='http://localhost:8080/v1/chat/completions',model='local-v1')
    r=semantic.analyze(b,d,{'text':'river'},tmp_path/'out',**kw)
    assert r['status']=='proposal_needs_inspection' and len(calls)==1
    assert semantic.analyze(b,d,{'text':'river'},tmp_path/'out',**kw)['cache_reused']
    assert len(calls)==1
    semantic.analyze(b,d,{'text':'different'},tmp_path/'out',**kw);assert len(calls)==2
    p['scenes'][0]['evidence_frames']=['fake']
    r=semantic.analyze(b,d,{'text':'new'},tmp_path/'out',**kw)
    assert r['status']=='needs_review' and r['api_calls']==1


def test_remote_requires_explicit_opt_in(tmp_path):
    b,d,_=data(tmp_path)
    with pytest.raises(ValueError,match='opt-in'):semantic.analyze(b,d,{},tmp_path/'out',endpoint='https://example.com/chat',model='v1')


def test_changed_input_frame_is_never_trusted(tmp_path):
    b,d,_=data(tmp_path);open(d['frames'][0]['file'],'wb').write(b'changed')
    with pytest.raises(ValueError,match='frame changed'):semantic.analyze(b,d,{},tmp_path/'out',endpoint='http://localhost:8080/chat',model='v1')


def test_non_object_model_response_returns_review_without_retry(tmp_path,monkeypatch):
    b,d,_=data(tmp_path);calls=[]
    class Response:
        status_code=200;content=b'{}'
        def json(self):return {'choices':[{'message':{'content':'[]'}}]}
    def post(*a,**kw):calls.append(1);return Response()
    monkeypatch.setattr(semantic.httpx,'post',post)
    result=semantic.analyze(b,d,{},tmp_path/'out',endpoint='http://localhost:8080/chat',model='v1')
    assert result['status']=='needs_review' and len(calls)==1
