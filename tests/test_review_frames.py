import json
import subprocess
from pathlib import Path

from PIL import Image

from reel_engine.review import review_frames


def test_exact_sequential_frames_cache_and_large_sample_list(tmp_path):
    # 120 requests exercise FFmpeg expression recursion and cache corruption.
    source=tmp_path/'input.mkv'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
        'testsrc2=size=160x90:rate=30:duration=4','-c:v','ffv1',str(source)],check=True)
    out=tmp_path/'review';out.mkdir()
    indices=list(range(120))
    files=review_frames(source,indices,out)
    assert len(files)==120
    with Image.open(files[0]) as image:assert image.width==960
    with Image.open(files[119]) as image:assert image.width==960
    original=files[50].read_bytes()
    assert review_frames(source,indices,out)==files
    files[50].write_bytes(b'corrupted')
    review_frames(source,indices,out)
    assert files[50].read_bytes()==original
    # Exact index ordering, not a regular-time approximation.
    sparse=review_frames(source,[0,50,119],out)
    assert sparse[1].read_bytes()==original
