from pathlib import Path
from PIL import Image
import pytest
from reel_engine.adaptive_sampling import representative_frames


def frames(tmp_path,moving=False):
    result=[]
    for i in range(61):
        p=tmp_path/f'{i}.jpg';Image.new('RGB',(96,54),(i%2*255 if moving else 90,)*3).save(p)
        result.append({'source_seconds':i*.5,'file':str(p),'scene_score':.4 if i==23 else 0,'sha256':str(i)})
    return result


def test_static_sampling_reduces_duplicates_keeps_edges_cuts_context(tmp_path):
    source=frames(tmp_path);selected,report=representative_frames(source,'smart',[7.5,21])
    times={f['source_seconds'] for f in selected}
    assert {0,30,11,11.5,12,7.5,21}<=times
    assert len(selected)<len(source)/2
    assert report['identity_established'] is False


def test_motion_increases_sampling_no_hard_budget_drops_witnesses(tmp_path):
    selected,report=representative_frames(frames(tmp_path,True),'smart')
    assert len(selected)==61 and report['soft_budget_exceeded']
    fast,_=representative_frames(frames(tmp_path,True),'fast')
    assert len(fast)<len(selected)


def test_invalid_profile_and_reversed_timeline_rejected(tmp_path):
    f=frames(tmp_path)
    with pytest.raises(ValueError):representative_frames(f,'turbo')
    with pytest.raises(ValueError):representative_frames(f[::-1])
