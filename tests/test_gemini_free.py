import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from reel_engine import gemini_free as g
from reel_engine.config import Settings


@pytest.fixture(autouse=True)
def prohibit_real_http(monkeypatch,tmp_path):
    def forbidden(*a,**kw):pytest.fail('Real HTTP is forbidden in Gemini local tests')
    monkeypatch.setattr(httpx,'get',forbidden);monkeypatch.setattr(httpx,'post',forbidden)
    monkeypatch.setattr(g,'PRICING_CHECKED',dt.datetime.now(dt.timezone.utc).date())
    reserve=g.reserve_quota
    monkeypatch.setattr(g,'reserve_quota',lambda folder,*a,**kw:reserve(tmp_path/'isolated-quota',*a,**kw))


def settings(**kw):
    return Settings(_env_file=None,**{'gemini_enabled':True,'gemini_api_key':'fake-secret',
        'google_oauth_access_token':'fake-oauth','gemini_project_id':'student-free-project',
        'gemini_free_tier_confirmed':True,'gemini_rpm':10,**kw})


def inputs(tmp_path):
    f=tmp_path/'frame.jpg';Image.new('RGB',(1920,1080),'blue').save(f)
    sha=hashlib.sha256(f.read_bytes()).hexdigest()
    details={'source_sha256':'source','source_width':1920,'source_height':1080,
             'frames':[{'file':str(f),'sha256':sha,'source_seconds':10.}]}
    base={'candidate':{'start':10.,'end':45.},'words':[], 'tracking':{}}
    proposal={'source_sha256':'source','model_version':g.MODEL,'scenes':[{'id':'shadow','start':10.,'end':45.,
        'center':.6,'kind':'object','confidence':.9,'evidence':'River shadow, story-relevant rather than a face',
        'evidence_frames':[sha],'subject_boxes':[{'t':10.,'box':[.5,.2,.2,.5],
        'visible_subject_box':[.5,.2,.2,.5],'bounds_evidence':'Full visible shadow'}]}]}
    return base,details,proposal


class Response:
    def __init__(self,status=200,body=None,headers=None):
        self.status_code=status;self.body=body;self.headers=headers or {};self.content=json.dumps(body).encode()
    def json(self):return self.body


class Client:
    def __init__(self,proposal=None,responses=None):
        self.gets=[];self.posts=[];self.proposal=proposal;self.responses=list(responses or [])
        self.billing={'projectId':'student-free-project','billingEnabled':False,'billingAccountName':''}
        self.resource={'name':'projects/123','projectId':'student-free-project','state':'ACTIVE'}
        self.lookup={'parent':'projects/123/locations/global','name':'projects/123/locations/global/keys/abc'}
    def get(self,url,**kw):
        self.gets.append((url,kw))
        return Response(body=self.lookup if 'lookupKey' in url else self.billing if 'billingInfo' in url else self.resource)
    def post(self,url,**kw):
        self.posts.append((url,kw))
        if self.responses:return self.responses.pop(0)
        return Response(body={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(self.proposal)}]}}],
                              'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':50,'totalTokenCount':150}})


def test_authoritative_free_verification_is_read_only():
    c=Client();r=g.verify_free_project(settings(),client=c)
    assert r['verified'] and len(c.gets)==3 and not c.posts
    assert c.gets[0][1]['params']=={'keyString':'fake-secret'}
    assert 'fake-secret' not in json.dumps(r) and 'fake-oauth' not in json.dumps(r)


@pytest.mark.parametrize('change',[{'gemini_model':'gemini-2.5-pro'},{'gemini_model':'gemini-2.5-flash-image'},
    {'gemini_free_tier_confirmed':False},{'google_oauth_access_token':''},{'gemini_project_id':''}])
def test_unknown_tier_key_only_or_paid_model_stops_before_request(change):
    c=Client()
    with pytest.raises(g.FreeTierBlocked):g.verify_free_project(settings(**change),client=c)
    assert not c.posts and not c.gets


def test_expired_price_allowlist_fails_closed():
    with pytest.raises(g.FreeTierBlocked,match='expired'):
        g.verify_free_project(settings(),client=Client(),now=dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=61))


@pytest.mark.parametrize('billing',[{'projectId':'student-free-project','billingEnabled':True},
    {'projectId':'student-free-project','billingEnabled':False,'billingAccountName':'billingAccounts/paid'},
    {'projectId':'other','billingEnabled':False},{'projectId':'student-free-project'}])
def test_billed_linked_or_unknown_project_is_rejected(billing):
    c=Client();c.billing=billing
    with pytest.raises(g.FreeTierBlocked):g.verify_free_project(settings(),client=c)
    assert not c.posts


def test_mismatched_key_project_rejected():
    c=Client();c.resource['projectId']='wrong-project'
    with pytest.raises(g.FreeTierBlocked,match='match'):g.verify_free_project(settings(),client=c)
    assert len(c.gets)==2


