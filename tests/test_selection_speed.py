import copy
import json
from pathlib import Path
import pytest
from reel_engine import selection_draft, download_policy, motion_check, timing
from reel_engine.config import settings


def test_native_auto_avoids_translated_tracks():
    assert selection_draft.native_auto_language({'language':'en-US','automatic_captions':{'en-orig':[],'hi':[]}})=='en-orig'
    assert selection_draft.native_auto_language({'language':'en','automatic_captions':{'en':[{'url':'https://example/?tlang=en'}]}}) is None


def test_auto_is_selection_only_hash_cached_and_fresh_bypasses(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'caption_cache_dir',tmp_path/'cache')
    calls=[]
    def fetch(args,**kw):
        calls.append(args)
        out=Path(args[-1]).parent;out.mkdir(parents=True,exist_ok=True)
        (out/'selection-auto.en-orig.json3').write_text(json.dumps({'events':[{'tStartMs':0,'dDurationMs':60000,'segs':[{'utf8':'Original draft ' * 20}]}]}))
        assert kw['metadata_input']['id']=='abcdefghijk'
        assert '--write-auto-subs' in args and args[args.index('--retries')+1]=='0'
    monkeypatch.setattr(selection_draft.youtube,'ytdlp',fetch)
    info={'id':'abcdefghijk','language':'en','automatic_captions':{'en-orig':[]}}
    a=selection_draft.fetch_selection_captions('abcdefghijk',tmp_path/'one',60,info)
    assert a['selection_only'] and a['words']==[] and not a['caption_cached']
    b=selection_draft.fetch_selection_captions('abcdefghijk',tmp_path/'two',60,info)
    assert b['caption_cached'] and len(calls)==1
    selection_draft.fetch_selection_captions('abcdefghijk',tmp_path/'three',60,info,fresh_captions=True)
    assert len(calls)==2
    (tmp_path/'cache/abcdefghijk/selection-auto/auto.json3').write_text('{}')
    selection_draft.fetch_selection_captions('abcdefghijk',tmp_path/'four',60,info)
    assert len(calls)==3


def test_auto_429_is_one_pass_and_diagnostic_is_private(tmp_path,monkeypatch):
    calls=[]
    def fail(*a,**kw):calls.append(1);raise RuntimeError('HTTP Error 429 https://example/?secret=hidden')
    monkeypatch.setattr(selection_draft.youtube,'ytdlp',fail)
    info={'language':'en','automatic_captions':{'en-orig':[]}}
    for _ in range(2):
        with pytest.raises(Exception):selection_draft.fetch_selection_captions('abcdefghijk',tmp_path,60,info)
    assert len(calls)==1 and 'secret=hidden' not in (tmp_path/'selection-auto-request.json').read_text()


def test_selection_draft_cannot_supply_render_words(tmp_path):
    from reel_engine.youtube_transcript import require_verified_words
    path=tmp_path/'transcript.json';path.write_text(json.dumps({'provider':'local-selection-draft','words':[]}))
    with pytest.raises(ValueError):require_verified_words({'transcript':str(path)}, {})


def test_draft_english_model_and_verification_unchanged(monkeypatch):
    monkeypatch.setattr(settings,'selection_draft_model','base')
    assert selection_draft.draft_model('en-US')=='base.en'
    assert selection_draft.draft_model('hi')=='base'
    assert settings.whisper_model=='small' and settings.whisper_beam_size==5


@pytest.mark.parametrize('height,size,strategy',[(1080,100000000,'eager-full'),(2160,100000000,'selected-sections'),(1080,2000000000,'selected-sections')])
def test_full_download_policy(height,size,strategy):
    info={'duration':900,'formats':[{'height':height,'vcodec':'h264','filesize':size}]}
    assert download_policy.choose_download(info,1500000000,2160)['strategy']==strategy


def test_fast_motion_and_boundary_flag_before_review():
    rows=[{'t':0,'center':.5,'camera_center':.5,'width':.1,'crop_width':.316,'confidence':1},
          {'t':.1,'center':.65,'camera_center':.51,'width':.1,'crop_width':.316,'confidence':1}]
    flags=motion_check.motion_flags(rows,0,45)
    assert flags[0]['near_boundary'] and 'subject_motion_exceeds_eased_camera_slack' in flags[0]['reasons']
    rows[1].update(center=.5,camera_center=.5)
    assert not motion_check.motion_flags(rows,0,45)


def test_missing_proxy_motion_requires_every_scene_review(tmp_path):
    result=motion_check.for_job({'tracking':{'visual_targets':[{'start':0,'end':3},{'start':3,'end':7}]}},tmp_path)
    assert result['flagged_source_seconds']==[1.5,5.] and result['review_fallback']


def test_compact_baseline_and_flagged_scene_only(monkeypatch):
    from reel_engine.review import compact_review_groups
    monkeypatch.setattr(settings,'compact_pre_review',True)
    edit={'segments':[{'source_start':0,'source_end':60,'output_start':0,'output_end':60}]}
    tracking={'visual_targets':[{'start':i*5,'end':i*5+5} for i in range(12)]}
    first=compact_review_groups(edit,tracking)
    assert len(first)==1 and first[0][0]==-1 and len(first[0][1])<=8
    tracking['flagged_output_seconds']=[26]
    groups=compact_review_groups(edit,tracking)
    assert [g[0] for g in groups]==[-1,2]


