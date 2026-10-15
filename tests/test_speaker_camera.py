import numpy as np
import pytest
from reel_engine.speaker_camera import build_speaker_camera
from reel_engine.tracking import crop_centers
from reel_engine.camera import ease_camera


def scenes():
    return [{'id':'room','start':0.,'end':6.,'stable_center':.5,'evidence':'Chronological source frames show one continuous room shot.'}]


def association(speaker,center,scene='room',start=0,end=6,confidence=.95):
    return {'scene':scene,'speaker':speaker,'confidence':confidence,
            'visual_evidence':'Reviewed identity stays at these source-specific center anchors.',
            'speech_mouth_evidence':'Selected audible turn and visible mouth movement coincide at reviewed frames.',
            'center_keyframes':[{'t':start,'center':center},{'t':end,'center':center}]}


def centers(plan,times):return crop_centers(plan,[],times)


def test_three_reviewed_speakers_switch_full_height_with_scene_bounded_easing():
    turns=[{'start':0,'end':2,'speaker':'A'},{'start':2,'end':4,'speaker':'B'},{'start':4,'end':6,'speaker':'C'}]
    plan=build_speaker_camera(turns,scenes(),[association('A',.25),association('B',.5),association('C',.75)])
    assert [s['to'] for s in plan['speaker_switches']]==['A','B','C']
    assert centers(plan,[1,3,5])==[.25,.5,.75]
    assert not plan['editorial_warnings'] and not plan['unresolved']
    times=[i/30 for i in range(180)];raw=[[c,.5,1.] for c in centers(plan,times)]
    path=np.array(ease_camera(raw,times,plan['camera_cuts'],30,plan['camera_easing_seconds']))
    assert np.allclose(path[:,1],.5) and np.allclose(path[:,2],1)
    assert np.max(np.abs(np.diff(path[:,0])))<.025
    assert path[59,0]<path[60,0]<path[61,0]


def test_brief_interjection_ignored_and_minimum_hold_debounces_longer_turn():
    turns=[{'start':0,'end':3,'speaker':'A'},{'start':.5,'end':.75,'speaker':'B'},
           {'start':3,'end':3.5,'speaker':'B'},{'start':3.5,'end':6,'speaker':'A'}]
    plan=build_speaker_camera(turns,scenes(),[association('A',.25),association('B',.75)])
    assert len(plan['ignored_interjections'])==1
    assert centers(plan,[.6,3.1,3.6,4.1,4.3])==[.25,.75,.75,.75,.25]
    assert not any(s['t']==pytest.approx(.5) for s in plan['speaker_switches'])
    assert plan['speaker_switches'][-1]['t']==pytest.approx(4.2)


def test_low_confidence_unknown_and_overlap_hold_with_warnings():
    turns=[{'start':0,'end':1.5,'speaker':'A'}, {'start':1.5,'end':3,'speaker':'B'},
           {'start':3,'end':4,'speaker':'UNKNOWN'},{'start':4,'end':6,'speaker':'A'},
           {'start':4.5,'end':5,'speaker':'C'}]
    plan=build_speaker_camera(turns,scenes(),[association('A',.25),association('B',.75,confidence=.79),association('C',.6)])
    assert centers(plan,[1,2,3.5,4.8])==[.25]*4
    assert {w['reason'] for w in plan['editorial_warnings']}=={'low_visual_identity_confidence','uncertain_audio_speaker','overlapping_speakers'}
    assert plan['unresolved'] and all(w['requires_editorial_review'] for w in plan['editorial_warnings'])


def test_actual_cut_resets_identity_and_never_eases_across_scenes():
    shots=[{'id':'first','start':0,'end':3,'stable_center':.5,'evidence':'Actual source cut at3.'},
           {'id':'next','start':3,'end':6,'stable_center':.6,'evidence':'New angle after actual cut.'}]
    turns=[{'start':0,'end':6,'speaker':'A'}]
    plan=build_speaker_camera(turns,shots,[association('A',.25,'first',0,3),association('A',.75,'next',3,6)])
    assert plan['camera_cuts']==[3]
    times=[i/30 for i in range(180)];path=np.array(ease_camera([[c,.5,1] for c in centers(plan,times)],times,plan['camera_cuts'],30,1.2))
    assert path[89,0]==pytest.approx(.25) and path[90,0]==pytest.approx(.75)
    uncertain=build_speaker_camera(turns,shots,[association('A',.25,'first',0,3)])
    assert centers(uncertain,[2,3,4])==[.25,.6,.6]
    assert uncertain['editorial_warnings'][0]['reason']=='missing_scene_bound_visual_identity'


def test_moving_identity_anchors_and_initial_uncertainty_use_reviewed_centers():
    item=association('A',.25);item['center_keyframes']=[{'t':0,'center':.25},{'t':6,'center':.75}]
    plan=build_speaker_camera([{'start':0,'end':6,'speaker':'A'}],scenes(),[item])
    assert centers(plan,[0,3,5])==pytest.approx([.25,.5,.25+5/6*.5])
    uncertain=build_speaker_camera([{'start':0,'end':6,'speaker':'A','speaker_uncertain':True}],scenes(),[item])
    assert centers(uncertain,[0,3,5])==[.5]*3


def test_voice_label_alone_cannot_establish_left_or_right_and_invalid_bounds_fail():
    item=association('A',.25);item.pop('speech_mouth_evidence')
    with pytest.raises(ValueError,match='Voice labels alone'):build_speaker_camera([],scenes(),[item])
    with pytest.raises(ValueError,match='Duplicate'):build_speaker_camera([],scenes(),[association('A',.25),association('A',.75)])
    with pytest.raises(ValueError,match='minimum hold'):build_speaker_camera([],scenes(),[],min_hold_seconds=.5)
    with pytest.raises(ValueError,match='confidence threshold'):build_speaker_camera([],scenes(),[],confidence_threshold=.5)
    invalid=scenes();invalid[0]['stable_center']=float('nan')
    with pytest.raises(ValueError,match='stable center'):build_speaker_camera([],invalid,[])