def test_management_error_is_redacted():
    class Bad:
        def get(self,*a,**k):raise httpx.ConnectError('fake-secret fake-oauth URL')
    with pytest.raises(g.FreeTierBlocked) as e:g.verify_free_project(settings(),client=Bad())
    assert 'fake-secret' not in str(e.value) and 'fake-oauth' not in str(e.value)


def test_no_authorization_means_zero_network(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p)
    r=g.analyze(b,d,{},tmp_path/'job',settings(),client=c)
    assert r['status']=='blocked' and r['api_calls_this_run']==0 and not c.gets and not c.posts


def test_official_request_grounding_cache_and_usage(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p);root=tmp_path/'job'
    r=g.analyze(b,d,{'text':'shadow'},root,settings(),authorized=True,client=c)
    assert r['status']=='proposal_needs_inspection' and not r['semantic_quality_pass']
    assert r['api_calls_this_run']==1 and r['management_requests']==3 and r['provider_usage']['totalTokenCount']==150
    url,kw=c.posts[0];assert url==g.API_URL and '?' not in url
    assert kw['headers']['x-goog-api-key']=='fake-secret'
    payload=kw['json'];assert 'tools' not in payload and 'cachedContent' not in payload
    assert payload['generationConfig']['responseMimeType']=='application/json'
    image=payload['contents'][0]['parts'][-1]['inlineData']['data']
    import base64
    im=Image.open(io.BytesIO(base64.b64decode(image)));assert im.width<=640 and im.height<=480
    spec=json.loads((root/'semantic-proposed-spec.json').read_text())
    assert spec['tracking']['unresolved'] and not spec['tracking']['confirmed']
    assert spec['tracking']['visual_targets'][0]['kind']=='object' and spec['words']==b['words']
    cached=g.analyze(b,d,{'text':'shadow'},root,settings(),client=c)
    assert cached['cache_reused'] and cached['api_calls_this_run']==0 and len(c.posts)==1
    changed=g.analyze(b,d,{'text':'changed'},root,settings(),authorized=True,client=c)
    assert not changed['cache_reused'] and len(c.posts)==2
    for f in root.rglob('*.json*'):
        assert 'fake-secret' not in f.read_text() and 'fake-oauth' not in f.read_text()


def test_tampered_cache_not_used_without_authorization(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p);root=tmp_path/'job'
    g.analyze(b,d,{},root,settings(),authorized=True,client=c)
    f=root/'semantic-analysis.json';v=json.loads(f.read_text());v['proposal']['scenes'][0]['center']=.3;f.write_text(json.dumps(v))
    r=g.analyze(b,d,{},root,settings(),client=c);assert r['status']=='blocked' and len(c.posts)==1


@pytest.mark.parametrize('issue',['low_confidence','fake_frame','gap','model','empty','out_of_bounds','narrow'])
def test_uncertain_or_invalid_plan_never_approved(tmp_path,issue):
    b,d,p=inputs(tmp_path);s=p['scenes'][0]
    if issue=='low_confidence':s['confidence']=.2
    if issue=='fake_frame':s['evidence_frames']=['invented']
    if issue=='gap':s['start']=11.
    if issue=='model':p['model_version']='paid-model'
    if issue=='empty':p['scenes']=[]
    if issue=='out_of_bounds':s['subject_boxes'][0]['box']=[.9,.2,.2,.5]
    if issue=='narrow':s['subject_boxes'][0]['box']=[.5,.2,.1,.5]
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=Client(p))
    assert r['status']=='needs_review' and not r['semantic_quality_pass']
    assert not (tmp_path/'job/semantic-proposed-spec.json').exists()


def test_crop_warning_requires_review(tmp_path):
    b,d,p=inputs(tmp_path);p['scenes'][0]['center']=.1
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=Client(p))
    assert r['warnings'] and r['status']=='proposal_needs_inspection' and not r['semantic_quality_pass']


def test_429_pauses_and_honors_retry_after_without_paid_fallback(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p,[Response(429,{}, {'Retry-After':'180'})])
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c)
    assert r['status']=='paused' and r['retry_after_seconds']==180 and len(c.posts)==1
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c)
    assert r['status']=='blocked' and len(c.posts)==1


def test_bounded_exponential_backoff_reverifies_billing(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p,[Response(503,{}),Response(503,{})])
    waits=[];r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c,sleep=waits.append)
    assert waits==[2,4] and len(c.posts)==3 and len(c.gets)==9 and r['backoff_seconds']==6
    assert r['status']=='proposal_needs_inspection'


def test_retry_after_date_and_wait_cap(tmp_path):
    assert g.retry_delay({'Retry-After':'Thu, 01 Jan 1970 00:02:00 GMT'},0,now=0)==120
    b,d,p=inputs(tmp_path);c=Client(p,[Response(503,{}, {'Retry-After':'120'})]);waits=[]
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c,sleep=waits.append)
    assert r['status']=='paused' and len(c.posts)==1 and not waits


