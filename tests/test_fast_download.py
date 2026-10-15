import json
from pathlib import Path

import numpy as np
import pytest

from reel_engine import fast_download as fd
from reel_engine.errors import StageError


def test_passage_bounds_are_tight_and_clamped():
    assert fd.section_range(2, 35, 40) == [0., 38.]
    assert fd.section_range(30, 60, 61) == [27., 61.]
    for args in [(0, 3, 2), (-1, 3, 4), (3, 3, 5), (0, 2, float('nan'))]:
        with pytest.raises(ValueError):
            fd.section_range(*args)


def info():
    return {'id': 'abcdefghijk', 'duration': 100, 'availability': 'public',
            'formats': [{'vcodec': 'av1', 'height': 2160}, {'vcodec': 'none'}]}


def fake_transfer(monkeypatch, height, duration):
    calls = []
    def transfer(args, **kwargs):
        calls.append((args, kwargs))
        (kwargs['progress_root']/'source.mkv').write_bytes(b'complete')
    monkeypatch.setattr(fd, 'ytdlp', transfer)
    monkeypatch.setattr(fd, 'probe', lambda p: {'streams': [{'codec_type':'video','height':height}, {'codec_type':'audio'}], 'format': {'duration':str(duration)}})
    return calls


def test_proxy_is_never_final_source_and_metadata_stays_in_memory(monkeypatch, tmp_path):
    calls = fake_transfer(monkeypatch, 480, 100)
    record = fd.download_proxy(info(), tmp_path)
    assert not record['render_eligible'] and record['kind'] == 'proxy'
    assert 'height<=480' in calls[0][0][calls[0][0].index('-f')+1]
    assert calls[0][1]['info'] == info()
    assert 'formats' not in (tmp_path/'accepted.json').read_text()
    assert fd.download_proxy(info(), tmp_path)['cached']
    assert len(calls) == 1


def test_section_uses_highest_quality_and_unverified_offset(monkeypatch, tmp_path):
    calls = fake_transfer(monkeypatch, 2160, 36)
    record = fd.download_section(info(), tmp_path, 20, 50, 100)
    assert record['padded_range'] == [17., 53.]
    assert record['source_offset'] == 17 and not record['offset_verified']
    args = calls[0][0]
    assert args[args.index('-f')+1] == 'bv*+ba/b'
    assert args[args.index('--download-sections')+1] == '*17.000000-53.000000'


def test_section_quality_downgrade_refused(monkeypatch, tmp_path):
    fake_transfer(monkeypatch, 1080, 36)
    with pytest.raises(StageError, match='highest advertised quality'):
        fd.download_section(info(), tmp_path, 20, 50, 100)
    assert not (tmp_path/'accepted.json').exists()


def test_partial_never_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(fd, 'ytdlp', lambda *args, **kwargs: (tmp_path/'source.mp4.part').write_bytes(b'partial'))
    with pytest.raises(StageError, match='complete section'):
        fd.download_proxy(info(), tmp_path)
    assert not (tmp_path/'accepted.json').exists()


def test_different_range_does_not_resume_existing_partial(monkeypatch, tmp_path):
    first = {'version': 1, 'kind': 'section', 'video_id': info()['id'],
             'requested_range': [20., 50.], 'padded_range': [17., 53.], 'highest_height': 2160}
    fd._bind_request(tmp_path, first)
    (tmp_path/'source.mp4.part').write_bytes(b'keep')
    with pytest.raises(StageError, match='different source/range'):
        fd.download_section(info(), tmp_path, 30, 60, 100)
    assert (tmp_path/'source.mp4.part').read_bytes() == b'keep'


def test_audio_match_finds_subsample_bounded_offset():
    rng = np.random.default_rng(4)
    search = rng.normal(0, .1, 24000)
    reference = search[5432:13432]*.8
    result = fd._match_audio(reference, search)
    assert result['accepted']
    assert result['position_seconds'] == 5432/8000
    assert not fd._match_audio(np.zeros(8000), search)['accepted']
    repeated = np.tile(reference, 4)
    assert not fd._match_audio(reference, repeated)['accepted']


def setup_anchor_audio(monkeypatch, shift=0., drift=0.):
    rate = 8000
    source = np.random.default_rng(73).normal(0, .1, 80*rate)
    section_start = 10+shift
    # Different start/end shifts model clock drift rather than one seek shift.
    def audio(path, start, duration, sample_rate=8000):
        real_start = start if Path(path).name == 'proxy.mkv' else start+section_start+(drift if start>20 else 0)
        idx = round(real_start*rate)
        return source[idx:idx+round(duration*rate)]
    monkeypatch.setattr(fd, '_audio', audio)


def test_two_audio_word_anchors_confirm_direct_mapping(monkeypatch, tmp_path):
    setup_anchor_audio(monkeypatch)
    words = [{'id':'a','start':14.,'end':14.4}, {'id':'b','start':45.,'end':45.5}]
    report = fd.confirm_section_audio('proxy.mkv', tmp_path/'section.mkv', [10, 50], words)
    assert report['offset_verified'] and not report['verify_section_required']
    assert abs(report['source_offset']-10)<.001
    assert len(report['anchors']) == 2


@pytest.mark.parametrize('shift,drift', [(0.3, 0), (0, .2)])
def test_shifted_or_drifting_section_requires_local_verification(monkeypatch, tmp_path, shift, drift):
    setup_anchor_audio(monkeypatch, shift, drift)
    words = [{'id':'a','start':14.,'end':14.4}, {'id':'b','start':45.,'end':45.5}]
    report = fd.confirm_section_audio('proxy.mkv', tmp_path/'section.mkv', [10, 50], words)
    assert not report['offset_verified'] and report['verify_section_required']
    assert 'source_offset' not in report
    assert report['reason'] == 'section_seek_offset_or_audio_drift_exceeds_tolerance'
    saved = json.loads((tmp_path/'audio-offset-check.json').read_text())
    assert saved['verify_section_required']
