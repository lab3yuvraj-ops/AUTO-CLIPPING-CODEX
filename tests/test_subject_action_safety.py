import json
from types import SimpleNamespace as NS
import pytest
from reel_engine.preflight import assess_subject_action,crop_safety
from reel_engine.scene_table import SceneTable,build_spec

def test_wide_gesture_passes_with_warning():
    result=assess_subject_action([.44,.1,.12,.3],[.2,.3,.6,.7],[.5,.5,1],1920,1080)
    assert result['subject_passed'] and result['action_status']=='wide action, accepted'
    assert result['action_overflow_pixels'] and result['action_excess_width_pixels']>0

def test_subject_outside_still_fails_with_optional_action():
    result=assess_subject_action([.75,.1,.12,.3],[.2,.3,.6,.7],[.5,.5,1],1920,1080)
    assert not result['subject_passed'] and result['subject_overflow_pixels']
    assert result['action_status']=='wide action, subject unsafe'

def scene_table():
    return {'scenes':[{'id':'speaker','start':0,'end':40,'center':.5,'evidence':'Reviewed face and hands independently','confidence':.9,
        'subject_boxes':[{'t':0,'box':[.44,.1,.12,.3],'visible_subject_box':[.44,.1,.12,.3],'bounds_evidence':'Full visible head'}],
        'action_boxes':[{'t':0,'box':[.2,.3,.6,.7],'bounds_evidence':'Full visible gesture'}]}]}

def test_subject_minimum_unchanged_and_wide_action_builds():
    base={'candidate':{'start':0,'end':40},'words':[],'tracking':{}}
    spec=build_spec(base,SceneTable.model_validate(scene_table()))
    target=spec['tracking']['visual_targets'][0]
    assert target['bound_type']=='subject' and target['box'][2]==.12
    assert target['action_box_keyframes'][0]['bound_type']=='action'
    data=scene_table();data['scenes'][0]['subject_boxes'][0]['box'][2]=.06
    with pytest.raises(ValueError,match='narrower'):build_spec(base,SceneTable.model_validate(data))

def test_crop_stage_allows_wide_action_but_not_subject_failure(tmp_path,monkeypatch):
    import cv2
    from reel_engine.render import run
    video=tmp_path/'source.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:size=640x360:rate=30:d=2','-c:v','libx264',str(video)])
    edit={'duration':2,'words':[],'segments':[{'source_start':0,'source_end':2,'output_start':0,'output_end':2}]}
    target={'start':0,'end':2,'kind':'character','confidence':.9,'reason':'speaker','evidence':'Reviewed','box':[.44,.1,.12,.3],
        'box_keyframes':[{'t':0,'box':[.44,.1,.12,.3]}],'safety_box_keyframes':[{'t':0,'box':[.44,.1,.12,.3]}],
        'camera_center_keyframes':[{'t':0,'center':.5}], 'action_box_keyframes':[{'t':0,'box':[.2,.3,.6,.7]}]}
    tracking={'visual_targets':[target],'crop_keyframes':[{'t':0,'center':.5}]}
    first=crop_safety(video,edit,tracking)
    assert first['passed'] and first['action_summary'][0]['status']=='wide action, accepted'
    target['safety_box_keyframes'][0]['box']=[.75,.1,.12,.3]
    second=crop_safety(video,edit,tracking)
    assert not second['passed'] and second['violations']

def test_fast_render_with_action_bounds_cannot_bypass_subject_failure(tmp_path,monkeypatch):
    import reel
    from reel_engine import preflight
    root=tmp_path/'jobs'/'fast_subject_test';root.mkdir(parents=True)
    (root/'job.json').write_text(json.dumps({'id':'fast_subject_test','fast':True,'source':'fake'}))
    spec=root/'spec.json';spec.write_text(json.dumps({'candidate':{'start':0,'end':40}}))
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel,'prepare_edit',lambda *a:({}, {'visual_targets':[{'action_box_keyframes':[{'t':0,'box':[.2,.3,.6,.7]}]}]}))
    monkeypatch.setattr(preflight,'preflight',lambda *a:{'passed':False,'crop_safety':{'passed':False,'violations':[{'scene':1}],'action_warnings':[]},'spec_sha256':'test'})
    monkeypatch.setattr(reel,'render_clip',lambda *a,**k:pytest.fail('Unsafe subject must not reach encoding'))
    with pytest.raises(ValueError,match='boundary/crop check failed'):reel._render('fast_subject_test',spec)