def test_project_quota_shared_between_runs_and_keys(tmp_path):
    s=settings(gemini_rpm=1);g.reserve_quota(tmp_path,s,100,now=100)
    with pytest.raises(g.FreeTierBlocked):g.reserve_quota(tmp_path,settings(gemini_api_key='another',gemini_rpm=1),100,now=110)
    g.reserve_quota(tmp_path,s,100,now=161)
    with pytest.raises(g.FreeTierBlocked):g.reserve_quota(tmp_path,settings(gemini_tpm=1000),2000,now=300)
    with pytest.raises(g.FreeTierBlocked):g.reserve_quota(tmp_path,settings(gemini_rpd=1),100,now=300)


def test_changed_frame_and_outside_passage_stop_before_network(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p);d['frames'][0]['source_seconds']=0
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c);assert r['status']=='blocked' and not c.gets
    d['frames'][0]['source_seconds']=10;Path(d['frames'][0]['file']).write_bytes(b'tampered')
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c);assert r['status']=='needs_review' and not c.posts


def test_no_calls_when_disabled_and_no_legacy_provider(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p)
    assert g.analyze(b,d,{},tmp_path/'job',settings(gemini_enabled=False),authorized=True,client=c)['api_calls_this_run']==0
    r=g.analyze(b,d,{},tmp_path/'job',settings(semantic_vision_url='https://paid.example'),authorized=True,client=c)
    assert r['status']=='blocked' and not c.gets


def test_unreviewed_semantic_plan_stops_before_preflight(tmp_path):
    import reel
    tracking={'semantic_review_required':True,'confirmed':False,'unresolved':True}
    with pytest.raises(ValueError,match='unreviewed'):
        reel._pre_render_review_guard({}, {}, {},tracking,tmp_path)


@pytest.mark.parametrize('status,outcome', [
    ('proposal_needs_inspection', 'success'), ('needs_review', 'failed'),
    ('paused', 'failed'), ('blocked', 'rejected')])
def test_semantic_status_closes_timing_ledger(tmp_path,status,outcome):
    from reel_engine.timing import stage, report
    with stage(tmp_path,'clip','gemini_semantic_analysis',run_id='run') as interval:
        interval.update(g.stage_result({'status':status,'cache_reused':False}))
    saved=report(tmp_path,'clip','run')
    assert not saved['open_stages']
    assert saved['intervals'][0]['outcome']==outcome
    assert saved['intervals'][0]['diagnostic']['category']==status


def test_404_stops_without_retry_or_substitution(tmp_path):
    b,d,p=inputs(tmp_path);c=Client(p,[Response(404,{'error':{'message':'unavailable'}})])
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c)
    assert r['status']=='needs_review' and r['api_calls_this_run']==1
    assert len(c.posts)==1 and r['provider_usage']=={}
    assert r['semantic_quality_pass'] is False
    assert not (tmp_path/'job'/'semantic-proposed-spec.json').exists()


def test_billing_changed_before_retry_prevents_second_inference(tmp_path):
    b,d,p=inputs(tmp_path)
    class Changes(Client):
        def post(self,*a,**kw):
            r=super().post(*a,**kw);self.billing['billingEnabled']=True;return r
    c=Changes(p,[Response(503,{})])
    r=g.analyze(b,d,{},tmp_path/'job',settings(),authorized=True,client=c,sleep=lambda t:None)
    assert r['status']=='blocked' and len(c.posts)==1 and r['management_requests']==6


def test_token_accounting_and_secrets_repr(tmp_path):
    from reel_engine.performance import summarize
    b,d,p=inputs(tmp_path);root=tmp_path/'job';s=settings();c=Client(p)
    g.analyze(b,d,{},root,s,authorized=True,client=c);g.analyze(b,d,{},root,s,client=c)
    r=summarize(root)['gemini']
    assert r['inference_calls']==1 and r['cache_hits']==1 and r['provider_usage']['totalTokenCount']==150
    assert 'fake-secret' not in repr(s) and 'fake-oauth' not in repr(s)


def test_boundary_detections_cached_but_source_and_bounds_invalidate(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from reel_engine import preflight as pf
    f=tmp_path/'source.mkv';f.write_bytes(b'first-source');calls=[]
    monkeypatch.setattr(pf,'probe',lambda p:{'format':{'duration':'100'}})
    monkeypatch.setattr(pf,'run',lambda args:(calls.append(args) or SimpleNamespace(stderr='')))
    assert pf.detect_boundary_cuts(f,10,45,tmp_path)==[] and len(calls)==2
    assert pf.detect_boundary_cuts(f,10,45,tmp_path)==[] and len(calls)==2
    f.write_bytes(b'different-source');pf.detect_boundary_cuts(f,10,45,tmp_path);assert len(calls)==4
    pf.detect_boundary_cuts(f,11,45,tmp_path);assert len(calls)==6
    cache=tmp_path/'boundary-detection-cache.json';data=json.loads(cache.read_text());data['rows']=[{'forged':True}];cache.write_text(json.dumps(data))
    pf.detect_boundary_cuts(f,11,45,tmp_path);assert len(calls)==8
