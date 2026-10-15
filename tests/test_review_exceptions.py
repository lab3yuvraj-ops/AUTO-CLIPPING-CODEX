import copy,json
import pytest
from reel_engine.preflight import snap_boundaries,boundary_flashes,margin_violation,crop_safety
from reel_engine.review_policy import record_inspection,inspection_plan,register_round
from reel_engine.scene_table import SceneTable,build_spec

def test_boundary_snap_intact_words_and_ambiguous_cut():
    candidate={'start':10.,'end':50.}
    words=[{'start':10.3,'end':10.6},{'start':49.4,'end':49.6}]
    plan,snaps,flags=snap_boundaries(candidate,words,[{'time':10.1,'score':.8},{'time':49.9,'score':.8}])
    assert plan['start']>10.1 and plan['end']<49.9 and len(snaps)==2 and not flags
    plan,snaps,flags=snap_boundaries(candidate,words,[{'time':10.29,'score':.8}])
    assert not snaps and 'clip first/last' in flags[0]['reason']
    assert snap_boundaries(candidate,words,[{'time':10.1,'score':.2}])[2]

def test_opening_and_ending_flash_detection():
    cuts=[{'time':10.07,'score':.8},{'time':49.97,'score':.7},{'time':20.,'score':.6}]
    assert len(boundary_flashes(10,50,cuts))==2
    assert not boundary_flashes(10.1,49.9,cuts)

def test_margin_catches_original_three_pan_offsets():
    # Independent reviewed subject extent; checking crop-derived box cannot
    # discover an incorrectly located target. Subject width .23 at 1920x1080.
    for actual,original in [(.61,.46),(.51,.47),(.65,.54)]:
        box=[actual-.115,.05,.23,.90]
        assert margin_violation(box,[original,.5,1],1920,1080,.04)
        assert not margin_violation(box,[actual,.5,1],1920,1080,.04)
    assert margin_violation([.39,.05,.22,.9],[.1,.5,1],1920,1080)

def test_pixel_hash_carry_requires_inspection_and_flags_force_review(tmp_path):
    from PIL import Image
    a=tmp_path/'a.jpg';b=tmp_path/'b.jpg';Image.new('RGB',(20,20),'red').save(a);b.write_bytes(a.read_bytes())
    assert inspection_plan(tmp_path,'final_frames',[a,b])['required_pages']
    record_inspection(tmp_path,'final_frames',[a])
    assert not inspection_plan(tmp_path,'final_frames',[b])['required_pages']
    assert inspection_plan(tmp_path,'final_frames',[b],[b])['required_pages']
    Image.new('RGB',(20,20),'blue').save(b)
    assert inspection_plan(tmp_path,'final_frames',[b])['required_pages']

def test_two_correction_round_cap(tmp_path):
    for n in (0,1,2):assert register_round(tmp_path,{'version':n})['correction_round']==n
    assert register_round(tmp_path,{'version':2})['correction_round']==2
    with pytest.raises(ValueError,match='Two correction'):register_round(tmp_path,{'version':3})

def table():
    return {'scenes':[{'id':'speaker','start':0.,'end':40.,'center':.5,'evidence':'Reviewed source anchors','confidence':.9,'positions':[{'t':0.,'center':.5},{'t':20.,'center':.52}], 'subject_boxes':[{'t':t,'box':[.4,.1,.2,.8],'visible_subject_box':[.4,.1,.2,.8],'bounds_evidence':'Synthetic independently specified full subject'} for t in (0.,40.)]}]}

def test_scene_schema_fixed_by_default_and_pan_threshold():
    base={'candidate':{'start':0.,'end':40.},'words':[],'tracking':{}}
    result=build_spec(base,SceneTable.model_validate(table()))
    assert len(result['tracking']['visual_targets'][0]['camera_center_keyframes'])==1
    d=table();d['scenes'][0]['positions'][1]['center']=.65
    assert len(build_spec(base,SceneTable.model_validate(d))['tracking']['visual_targets'][0]['camera_center_keyframes'])==2
    automatic=table();automatic['scenes'][0]['positions']=[];automatic['scenes'][0]['subject_boxes'][1]['box'][0]=.55
    automatic['scenes'][0]['subject_boxes'][1]['visible_subject_box'][0]=.55
    assert len(build_spec(base,SceneTable.model_validate(automatic))['tracking']['visual_targets'][0]['camera_center_keyframes'])==2
    d['scenes'][0]['subject_boxes'][0]['box']=[.9,.1,.2,.8]
    with pytest.raises(ValueError):SceneTable.model_validate(d)

def test_real_source_boundary_detection(tmp_path):
    from reel_engine.render import run
    from reel_engine.preflight import detect_boundary_cuts
    video=tmp_path/'cut.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:size=640x360:rate=30:d=1','-f','lavfi','-i','color=blue:size=640x360:rate=30:d=1','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264',str(video)])
    cuts=detect_boundary_cuts(video,.9,1.8,tmp_path)
    assert any(abs(c['time']-1)<.04 for c in cuts)
    assert boundary_flashes(.9,1.8,cuts)

