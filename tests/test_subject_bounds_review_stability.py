import copy,json
import pytest
from reel_engine.scene_table import SceneTable,build_spec
from reel_engine.review import canonical_review,scene_review_groups
from reel_engine.preflight import choose_word_boundary

def test_full_width_reference_rejects_narrow_or_missing_target():
    data={'scenes':[{'id':'subject','start':0,'end':40,'center':.5,'evidence':'Reviewed full extent','confidence':.9,'subject_boxes':[{'t':0,'box':[.42,.1,.16,.9],'visible_subject_box':[.3,.1,.4,.9],'bounds_evidence':'Actual independent source frame'}]}]}
    base={'candidate':{'start':0,'end':40},'words':[],'tracking':{}}
    with pytest.raises(ValueError,match='narrower'):build_spec(base,SceneTable.model_validate(data))
    warned=build_spec(base,SceneTable.model_validate(data),bounds_policy='warn')
    assert warned['tracking']['subject_bounds_warnings']
    assert warned['tracking']['visual_targets'][0]['box'][2]==.4
    del data['scenes'][0]['subject_boxes'][0]['visible_subject_box']
    with pytest.raises(ValueError,match='Missing independently'):build_spec(base,SceneTable.model_validate(data))

def test_camera_position_is_separate_from_full_subject_box():
    from reel_engine.visual_focus import focus_geometry
    import numpy as np
    target={'kind':'character','box':[.3,.1,.4,.9],'camera_center_keyframes':[{'t':0,'center':.6}]}
    assert focus_geometry(np.zeros((1080,1920,3),dtype='uint8'),None,target,source_time=1)==[.6,.5,1.]

def test_small_trim_preserves_canonical_timeline_and_interior_samples():
    edit={'duration':40,'segments':[{'source_start':10.,'source_end':50.,'output_start':0.,'output_end':40.}],'words':[]}
    tracking={'visual_targets':[{'start':10.,'end':30.,'scene_start':10.,'scene_end':30.,'box_keyframes':[]},{'start':30.,'end':50.,'scene_start':30.,'scene_end':50.,'box_keyframes':[]}]}
    changed=copy.deepcopy(edit);changed['segments'][0]['source_start']=10.0666667;changed['duration']-=.0666667
    revised=copy.deepcopy(tracking);revised['visual_targets'][0]['start']=10.0666667
    a,ta=canonical_review(edit,tracking);b,tb=canonical_review(changed,revised)
    assert a==b and scene_review_groups(a,ta)==scene_review_groups(b,tb)

def test_explicit_next_word_choice_preserves_next_word_and_logs(tmp_path):
    spec={'candidate':{'start':10.,'end':50.},'words':[{'id':1,'start':10.1,'end':10.3,'text':'Nathan'},{'id':2,'start':10.3,'end':10.6,'text':'sat'}],'tracking':{'visual_targets':[]}}
    changed=choose_word_boundary(spec,tmp_path,'start-next-word')
    assert changed['candidate']['start']==10.3 and [w['id'] for w in changed['words']]==[2]
    assert spec['words'][0]['id']==1
    assert json.loads((tmp_path/'word-boundary-choice.json').read_text())['removed_word']['id']==1

def test_scene_page_pixels_survive_boundary_only_trim(tmp_path,monkeypatch):
    from reel_engine.config import settings
    monkeypatch.setattr(settings,"compact_pre_review",False)
    from reel_engine.render import run
    from reel_engine.review import make_review
    from reel_engine.review_policy import pixel_hash
    video=tmp_path/'source.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30:d=6','-f','lavfi','-i','sine=frequency=440:duration=6','-c:v','libx264','-c:a','aac',str(video)])
    edit={'duration':6.,'segments':[{'source_start':0.,'source_end':6.,'output_start':0.,'output_end':6.}],'words':[]}
    targets=[{'start':float(i),'end':float(i+1),'scene_start':float(i),'scene_end':float(i+1),'kind':'character','box':[.4,.1,.2,.8],'box_keyframes':[{'t':float(i),'box':[.4,.1,.2,.8]}],'confidence':.9,'reason':str(i),'evidence':'Synthetic reviewed target'} for i in range(6)]
    tracking={'visual_targets':targets,'crop_keyframes':[{'t':0,'center':.5}],'camera_cuts':[1,2,3,4,5]}
    first=make_review(video,edit,tracking,tmp_path);hashes={p:pixel_hash(p) for p in first['pages']}
    revised=copy.deepcopy(edit);revised['duration']-=1/30;revised['segments'][0]['source_start']=1/30;revised['segments'][0]['output_end']-=1/30
    t=copy.deepcopy(tracking);t['visual_targets'][0]['start']=1/30;t['visual_targets'][0]['box_keyframes'][0]['t']=1/30
    second=make_review(video,revised,t,tmp_path)
    unchanged=[p for p in second['pages'] if hashes.get(p)==pixel_hash(p)]
    assert len(second['pages'])==3 and len(unchanged)>=2
