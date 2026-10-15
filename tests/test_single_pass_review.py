import json
from pathlib import Path
import pytest
from reel_engine.youtube_transcript import atomic_json


def test_single_pass_policy_does_not_claim_visual_quality_pass():
    from reel_engine.review_policy import choose_policy
    policy=choose_policy({'review_mode':'single-pass','source_sha256':'h'},{'tracking':{}},{'passed':False})
    assert policy['policy']=='single-pass' and not policy['pre_render_zero_flags']
    assert policy['baseline_required'] and policy['correction_cap']==0


def test_repeat_visual_review_reuses_receipt_and_changed_spec_cannot_loop(tmp_path,monkeypatch):
    import reel
    from reel_engine.review_policy import spec_hash
    ident='abcdefghijk-clip1';root=tmp_path/'jobs'/ident;root.mkdir(parents=True)
    spec={'candidate':{},'tracking':{}};spec_path=root/'spec.json';atomic_json(spec_path,spec)
    atomic_json(root/'job.json',{'review_mode':'single-pass','source_sha256':'hash'})
    atomic_json(root/'review-result.json',{'preflight':{'spec_sha256':spec_hash(spec)},
        'review_engine_version':'test','review_policy':{'source_sha256':'hash'}})
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel,'engine_version',lambda:'test')
    monkeypatch.setattr(reel,'prepare_edit',lambda *a:pytest.fail('No second review build'))
    assert reel._review(ident,spec_path)['cache_reused']
    atomic_json(spec_path,{'candidate':{'changed':True},'tracking':{}})
    with pytest.raises(ValueError,match='single visual pass is complete'):
        reel._review(ident,spec_path)


def test_render_reuses_preflight_and_accepted_minor_defects(tmp_path,monkeypatch):
    import reel
    from PIL import Image
    from reel_engine import preflight
    from reel_engine.review_policy import choose_policy,spec_hash,record_inspection
    spec={'tracking':{}}
    job={'review_mode':'single-pass','source':'source.mkv','source_sha256':'hash'}
    checks={'passed':False,'source_sha256':'hash','spec_sha256':spec_hash(spec),'crop_safety':{'violations':[{'scene':1}]}}
    page=tmp_path/'sheet.png';Image.new('RGB',(10,10)).save(page)
    (tmp_path/'review').mkdir()
    atomic_json(tmp_path/'review'/'review.json',{'pages':[str(page)],'final_source_sha256':'hash'})
    atomic_json(tmp_path/'review-result.json',{'preflight':checks,'review_policy':choose_policy(job,spec,checks),'review_engine_version':'test'})
    record_inspection(tmp_path,'pre',[page])
    monkeypatch.setattr(reel,'engine_version',lambda:'test')
    monkeypatch.setattr(reel,'digest',lambda *a:'hash')
    monkeypatch.setattr(preflight,'preflight',lambda *a:pytest.fail('No second preflight'))
    tracking={};reel._pre_render_review_guard(job,spec,{},tracking,tmp_path)
    assert any('without a correction loop' in w for w in tracking['editorial_warnings'])
    # A changed recipe cannot inherit the old inspection.
    with pytest.raises(ValueError,match='exact source/spec'):
        reel._pre_render_review_guard(job,{'tracking':{'changed':True}},{},{},tmp_path)


def test_one_render_no_post_render_screenshots_and_approval_still_required(tmp_path,monkeypatch):
    import reel
    from reel_engine import final_review,outro
    ident='abcdefghijk-clip1';root=tmp_path/'jobs'/ident;root.mkdir(parents=True)
    job={'id':ident,'source':'source','source_sha256':'hash','review_mode':'single-pass'}
    atomic_json(root/'job.json',job);spec=root/'spec.json';atomic_json(spec,{'candidate':{'start':0,'end':35}})
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel,'prepare_edit',lambda *a:({'words':[]},{'visual_targets':[]}))
    monkeypatch.setattr(reel,'_pre_render_review_guard',lambda job,*a:job.update(review_policy={'policy':'single-pass'}))
    monkeypatch.setattr(outro,'resolve_outro',lambda *a:None)
    monkeypatch.setattr(final_review,'sample_final',lambda *a:pytest.fail('No post-render screenshot extraction'))
    calls=[]
    def render(src,edit,tracking,path,config):
        calls.append('render');path.write_bytes(b'finished');return {'caption_events':[],'timings':{}}
    monkeypatch.setattr(reel,'render_clip',render)
    monkeypatch.setattr(reel,'validate_render',lambda *a,**kw:[{'status':'pass'}])
    result=reel._render(ident,spec)
    assert calls==['render'] and result['status']=='Needs approval'
    assert result['final_mp4_review']['performed'] is False and not result.get('approval')
    with pytest.raises(ValueError,match='exact render'):reel.publish(ident)
