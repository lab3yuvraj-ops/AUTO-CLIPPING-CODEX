"""Offline orchestration safety tests. No media or provider calls occur."""
import json
import threading
from pathlib import Path
import pytest
import reel
from reel_engine import fast, timing, fast_download, fast_gate, overview
from reel_engine.youtube_transcript import atomic_json


def job_record(tmp_path,ident='source_test_fast',**extra):
    root=tmp_path/'jobs'/ident;root.mkdir(parents=True,exist_ok=True)
    job={'id':ident,'video_id':'abcdefghijk','run_id':'test_run','requested_clips':2,'fast':True,**extra}
    atomic_json(root/'job.json',job);return job,root


def test_rejected_benchmark_stops_and_normal_fast_falls_back(tmp_path):
    calls=[]
    def normal(**kwargs):calls.append(kwargs);return {'id':'normal_source'}
    for ident,stop in [('benchmark_source',True),('ordinary_source',False)]:
        job,root=job_record(tmp_path,ident,stop_on_fast_rejection=stop)
        timing.mark(tmp_path,ident,'workflow','start',run_id=job['run_id'])
        result=fast.reject(tmp_path,job,root,['live_action'],normal)
        assert result['status']=='Fast gate rejected' and not result['fast_eligible']
        assert timing.report(tmp_path,ident)['intervals'][-1]['outcome']=='rejected'
    assert calls==[{'url':'https://www.youtube.com/watch?v=abcdefghijk','clips':2}]
    assert fast._read(tmp_path/'jobs'/'ordinary_source'/'job.json')['normal_fallback_job']=='normal_source'


def test_real_shaped_speaker_metrics_reach_visual_gate(tmp_path,monkeypatch):
    from reel_engine import eager_download
    monkeypatch.setattr(eager_download,'start',lambda *a,**kw:{'run_id':'test'})
    info={'id':'abcdefghijk','title':'Presenter','duration':120.,'availability':'public','formats':[{'height':1080,'vcodec':'h264'}]}
    monkeypatch.setattr(fast.youtube,'ytdlp',lambda *a,**kw:json.dumps(info))
    calls=[]
    def captions(*a,**kw):
        calls.append(kw['max_attempts']);return {'provider':'youtube-captions','cues':[{'start':0,'end':120,'text':'complete'}]}
    monkeypatch.setattr(fast,'fetch_caption_draft',captions)
    monkeypatch.setattr(fast_download,'download_proxy',lambda *a,**kw:{'source':'proxy.mp4','source_sha256':'proxy_hash'})
    monkeypatch.setattr(overview,'make_overview',lambda *a,**kw:{'pages':1,'page_files':[],'source_seconds':120.})
    monkeypatch.setattr(fast_gate,'gather_visual_samples',lambda *a,**kw:{'visual_samples_sha256':'sample_hash','overview_hashes':{},'pages':[]})
    result=fast.analyze_fast(tmp_path,'https://www.youtube.com/watch?v=abcdefghijk',2,fresh=True,stop_on_rejection=True)
    assert result['status']=='Fast selection ready; classify selected passages'
    assert result['gate_pending'] and not result.get('fast_eligible',False)
    assert calls==[1]


def test_prepare_refuses_unaccepted_eligibility(tmp_path):
    job,root=job_record(tmp_path,fast_eligible=False)
    selection=root/'selection.json';atomic_json(selection,{'candidates':[]})
    with pytest.raises(ValueError,match='accepted evidence gate'):fast.prepare_selected(tmp_path,job,selection)


def test_proxy_and_word_evidence_guards_before_media_processing(tmp_path,monkeypatch):
    monkeypatch.setattr(reel,'probe',lambda _:pytest.fail('Guard must run before media processing'))
    spec={'candidate':{'start':0,'end':35},'words':[{'id':'w1','start':1,'end':2,'roman':'Hello'}],'tracking':{}}
    with pytest.raises(ValueError,match='proxy pixels'):reel.prepare_edit({'media_kind':'proxy'},spec,tmp_path)
    transcript=tmp_path/'transcript.json';atomic_json(transcript,{'provider':'youtube-captions'})
    job={'transcript':str(transcript),'source_sha256':'final_media'}
    with pytest.raises(ValueError,match='verify'):reel.prepare_edit(job,spec,tmp_path)
    atomic_json(tmp_path/'verified-passages.json',{'source_sha256':'final_media','passages':[{'range':[0,35],'words':[{'id':'different','start':1,'end':2}]}]})
    with pytest.raises(ValueError,match='verified word IDs'):reel.prepare_edit(job,spec,tmp_path)
    atomic_json(tmp_path/'verified-passages.json',{'source_sha256':'proxy_media','passages':[]})
    with pytest.raises(ValueError,match='different source'):reel.prepare_edit(job,spec,tmp_path)


