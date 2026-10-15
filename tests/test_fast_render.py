"""Real CPU FFmpeg regression for the optional direct render path."""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from reel_engine.fast_render import camera_plan, fast_render_clip, fast_review
from reel_engine.render import probe, render_clip, run
from reel_engine.outro import append_outro


@pytest.fixture
def source(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    path=tmp_path/'source.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30:duration=3',
         '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3',
         '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)])
    return path


def recipe():
    edit={'duration':2.,'segments':[{'source_start':.5,'source_end':2.5,'output_start':0.,'output_end':2.}],
          'words':[{'id':'w0','roman':'Hello','speaker':'SPEAKER_00','start':.2,'end':.7,'source_start':.7,'source_end':1.2},
                   {'id':'w1','roman':'there','speaker':'SPEAKER_00','start':.7,'end':1.2,'source_start':1.2,'source_end':1.7}]}
    tracking={'mode':'fill','camera_smoothing':True,'camera_easing_seconds':1.2,
              'crop_policy':'full_source_height_horizontal_only', 'unresolved':False,
              'crop_keyframes':[{'t':.5,'center':.3},{'t':1.5,'center':.7,'cut':True}],
              'camera_cuts':[1.5]}
    return edit,tracking


def test_camera_exact_geometry_and_scene_reset(source):
    edit,tracking=recipe();plan=camera_plan(source,edit,tracking)
    assert plan['count']==60
    assert plan['geometry'][29][0]==pytest.approx(.3)
    assert plan['geometry'][30][0]==pytest.approx(.7)
    assert all(g[1:]==[.5,1.] for g in plan['geometry'])
    assert plan['xs']==[int(np.clip(g[0]*640-round(360*9/16)/2,0,640-round(360*9/16))) for g in plan['geometry']]
    tracking['camera_cuts']=[]
    smooth=camera_plan(source,edit,tracking)
    assert smooth['geometry'][29][0]<smooth['geometry'][30][0]
    assert max(np.diff([g[0] for g in smooth['geometry']]))<.04


def test_real_render_encoding_caption_events_and_normal_parity(source,tmp_path):
    edit,tracking=recipe();fast=tmp_path/'fast'/'story.mp4';normal=tmp_path/'normal'/'story.mp4'
    fast.parent.mkdir();normal.parent.mkdir()
    info=fast_render_clip(source,edit,tracking,fast,{},threads=2)
    slow=render_clip(source,edit,tracking,normal,{})
    assert info['caption_events']==slow['caption_events']
    assert info['full_source_height'] and info['single_pass']
    assert not (fast.parent/'edited.mkv').exists()
    assert json.loads((fast.parent/'camera-path.json').read_text())==json.loads((normal.parent/'camera-path.json').read_text())
    metadata=probe(fast);v=next(s for s in metadata['streams'] if s['codec_type']=='video');a=next(s for s in metadata['streams'] if s['codec_type']=='audio')
    assert (v['width'],v['height'],v['codec_name'])==(1080,1920,'h264')
    assert v['avg_frame_rate']=='30/1'
    assert (a['codec_name'],a['sample_rate'],a['channels'])==('aac','48000',2)
    assert abs(float(v['duration'])-float(a['duration']))<=.1
    normal_metadata=probe(normal)
    nv=next(s for s in normal_metadata['streams'] if s['codec_type']=='video')
    na=next(s for s in normal_metadata['streams'] if s['codec_type']=='audio')
    assert (nv['width'],nv['height'],nv['codec_name'],nv['avg_frame_rate'])==(1080,1920,'h264','30/1')
    assert (na['codec_name'],na['sample_rate'],na['channels'])==('aac','48000',2)
    # Different Lanczos implementations are expected; protect crop identity,
    # source-frame selection and overall pixels rather than false exact parity.
    fc=cv2.VideoCapture(str(fast));nc=cv2.VideoCapture(str(normal));errors=[]
    for index in (0,15,29,30,45,59):
        fc.set(cv2.CAP_PROP_POS_FRAMES,index);nc.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,f=fc.read();ok2,n=nc.read();assert ok and ok2
        errors.append(float(np.mean(np.abs(f.astype(float)-n.astype(float)))))
    fc.release();nc.release()
    assert max(errors)<12,errors


def test_compact_review_hash_cache_and_revision(source,tmp_path):
    edit,tracking=recipe();first=fast_review(source,edit,tracking,tmp_path)
    assert len(first['pages'])==1 and first['changed_pages']==first['pages']
    assert fast_review(source,edit,tracking,tmp_path)['cache_reused']
    edit['words'][0]['roman']='Hi'
    revised=fast_review(source,edit,tracking,tmp_path)
    assert not revised['cache_reused'] and revised['changed_pages']
    tracking['crop_keyframes'][0]['center']=.5
    moved=fast_review(source,edit,tracking,tmp_path)
    assert not moved['cache_reused'] and moved['changed_pages']
    assert moved['samples'][0]['camera'][0]!=revised['samples'][0]['camera'][0]


def test_real_four_second_cta_preserves_story_video_packets(source,tmp_path):
    from reel_engine.render import file_hash
    edit,tracking=recipe();body=tmp_path/'story.mp4'
    fast_render_clip(source,edit,tracking,body,{},threads=2)
    cta=tmp_path/'cta.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:size=1080x1920:rate=30:duration=4',
         '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=4',
         '-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-shortest',str(cta)])
    result=append_outro(body,tmp_path/'final.mp4',{'path':str(cta),'duration':4.,'sha256':file_hash(cta)})
    assert result['audio_repetitions']==0 and abs(result['total_duration']-6)<.1
    assert all(c['status']=='pass' for c in result['checks'])
    def packets(path):
        data=json.loads(run(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_data_hash','sha256','-of','json',str(path)]).stdout)
        return [p['data_hash'] for p in data['packets']]
    original=packets(body)
    # Concat may insert SPS/PPS in the first key packet while preserving every
    # coded image. Non-key packets remain identical; verify decoded pixels too.
    assert packets(tmp_path/'final.mp4')[1:len(original)]==original[1:]
    def frame_hashes(path):
        output=run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-frames:v','60','-f','framemd5','-']).stdout
        return [line.split(',')[-1].strip() for line in output.splitlines() if line and not line.startswith('#')]
    assert frame_hashes(body)==frame_hashes(tmp_path/'final.mp4')


def test_rejects_unanchored_target_or_moving_captions(source,tmp_path):
    edit,tracking=recipe();tracking['visual_targets']=[{'start':.5,'end':2.5,'box':[.1,.1,.2,.4],
        'kind':'character','confidence':1.,'reason':'test','evidence':'source fixture'}]
    with pytest.raises(ValueError,match='identity anchors'):camera_plan(source,edit,tracking)
    edit['caption_positions']=[{'start':0,'end':1,'y':1000}]
    with pytest.raises(ValueError,match='locked'):fast_render_clip(source,edit,tracking,tmp_path/'bad.mp4',{})


def test_real_trim_concat_keeps_mapping_and_caption_guard_intervals(source,tmp_path):
    edit,tracking=recipe()
    edit['segments']=[{'source_start':0.,'source_end':1.,'output_start':0.,'output_end':1.},
                      {'source_start':2.,'source_end':3.,'output_start':1.,'output_end':2.}]
    edit['words'][0].update(source_start=.2,source_end=.7)
    edit['words'][1].update(start=1.2,end=1.7,source_start=2.2,source_end=2.7)
    tracking['crop_keyframes']=[{'t':0.,'center':.3},{'t':2.,'center':.7,'cut':True}]
    tracking['camera_cuts']=[]
    plan=camera_plan(source,edit,tracking)
    assert plan['times'][29]==pytest.approx(29/30)
    assert plan['times'][30]==2.
    assert plan['geometry'][29][0]==pytest.approx(.3)
    assert plan['geometry'][30][0]==pytest.approx(.7)
    output=tmp_path/'trim-concat.mp4'
    result=fast_render_clip(source,edit,tracking,output,{},threads=2)
    assert result['render_frames']==60 and abs(float(probe(output)['format']['duration'])-2)<.05
    assert all(0<=e['start']<e['end']<=2 for e in result['caption_events'])
