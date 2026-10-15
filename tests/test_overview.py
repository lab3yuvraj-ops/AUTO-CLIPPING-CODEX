import json
from types import SimpleNamespace
from PIL import Image
from reel_engine import overview


def test_overview_actual_timestamps_cache_and_sparse_keyframe_fallback(monkeypatch,tmp_path):
    source=tmp_path/'source';source.write_bytes(b'source')
    monkeypatch.setattr(overview,'probe',lambda _: {'format':{'duration':'30'}})
    calls=[]
    def decode(args,**kwargs):
        calls.append(args)
        stamps=[0] if '-skip_frame' in args else [0,12.4,24.8]
        pattern=args[-1]
        for i,t in enumerate(stamps,1):Image.new('RGB',(640,360),'red').save(pattern % i)
        return SimpleNamespace(returncode=0,stderr='\n'.join(f'[showinfo] n: {i} pts: 0 pts_time:{t}' for i,t in enumerate(stamps)))
    monkeypatch.setattr(overview.subprocess,'run',decode)
    first=overview.make_overview(source,tmp_path)
    assert first['decode_mode']=='all_frames'
    assert [r['source_seconds'] for r in first['frames']]==[0,12.4,24.8]
    assert len(calls)==2
    assert overview.make_overview(source,tmp_path)['cache_reused']
    assert len(calls)==2
    # Corrupted cached images must not be silently accepted.
    from pathlib import Path
    Path(first['frames'][0]['file']).write_bytes(b'corrupt')
    assert not overview.make_overview(source,tmp_path)['cache_reused']
    assert len(calls)==4
    source.write_bytes(b'different-source')
    assert overview.make_overview(source,tmp_path)['source_sha256']!=first['source_sha256']
