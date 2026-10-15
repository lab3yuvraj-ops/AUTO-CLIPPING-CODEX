import pytest
from reel_engine.final_review import review_route,sample_final


def records():
    return (dict(fast=True,crop_strategy='fixed',passage_classification=dict(classification='single/dominant-presenter',requires_stable_context=False)),
        dict(tracking=dict(stable_framing=True,stable_framing_evidence='Source-reviewed stable presenter centred throughout passage',confirmed=True,unresolved=False)))


def test_stable_dominant_no_longer_bypasses_baseline():
    job,spec=records();assert review_route(job,spec)=='pre-render-combined-review'
    spec['tracking']['stable_framing']=False
    assert review_route(job,spec)=='pre-render-combined-review'


def test_dialogue_uncertain_and_nonfast_require_pre_review():
    job,spec=records();job['passage_classification']['classification']='multi-speaker dialogue'
    assert review_route(job,spec)=='pre-render-combined-review'


def test_stable_presenter_review_no_longer_defers_without_checks(tmp_path,monkeypatch):
    import json,reel
    from reel_engine import preflight
    root=tmp_path/'jobs'/'presenter_test';root.mkdir(parents=True)
    job,spec=records();job.update(id='presenter_test',run_id='test_final_review',timing_job='presenter_test',source='source')
    (root/'job.json').write_text(json.dumps(job));edit=root/'spec.json';edit.write_text(json.dumps(spec))
    monkeypatch.setattr(reel,'STATE',tmp_path)
    def checks(*a,**kw):raise ValueError('Checks precede baseline review')
    monkeypatch.setattr(preflight,'snap_spec',checks)
    with pytest.raises(ValueError,match='Checks precede'):reel.review('presenter_test',edit)


def test_final_sampling_includes_real_cut_frames_and_cache(tmp_path):
    from reel_engine.render import run
    video=tmp_path/'video.mp4'
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=30:duration=8','-c:v','libx264',str(video)])
    edit=dict(duration=4,segments=[dict(source_start=10,source_end=14,output_start=0,output_end=4)])
    tracking=dict(camera_cuts=[12])
    first=sample_final(video,edit,tracking,tmp_path)
    assert 0. in first['sample_seconds'] and 7.9 in first['sample_seconds']
    assert 3.5 not in first['sample_seconds']
    assert any(abs(t-1.95)<.04 for t in first['sample_seconds'])
    assert first['pages'] and sample_final(video,edit,tracking,tmp_path)['cache_reused']
    tracking['camera_cuts']=[11]
    assert not sample_final(video,edit,tracking,tmp_path)['cache_reused']
