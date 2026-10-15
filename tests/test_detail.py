from types import SimpleNamespace
from pathlib import Path
from PIL import Image
import pytest
from reel_engine import detail


def test_detail_offsets_cut_candidates_and_discarded_tail(monkeypatch,tmp_path):
    source=tmp_path/'source';source.write_bytes(b'source')
    monkeypatch.setattr(detail,'probe',lambda _: {'format':{'duration':'60'}})
    calls=[]
    def decode(args,**kwargs):
        calls.append(args)
        for i in range(1,3):Image.new('RGB',(640,360),'green').save(args[-1] % i)
        return SimpleNamespace(returncode=0,stderr='\n'.join([
            '[showinfo] n: 0 pts: 0 pts_time:0','lavfi.scene_score=0',
            '[showinfo] n: 1 pts: 0 pts_time:0.5','lavfi.scene_score=0.3',
            '[showinfo] n: 2 pts: 0 pts_time:1','lavfi.scene_score=0']))
    monkeypatch.setattr(detail.subprocess,'run',decode)
    first=detail.make_details(source,tmp_path,[(10,11)])['passages'][0]
    assert [f['source_seconds'] for f in first['frames']]==[10,10.5]
    assert first['candidate_scene_cuts']==[10.5]
    assert detail.make_details(source,tmp_path,[(10,11)])['passages'][0]['cache_reused']
    assert len(calls)==1
    Path(first['frames'][0]['file']).write_bytes(b'corrupt')
    assert not detail.make_details(source,tmp_path,[(10,11)])['passages'][0]['cache_reused']
    assert len(calls)==2
    with pytest.raises(ValueError):detail.make_details(source,tmp_path,[(59,61)])