def test_fast_missing_transcript_cannot_bypass_verified_words(tmp_path,monkeypatch):
    monkeypatch.setattr(reel,'probe',lambda _:pytest.fail('Missing word evidence must block before media processing'))
    job={'fast':True,'fast_eligible':True,'verification_route':'proxy_verified_anchor_matched',
         'media_kind':'section','source':'final.mp4','source_sha256':'hash',
         'transcript':str(tmp_path/'missing-transcript.json')}
    spec={'candidate':{'start':0,'end':35},'words':[{'id':'w1','start':1,'end':2,'roman':'Hello'}],'tracking':{}}
    with pytest.raises(ValueError):reel.prepare_edit(job,spec,tmp_path)


def test_parallel_jobs_isolated_and_one_failure_retains_other_success(tmp_path,monkeypatch):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(fast,'parallel_budget',lambda:{'workers':2,'threads_per_clip':2})
    records=[]
    for ident in ('clip_one_test','clip_two_test'):
        job_record(tmp_path,ident)
        atomic_json(tmp_path/f'{ident}.json',{})
        records.append({'job':ident,'edit':f'{ident}.json'})
    manifest=tmp_path/'batch.json';atomic_json(manifest,records)
    barrier=threading.Barrier(2);calls=[]
    def render(ident,edit,**kwargs):
        calls.append((ident,edit,kwargs));barrier.wait(timeout=5)
        if ident=='clip_two_test':raise RuntimeError('provider_secret_should_not_leak')
        output=reel.job_path(ident).parent/'reel.mp4';output.write_bytes(b'success')
        return {'id':ident,'video':str(output),'config':{'secret':'never'}}
    monkeypatch.setattr(reel,'render',render)
    report=reel.batch(manifest,'render')
    assert len(calls)==2 and all(c[2]['threads']==2 for c in calls)
    assert report['results'][0]['ok'] and not report['results'][1]['ok']
    assert not report['all_succeeded'] and not report['publication_authorized']
    assert Path(report['results'][0]['result']['video']).read_bytes()==b'success'
    text=(tmp_path/'batch-render-report.json').read_text();assert 'provider_secret' not in text and 'never' not in text
    assert calls[0][1]!=calls[1][1]


def test_keep_lossless_dispatches_normal_renderer(tmp_path,monkeypatch):
    from reel_engine import final_review
    monkeypatch.setattr(reel,'_pre_render_review_guard',lambda job,*a:job.update(review_policy={'policy':'full-first-pass'}))
    monkeypatch.setattr(final_review,'sample_final',lambda *a:{'cache_reused':False})
    from reel_engine import outro, fast_render
    monkeypatch.setattr(reel,'STATE',tmp_path)
    job,root=job_record(tmp_path,'clip_normal_test',fast_eligible=True,verification_route='proxy_verified_anchor_matched',source='final.mp4',source_sha256='hash')
    spec={'candidate':{'start':0,'end':35},'caption':'Test'};spec_path=root/'spec.json';atomic_json(spec_path,spec)
    edit={'duration':35,'words':[],'segments':[]};tracking={}
    atomic_json(root/'skipped-words.json',{'skipped_count':0,'skipped_words':[]})
    monkeypatch.setattr(reel,'prepare_edit',lambda *a:(edit,tracking))
    monkeypatch.setattr(reel,'engine_version',lambda:'version')
    monkeypatch.setattr(outro,'resolve_outro',lambda *a:None)
    monkeypatch.setattr(fast_render,'fast_render_clip',lambda *a,**kw:pytest.fail('Must not direct render with keep-lossless'))
    calls=[]
    def normal(source,edit,tracking,path,config):
        calls.append(source);path.write_bytes(b'normal');return {'caption_events':[],'timings':{}}
    monkeypatch.setattr(reel,'render_clip',normal)
    monkeypatch.setattr(reel,'validate_render',lambda *a,**kw:[{'status':'pass'}])
    result=reel.render(job['id'],spec_path,keep_lossless=True)
    assert calls==['final.mp4'] and result['keep_lossless'] and result['render_mode']=='lossless'


