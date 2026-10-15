import copy,json
from pathlib import Path
import pytest
from reel_engine.review_policy import choose_policy,save_policy,spec_hash,record_inspection
from reel_engine.youtube_transcript import atomic_json


def stable_records():
    job={'id':'presenter_test','source':'source','source_sha256':'finalhash','fast':False,'crop_strategy':'fixed',
         'passage_classification':{'classification':'single/dominant-presenter'}}
    spec={'candidate':{'start':0.,'end':35.,'passage_evidence':{'animated':False,'classification':'single/dominant-presenter'}},
          'words':[],'tracking':{'stable_framing':True,'stable_framing_evidence':'Source-reviewed stable portrait focus',
                                 'confirmed':True,'unresolved':False}}
    checks={'passed':True,'spec_sha256':spec_hash(spec),'crop_safety':{'passed':True},
            'motion_check':{'proxy_sha256':'proxyhash','flagged_scenes':[],'flagged_source_seconds':[]}}
    return job,spec,checks


@pytest.mark.parametrize('fast',[False,True])
@pytest.mark.parametrize('kind',['single/dominant-presenter','single-narrator-with-stable-framing'])
def test_stable_zero_flags_reduced_in_both_modes(fast,kind,tmp_path):
    job,spec,checks=stable_records();job['fast']=fast;spec['candidate']['passage_evidence']['classification']=kind
    policy=save_policy(tmp_path,job,spec,checks)
    assert policy['policy']=='stable-baseline-exceptions' and policy['baseline_required']
    assert not policy['full_first_pass'] and json.loads((tmp_path/'review-policy.json').read_text())['reason']


@pytest.mark.parametrize('problem',['animated','identity','motion','boundary','crop','missing_motion','unstable'])
def test_flags_and_identity_never_use_reduced_review(problem):
    job,spec,checks=stable_records()
    if problem=='animated':spec['candidate']['passage_evidence']['animated']=True
    if problem=='identity':spec['candidate']['passage_evidence']['screen_identity_matters']=True
    if problem=='motion':checks['motion_check']['flagged_source_seconds']=[2.]
    if problem=='boundary':checks['boundary_flags']=[{'time':0}]
    if problem=='crop':checks['crop_safety']['violations']=[{'time':1}]
    if problem=='missing_motion':checks['motion_check']={}
    if problem=='unstable':spec['tracking']['stable_framing']=False
    assert choose_policy(job,spec,checks)['full_first_pass']


def test_full_policy_contains_every_scene_and_baseline():
    from reel_engine.review import compact_review_groups
    edit={'segments':[{'source_start':0,'source_end':60,'output_start':0,'output_end':60}]}
    tracking={'review_coverage':'all-scenes','visual_targets':[{'start':i*5,'end':i*5+5} for i in range(12)]}
    groups=compact_review_groups(edit,tracking)
    assert groups[0][0]==-1
    stamps=[t for group,points in groups if group>=0 for t in points]
    assert all(any(i*5<=t<i*5+5 for t in stamps) for i in range(12))


def test_full_contextual_review_has_coverage_without_character_boxes():
    from reel_engine.review import compact_review_groups
    edit={'segments':[{'source_start':0,'source_end':60,'output_start':0,'output_end':60}]}
    tracking={'review_coverage':'all-scenes','context_scenes':[{'start':i*10,'end':i*10+10} for i in range(6)]}
    points=[t for _,values in compact_review_groups(edit,tracking) for t in values]
    assert all(any(i*10<=t<i*10+10 for t in points) for i in range(6))


def test_render_requires_inspected_baseline_and_policy_match(tmp_path,monkeypatch):
    import reel
    from PIL import Image
    from reel_engine import preflight
    from reel_engine.render import file_hash
    job,spec,checks=stable_records();root=tmp_path
    monkeypatch.setattr(preflight,'preflight',lambda *a:checks)
    monkeypatch.setattr(reel,'engine_version',lambda:'engine')
    with pytest.raises(ValueError,match='Generate and inspect'):reel._pre_render_review_guard(job,spec,{}, {},root)
    policy=save_policy(root,job,spec,checks)
    folder=root/'review';folder.mkdir();page=folder/'page-baseline-01.jpg';Image.new('RGB',(30,30),'white').save(page)
    atomic_json(folder/'review.json',{'pages':[str(page)],'final_source_sha256':'finalhash','page_hashes':{str(page):file_hash(page)}})
    atomic_json(root/'review-result.json',{'preflight':checks,'review_policy':policy,'review_engine_version':'engine'})
    with pytest.raises(ValueError,match='Inspect the baseline'):reel._pre_render_review_guard(job,spec,{}, {},root)
    record_inspection(root,'pre',[page]);reel._pre_render_review_guard(job,spec,{}, {},root)
    spec['candidate']['passage_evidence']['animated']=True
    with pytest.raises(ValueError,match='policy changed'):reel._pre_render_review_guard(job,spec,{}, {},root)


def test_explicit_phases_are_clip_scoped_and_parent_reported(tmp_path):
    from reel_engine.timing import interactive_phase,report
    for clip in ('clip_one_test','clip_two_test'):
        root=tmp_path/'jobs'/clip;root.mkdir(parents=True)
        atomic_json(root/'job.json',{'source_job_id':'source_test','run_id':'run'})
        interactive_phase(tmp_path,clip,'review_pass','start',round_number=1)
        interactive_phase(tmp_path,clip,'review_pass','end',round_number=1)
        ledger=root/'interactive-phases.jsonl'
        assert len(ledger.read_text().splitlines())==2
    data=report(tmp_path,'source_test','run')
    assert len(data['interactive_phases'])==2 and len({i['stage'] for i in data['interactive_phases']})==2
    with pytest.raises(ValueError,match='two correction'):interactive_phase(tmp_path,'clip_one_test','correction','start',round_number=3)


def test_between_commands_reports_interactive_overlap_without_double_count(tmp_path):
    from reel_engine.timing import mark,report
    for name,a,b in [('workflow',0,100),('cli_analyze',0,20),('interactive_selection_reading_clip_1',20,70),('cli_prepare',70,100)]:
        mark(tmp_path,'test',name,'start',run_id='run',at=a)
        mark(tmp_path,'test',name,'end',run_id='run',at=b)
    data=report(tmp_path,'test')
    assert data['wall_seconds']==100 and data['untracked_wall_seconds']==0
    assert data['between_commands_wall_seconds']==50 and data['interactive_wall_seconds']==50
    assert data['interactive_between_commands_seconds']==50
