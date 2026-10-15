import json
import shutil
import pytest
import subprocess
import numpy as np
from reel_engine.render import run, probe
from reel_engine.fast_render import fast_render_clip


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
@pytest.mark.parametrize('gapped', [False, True])
def test_late_fractional_seek_preserves_decoded_video_audio_events_and_camera(tmp_path,gapped):
    source=tmp_path/'source.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=16',
         '-f','lavfi','-i','sine=frequency=587:sample_rate=48000:duration=16',
         '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)])
    segments=([{'source_start':12.34,'source_end':13.34,'output_start':0.,'output_end':1.},
               {'source_start':14.34,'source_end':15.34,'output_start':1.,'output_end':2.}]
              if gapped else [{'source_start':12.34,'source_end':14.34,'output_start':0.,'output_end':2.}])
    edit={'duration':2.,'segments':segments,'words':[{'id':1,'roman':'Test','start':.2,'end':.5,'source_start':12.54,'source_end':12.84}]}
    tracking={'camera_easing_seconds':1.2,'camera_smoothing':True,'crop_policy':'full_source_height_horizontal_only',
              'crop_keyframes':[{'t':12.34,'center':.4},{'t':13.1,'center':.6}], 'camera_cuts':[]}
    infos=[]
    for name,seek in [('before',False),('after',True)]:
        out=tmp_path/name/'story.mp4';infos.append(fast_render_clip(source,edit,tracking,out,{'input_seek':seek},threads=2))
    assert infos[1]['input_seek_seconds']==11
    assert infos[0]['caption_events']==infos[1]['caption_events']
    assert json.loads((tmp_path/'before/camera-path.json').read_text())==json.loads((tmp_path/'after/camera-path.json').read_text())
    def hashes(name,stream):
        cmd=['ffmpeg','-v','error','-i',str(tmp_path/name/'story.mp4'),'-map',f'0:{stream}:0']
        if stream=='v':cmd+=['-pix_fmt','yuv420p']
        else:cmd+=['-c:a','pcm_s16le']
        return [r.split(',')[-1].strip() for r in run(cmd+['-f','framemd5','-']).stdout.splitlines() if r and not r.startswith('#')]
    assert hashes('before','v')==hashes('after','v')
    # Input timestamp rebasing can change AAC floating point rounding. Require
    # identical sample count and sub-LSB error, not a false bit-exact AAC claim.
    audio=[np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(tmp_path/n/'story.mp4'),
            '-vn','-f','f32le','-']),dtype=np.float32).astype(float) for n in ('before','after')]
    assert audio[0].shape==audio[1].shape
    error=audio[0]-audio[1]
    assert np.max(np.abs(error))<2/32768
    assert np.mean(error**2)<np.mean(audio[0]**2)*1e-9
