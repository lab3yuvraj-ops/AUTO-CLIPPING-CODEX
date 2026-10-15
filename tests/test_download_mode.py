import pytest
from reel_engine.download_policy import choose_download


def test_transcript_first_defers_ordinary_full_quality_until_selection():
    info={'duration':900,'formats':[{'vcodec':'h264','height':1080,'filesize':10000000}]}
    assert choose_download(info,1500000000,2160)['strategy']=='eager-full'
    p=choose_download(info,1500000000,2160,'selected-sections')
    assert p['strategy']=='selected-sections' and p['height']==1080
    assert 'explicit' in p['reason']
    with pytest.raises(ValueError):choose_download(info,1500000000,2160,'low-quality')