def test_final_boundary_only_and_pixel_carry(tmp_path):
    from reel_engine.render import run
    from reel_engine.final_review import sample_final
    video=tmp_path/'video.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=30:duration=8','-c:v','libx264',str(video)])
    edit={'duration':4.,'segments':[{'source_start':10.,'source_end':14.,'output_start':0.,'output_end':4.}],'words':[]}
    first=sample_final(video,edit,{'camera_cuts':[12.]},tmp_path)
    record_inspection(tmp_path,'final_frames',list(first['frame_pixel_hashes']))
    video2=tmp_path/'video2.mp4';video2.write_bytes(video.read_bytes())
    second=sample_final(video2,edit,{'camera_cuts':[12.]},tmp_path)
    assert second['carried_frames'] or not second['required_pages']
    damaged=next(iter(second['frame_pixel_hashes']))
    from PIL import Image
    Image.new('RGB',(20,20),'red').save(damaged)
    repaired=sample_final(video2,edit,{'camera_cuts':[12.]},tmp_path)
    assert not repaired['cache_reused']
    flagged=sample_final(video2,edit,{'camera_cuts':[12.],'flagged_output_seconds':[.1]},tmp_path)
    record_inspection(tmp_path,'final_frames',list(flagged['frame_pixel_hashes']))
    assert sample_final(video2,edit,{'camera_cuts':[12.],'flagged_output_seconds':[.1]},tmp_path)['required_pages']
    sample_final(video2,edit,{'camera_cuts':[12.]},tmp_path)
    trimmed=copy.deepcopy(edit);trimmed['segments'][0]['source_start']=10.1;trimmed['duration']=3.9
    third=sample_final(video2,trimmed,{'camera_cuts':[12.]},tmp_path)
    assert third['boundary_only'] and len(third['sample_seconds'])<=7
    assert not any(abs(t-1.95)<.03 for t in third['sample_seconds'])


def test_scene_csv_and_json_emit_same_spec(tmp_path):
    import csv
    from reel_engine.scene_table import load_table
    data=table();jp=tmp_path/'scenes.json';jp.write_text(json.dumps(data))
    cp=tmp_path/'scenes.csv';row=data['scenes'][0].copy()
    for k in ('positions','subject_boxes'):row[k]=json.dumps(row[k])
    with cp.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    assert load_table(jp).model_dump()==load_table(cp).model_dump()

def test_snap_logs_and_clamps_targets_without_modifying_words(tmp_path,monkeypatch):
    from reel_engine import preflight
    monkeypatch.setattr(preflight,'detect_boundary_cuts',lambda *a:[{'time':10.1,'score':.8}])
    spec={'candidate':{'start':10.,'end':50.,'preserve_pauses':[[10.,50.]]},'words':[{'id':1,'start':10.3,'end':10.6}],
        'tracking':{'camera_cuts':[10.1,30.],'visual_targets':[{'start':10.,'end':50.,'box':[.4,.1,.2,.8],'box_keyframes':[{'t':10.,'box':[.4,.1,.2,.8]},{'t':50.,'box':[.4,.1,.2,.8]}]}]}}
    revised=preflight.snap_spec('source',spec,tmp_path)
    assert revised['words']==spec['words'] and revised['candidate']['start']>10.1
    assert revised['tracking']['visual_targets'][0]['start']==revised['candidate']['start']
    assert json.loads((tmp_path/'boundary-snaps.json').read_text())[0]['edge']=='start'

def test_unsafe_preflight_stops_render_before_encoder(tmp_path,monkeypatch):
    import reel
    from reel_engine import preflight
    root=tmp_path/'jobs'/'clip_test_careful';root.mkdir(parents=True)
    spec={'candidate':{'start':0.,'end':40.},'words':[],'tracking':{}}
    (root/'spec.json').write_text(json.dumps(spec));(root/'job.json').write_text(json.dumps({'id':'clip_test_careful','source':'fake','source_sha256':'fake'}))
    monkeypatch.setattr(reel,'STATE',tmp_path);monkeypatch.setattr(reel,'prepare_edit',lambda *a:({},{}))
    monkeypatch.setattr(preflight,'preflight',lambda *a:{'passed':False})
    monkeypatch.setattr(reel,'render_clip',lambda *a:pytest.fail('Unsafe preflight must not encode'))
    with pytest.raises(ValueError,match='Pre-render'):reel._render('clip_test_careful',root/'spec.json')

def test_final_trim_normalizes_boundary_anchor_time_only():
    from reel_engine.final_review import interior_fingerprint
    edit={'segments':[{'source_start':0.,'source_end':40.}],'words':[{'id':1,'source_start':1.,'source_end':2.,'roman':'Hello'}]}
    tracking={'visual_targets':[{'start':0.,'end':40.,'box_keyframes':[{'t':0.,'box':[.4,.1,.2,.8]}]}]}
    new=copy.deepcopy(edit);new['segments'][0]['source_start']=.1;t=copy.deepcopy(tracking);t['visual_targets'][0]['start']=.1;t['visual_targets'][0]['box_keyframes'][0]['t']=.1
    assert interior_fingerprint(edit,tracking)==interior_fingerprint(new,t)
    t['visual_targets'][0]['box_keyframes'][0]['box'][0]=.5
    assert interior_fingerprint(edit,tracking)!=interior_fingerprint(new,t)


def test_review_sampling_survives_cta_sar_change(tmp_path):
    from reel_engine.render import run
    from reel_engine.review import review_frames
    from PIL import Image
    parts=[]
    for n,(color,sar) in enumerate([('red','0/1'),('blue','1/1')]):
        part=tmp_path/f'part-{n}.mp4';parts.append(part)
        run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:size=360x640:rate=30:d=1','-vf',f'setsar={sar}','-c:v','libx264',str(part)])
    listing=tmp_path/'concat.txt';listing.write_text('\n'.join(f"file '{p.as_posix()}'" for p in parts))
    video=tmp_path/'joined.mp4'
    run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(video)])
    frames=review_frames(video,[0,29,30,45,59],tmp_path)
    assert len(frames)==5
    for frame in frames[:2]:
        rgb=Image.open(frame).getpixel((100,100));assert rgb[0]>200 and rgb[2]<30
    for frame in frames[2:]:
        rgb=Image.open(frame).getpixel((100,100));assert rgb[2]>200 and rgb[0]<30