def test_proxy_review_maps_times_without_mutating_final_edit(tmp_path):
    from reel_engine.review import proxy_review_input
    from reel_engine.render import file_hash
    proxy=tmp_path/'proxy.mkv';proxy.write_bytes(b'proxy')
    parent=tmp_path/'source';parent.mkdir()
    (parent/'job.json').write_text(json.dumps({'proxy':{'source':str(proxy),'source_sha256':file_hash(proxy)}}))
    child=tmp_path/'clip';child.mkdir()
    (child/'job.json').write_text(json.dumps({'source_job_id':'source','source_time_offset':100.}))
    edit={'segments':[{'source_start':3,'source_end':40}],'words':[{'source_start':4,'source_end':5}]}
    tracking={'visual_targets':[{'start':3,'end':40,'box_keyframes':[{'t':3,'box':[.4,.2,.1,.3]}]}],'camera_cuts':[8],'crop_keyframes':[{'t':3,'center':.5}],'samples':[{'t':3}]}
    before=copy.deepcopy((edit,tracking))
    source,mapped,camera,used=proxy_review_input('full.mkv',edit,tracking,child)
    assert used and source==proxy and mapped['segments'][0]['source_start']==103
    assert mapped['words'][0]['source_start']==104 and camera['camera_cuts']==[108]
    assert camera['visual_targets'][0]['box_keyframes'][0]['t']==103 and camera['samples'][0]['t']==103
    assert (edit,tracking)==before
    proxy.write_bytes(b'bad')
    with pytest.raises(ValueError,match='proxy hash'):proxy_review_input('full.mkv',edit,tracking,child)


def test_workflow_envelope_does_not_hide_gaps(tmp_path):
    for name,a,b in [('workflow',0,100),('download',0,10),('render',90,100)]:
        timing.mark(tmp_path,'test',name,'start',run_id='run',at=a)
        timing.mark(tmp_path,'test',name,'end',run_id='run',at=b)
    report=timing.report(tmp_path,'test')
    assert report['untracked_wall_seconds']==80 and report['gaps'][0]['start']==10


def test_cli_overhead_and_between_command_accounting(tmp_path):
    timing.mark(tmp_path,'test','metadata','start',run_id='run',at=1)
    timing.mark(tmp_path,'test','metadata','end',run_id='run',at=2)
    timing.record_command_coverage(tmp_path,'test','analyze',0,3,True)
    timing.record_command_coverage(tmp_path,'test','prepare',6,8,True)
    report=timing.report(tmp_path,'test')
    assert report['wall_seconds']==8 and report['untracked_wall_seconds']==0
    assert next(i for i in report['intervals'] if i['stage']=='between_commands')['seconds']==3


def test_base_draft_is_segment_only_and_cached(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import faster_whisper
    from reel_engine import render
    monkeypatch.setattr(settings,'local_model_dir',tmp_path/'models')
    monkeypatch.setattr(settings,'selection_draft_model','base')
    monkeypatch.setattr(render,'run',lambda *a,**kw:None)
    calls=[]
    class FakeWhisper:
        def __init__(self,name,**kw):assert name=='base.en' and kw['device']=='cpu' and kw['compute_type']=='int8'
        def transcribe(self,*a,**kw):
            calls.append(kw)
            return iter([SimpleNamespace(start=0.,end=1.,text='Hello world')]),SimpleNamespace(language='en')
    monkeypatch.setattr(faster_whisper,'WhisperModel',FakeWhisper)
    source=tmp_path/'audio.wav';source.write_bytes(b'media')
    root=tmp_path/'draft'
    result=selection_draft.transcribe_selection_draft(source,root,'en')
    data=json.loads(Path(result['transcript']).read_text())
    assert data['provider']=='local-selection-draft' and not data['words'] and data['selection_only']
    assert calls==[{'language':'en','beam_size':1,'word_timestamps':False,'vad_filter':True}]
    assert selection_draft.transcribe_selection_draft(source,root,'en')['transcription_timings']['checkpoint_reused']


def test_eager_download_reuses_only_hash_verified_full_media(tmp_path,monkeypatch):
    from reel_engine import eager_download,youtube
    source=tmp_path/'full.mkv';source.write_bytes(b'full quality')
    calls=[]
    def download(*a,**kw):
        calls.append(kw)
        assert kw['no_retries']
        return {'source':str(source),'metadata':{'best_available_height':1080}}
    monkeypatch.setattr(youtube,'download',download)
    info={'id':'abcdefghijk','duration':900,'formats':[{'height':1080,'vcodec':'h264'}]}
    root=tmp_path/'jobs/abcdefghijk';root.mkdir(parents=True)
    eager_download.work(tmp_path,'abcdefghijk','run1',info)
    eager_download.work(tmp_path,'abcdefghijk','run2',info)
    assert len(calls)==1 and json.loads((root/'eager-full-run2.json').read_text())['cached']
    source.write_bytes(b'corrupted')
    eager_download.work(tmp_path,'abcdefghijk','run3',info)
    assert len(calls)==2
