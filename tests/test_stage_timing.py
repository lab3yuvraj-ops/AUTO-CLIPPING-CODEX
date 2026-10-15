import concurrent.futures
import json
import pytest
from reel_engine import timing


def interval(state,name,a,b,**kwargs):
    timing.mark(state,'job_test',name,'start',at=a,run_id='run_a',**kwargs)
    timing.mark(state,'job_test',name,'end',at=b,run_id='run_a',outcome='success',**kwargs)


def test_mark_validation_and_open_stage(tmp_path):
    for args in [('bad/name','stage','start'),('job_test','bad stage','start'),('job_test','stage','other')]:
        with pytest.raises(ValueError):timing.mark(tmp_path,*args)
    for at in (float('nan'),float('inf'),'123'):
        with pytest.raises(ValueError):timing.mark(tmp_path,'job_test','stage','start',at=at)
    with pytest.raises(ValueError):timing.mark(tmp_path,'job_test','stage','end',at=1)
    timing.mark(tmp_path,'job_test','stage','start',at=10,run_id='run_a')
    with pytest.raises(ValueError):timing.mark(tmp_path,'job_test','stage','start',at=11,run_id='run_a')
    with pytest.raises(ValueError):timing.mark(tmp_path,'job_test','stage','end',at=9,run_id='run_a')
    data=timing.report(tmp_path,'job_test');assert data['open_stages']==['stage']
    assert 'INCOMPLETE' in timing.table(data)


def test_overlapping_stages_union_not_double_counted(tmp_path):
    interval(tmp_path,'word_verification',10,20)
    interval(tmp_path,'section_download',15,25)
    report=timing.report(tmp_path,'job_test')
    assert report['wall_seconds']==15
    assert report['summed_stage_seconds']==20
    assert report['covered_wall_seconds']==15
    assert report['untracked_wall_seconds']==0
    assert report['overlaps']==[{'first':'word_verification','second':'section_download','seconds':5}]


def test_repeat_cached_failed_and_run_isolation(tmp_path,monkeypatch):
    interval(tmp_path,'download',0,5,cached=True)
    interval(tmp_path,'download',15,20)
    report=timing.report(tmp_path,'job_test','run_a')
    assert len(report['intervals'])==2 and report['intervals'][0]['cached']
    assert report['untracked_wall_seconds']==10
    clock=iter([30.,34.]);monkeypatch.setattr(timing.time,'time',lambda:next(clock))
    with pytest.raises(RuntimeError):
        with timing.stage(tmp_path,'job_test','render',run_id='run_b'):
            raise RuntimeError('failure')
    latest=timing.report(tmp_path,'job_test')
    assert latest['run_id']=='run_b' and latest['wall_seconds']==4
    assert latest['intervals'][0]['outcome']=='failed'
    assert not latest['open_stages']
    assert timing.report(tmp_path,'job_test','run_a')['wall_seconds']==20


def test_thread_log_rows_are_atomic_and_jobs_isolated(tmp_path):
    def work(i):
        with timing.stage(tmp_path,f'job_{i}',f'work_{i}',run_id='run_a',cached=i%2==0):pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(work,range(24)))
    rows=[json.loads(line) for line in (tmp_path/'stage-timings.jsonl').read_text().splitlines()]
    assert len(rows)==48
    for i in range(24):
        report=timing.report(tmp_path,f'job_{i}')
        assert len(report['intervals'])==1 and report['intervals'][0]['stage']==f'work_{i}'
        assert report['intervals'][0]['cached']==(i%2==0)
        assert not report['open_stages']


def test_phase_cli_accounts_current_gap_on_source_owner(monkeypatch,tmp_path):
    import reel,sys
    owner='source_job_123';clip='source_job_123_clip1';root=tmp_path/'jobs'/clip;root.mkdir(parents=True)
    (root/'job.json').write_text(json.dumps({'timing_job':owner,'run_id':'run_a'}))
    timing.mark(tmp_path,owner,'download','start',at=0,run_id='run_a')
    timing.mark(tmp_path,owner,'download','end',at=1,run_id='run_a')
    clock=iter([10.,10.1,10.2])
    monkeypatch.setattr(reel,'STATE',tmp_path);monkeypatch.setattr(timing.time,'time',lambda:next(clock))
    monkeypatch.setattr(sys,'argv',['reel.py','phase',clip,'review_pass','--event','start'])
    reel.main()
    r=timing.report(tmp_path,owner,'run_a')
    assert any(i['stage']=='between_commands' and i['start']==1 and i['end']==10 for i in r['intervals'])
    assert any(i['stage']=='cli_phase' for i in r['intervals'])
    assert r['untracked_wall_seconds']==0
    # No historical review was invented: actual review still starts at10.
    rows=[json.loads(x) for x in (root/'interactive-phases.jsonl').read_text().splitlines()]
    assert rows[0]['at']==10.1 and rows[0]['job']==owner
