import copy
import pytest
from reel_engine.editing_plan import compile_plan,save_plan,grounded_scene_proposal
from reel_engine.scene_table import SceneTable,build_spec


def recipe():
    base={'candidate':{'start':10.,'end':45.},'words':[{'id':1,'start':11.,'end':11.5,'roman':'Hello'}],
          'tracking':{'confirmed':True,'unresolved':False}}
    row={'id':'river-shadow','start':10.,'end':45.,'center':.6,'kind':'object','confidence':.9,
         'evidence':'Shadow seen on river in reviewed frame, not inferred from keywords',
         'subject_boxes':[{'t':10.,'box':[.5,.3,.2,.4],'visible_subject_box':[.5,.3,.2,.4],
                           'bounds_evidence':'Complete river shadow region in actual source frame'}]}
    return base,row,build_spec(base,SceneTable.model_validate({'scenes':[row]}))


def test_plan_keeps_existing_style_and_hash_invalidation(tmp_path):
    base,row,spec=recipe();job={'source_sha256':'abc'}
    a=save_plan(tmp_path,job,spec);assert not a['cache_reused']
    assert save_plan(tmp_path,job,spec)['cache_reused']
    assert a['caption']['position']==[500,1420] and a['output']['crf']==18
    assert not a['inspection_approved'] and not a['publication_approved']
    moved=copy.deepcopy(spec);moved['tracking']['visual_targets'][0]['camera_center_keyframes'][0]['center']=.65
    assert save_plan(tmp_path,job,moved)['plan_hash']!=a['plan_hash']
    caption=copy.deepcopy(spec);caption['words'][0]['roman']='Hi'
    assert save_plan(tmp_path,job,caption)['plan_hash']!=a['plan_hash']


@pytest.mark.parametrize('change',[lambda s:s['tracking']['visual_targets'][0].update(layout='full_frame_background'),
                                  lambda s:s['tracking']['visual_targets'][0].update(start=10.5),
                                  lambda s:s['words'][0].update(end=46),
                                  lambda s:s['tracking'].update(camera_cuts=[12,11]),
                                  lambda s:s['tracking']['visual_targets'][0].update(full_subject_bounds_confirmed=False)])
def test_invalid_plan_never_reaches_render(change):
    _,_,spec=recipe();change(spec)
    with pytest.raises(ValueError):compile_plan({'source_sha256':'abc'},spec)


def test_semantic_subject_requires_real_frame_and_stays_unapproved():
    base,row,_=recipe();details={'source_sha256':'abc','frames':[{'sha256':'frame','source_seconds':10.}]}
    proposal={'source_sha256':'abc','model_version':'local-test-v1','scenes':[dict(row,evidence_frames=['frame'])]}
    s=grounded_scene_proposal(base,proposal,details)
    assert s['tracking']['unresolved'] and not s['tracking']['confirmed']
    proposal['scenes'][0]['evidence_frames']=['invented']
    with pytest.raises(ValueError,match='frame evidence'):grounded_scene_proposal(base,proposal,details)


def test_unknown_subject_does_not_invent_coordinates():
    base,_,_=recipe()
    with pytest.raises(ValueError,match='No grounded'):grounded_scene_proposal(base,{'source_sha256':'abc','model_version':'v1','scenes':[]},{'source_sha256':'abc','frames':[]})