@pytest.mark.parametrize('speaker_count,skip',[(1,True),(3,False)])
def test_offset_mismatch_saves_resumable_section_child(tmp_path,monkeypatch,speaker_count,skip):
    from reel_engine import local_transcription
    job,root=job_record(tmp_path,fast_eligible=True,metadata={'duration':100.},created=0,speaker_count=speaker_count,crop_strategy='fixed')
    proxy=root/'proxy.mp4';proxy.write_bytes(b'proxy')
    section=root/'section.mp4';section.write_bytes(b'section')
    job['proxy']={'source':str(proxy),'source_sha256':fast.file_hash(proxy)}
    atomic_json(root/'fast-gate.json',{'eligible':True})
    atomic_json(root/'transcript.json',{'provider':'youtube-captions','language':'en'})
    page=root/'detail-page.jpg';page.write_bytes(b'reviewed source evidence');pages={str(page):fast.file_hash(page)}
    atomic_json(root/'selected-details.json',{'passages':[{'range':[10.,45.],'source_sha256':fast.file_hash(proxy),'page_files':[{'file':str(page),'sha256':fast.file_hash(page)}]}]})
    selection=root/'selection.json';atomic_json(selection,{'candidates':[{'start':10.,'end':45.,'reason':'Complete story','opening':'Opening','ending':'Payoff','passage_evidence':{'reviewed_by':'Codex','source_sha256':fast.file_hash(proxy),'reviewed_page_hashes':pages,'reason':'Actual selected frames and speech inspected','animated':False,'classification':'single/dominant-presenter' if skip else 'multi-speaker dialogue','identity_confident':True,'chosen_strategy':'fixed'}}]})
    monkeypatch.setattr(fast.youtube,'ytdlp',lambda *a,**kw:json.dumps({'duration':100.}))
    monkeypatch.setattr(fast_download,'download_section',lambda *a,**kw:{'source':str(section),'kind':'section','height':1080,'padded_range':[7.,48.],'source_offset':7.})
    monkeypatch.setattr(fast_download,'confirm_section_audio',lambda *a,**kw:{'offset_verified':False,'verify_section_required':True})
    monkeypatch.setattr(fast,'probe',lambda *a:{'format':{'duration':41.}})
    calls=[]
    def verify(source,folder,ranges,**kwargs):
        calls.append((str(source),kwargs));folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        output=folder/'verified-passages.json'
        atomic_json(output,{'source_sha256':fast.file_hash(source),'passages':[{'range':list(ranges[0]),'words':[{'id':'w1','start':8.,'end':9.,'confidence':.8}],'signature':'evidence'}]})
        return {'verified_passages':str(output)}
    monkeypatch.setattr(local_transcription,'verify_passages',verify)
    from reel_engine import speech_worker,detail
    monkeypatch.setattr(speech_worker,'request',lambda root,run,op,args=None,**kw:verify(args['source'],args['root'],args['ranges'],skip_diarization=args['skip_diarization']) if op=='verify' else {'stopped':True})
    monkeypatch.setattr(detail,'make_details',lambda *a,**k:{'passages':[]})
    report=fast.prepare_selected(tmp_path,job,selection)
    child=report['clips'][0]
    assert len(calls)==2 and all(kwargs['skip_diarization']==skip for _,kwargs in calls)
    child_path=tmp_path/'jobs'/child['id']/'job.json'
    assert child_path.exists(),'Section-local fallback must be resumable through standard CLI job commands'
    saved=fast._read(child_path)
    assert saved['source']==str(section) and saved['source_sha256']==fast.file_hash(section)
    assert saved['status']=='Needs section editorial boundaries'
