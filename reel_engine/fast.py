"""Opt-in staged fast workflow. Original source, word and approval guards remain."""
import copy
import concurrent.futures
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from . import youtube
from .config import settings
from .youtube_transcript import atomic_json
from .selection_draft import fetch_selection_captions as fetch_caption_draft
from .render import file_hash,probe
from .timing import stage,mark


def _read(p):return json.loads(Path(p).read_text(encoding='utf-8'))


def save_clip_record(folder,child):
    path=Path(folder)/'job.json';old=_read(path) if path.exists() else {}
    if old.get('publishing') or old.get('post_id'):raise ValueError('Existing publication state is preserved; reconcile it before reprocessing this clip.')
    # Retain render provenance so a changed edit still chooses lossless revision
    # rendering. A preparation retry must not erase expensive saved work.
    result={**old,**child};result.pop('approval',None)
    atomic_json(path,result)
    return result


def analyze_fast(state,url,clips,*,fresh=False,stop_on_rejection=False,normal_analyze=None,fresh_captions=False,caption_max_attempts=4,careful_sections=False):
    from .fast_download import download_proxy
    from .overview import make_overview
    from .fast_gate import gather_visual_samples
    state=Path(state);video=youtube.video_id(url)
    if settings.local_device!='cpu' or settings.local_compute_type!='int8' or settings.whisper_model!='small':raise ValueError('Fast mode requires the approved cached Whisper small CPU/int8 configuration.')
    if not isinstance(clips,int) or isinstance(clips,bool) or clips<1:raise ValueError('Fast analysis requires a positive clip count.')
    suffix='-sections' if careful_sections else '-fast'
    ident=video+suffix+'-'+uuid.uuid4().hex[:8] if fresh else video+suffix
    root=state/'jobs'/ident;root.mkdir(parents=True,exist_ok=True)
    path=root/'job.json';job=_read(path) if path.exists() else {'id':ident,'video_id':video,'created':time.time(),'requested_clips':clips,'fast':True,'stop_on_fast_rejection':stop_on_rejection,'benchmark_fresh':fresh,'run_id':uuid.uuid4().hex,'status':'Fast preparation','config':{'auto_publish':False}}
    if path.exists():job['run_id']=uuid.uuid4().hex
    run=job['run_id'];atomic_json(path,job)
    if careful_sections:
        job.update(fast=False,careful_sections=True);atomic_json(path,job)
    # Saved runs resume honestly; new benchmark roots never reference another source job.
    timingpath=state/'stage-timings.jsonl'
    if not timingpath.exists() or not any(json.loads(x).get('run_id')==run for x in timingpath.read_text().splitlines() if x.strip()):
        mark(state,ident,'workflow','start',run_id=run)
    def timed(name,call,cached=False):
        with stage(state,ident,name,run_id=run,cached=False) as interval:
            result=call()
            if isinstance(result,dict):interval['cached']=bool(result.get('caption_cached') or result.get('cached') or result.get('cache_reused'))
            return result
    try:
        info=timed('metadata',lambda:json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',f'https://www.youtube.com/watch?v={video}'])))
        if not info.get('duration') or info['duration']>settings.max_source_seconds:raise ValueError('Source exceeds the configured duration limit.')
        if info.get('is_live') or info.get('live_status') in ('is_live','is_upcoming','post_live') or info.get('availability') not in (None,'public'):raise ValueError('Fast source must be released, public and processed.')
        job['metadata']={k:info.get(k) for k in ('id','title','duration','channel_id','upload_date','width','height','fps')}
        job['highest_height']=max((f.get('height') or 0 for f in info.get('formats',[]) if f.get('vcodec') not in (None,'none')),default=0)
        from .download_policy import choose_download
        policy=choose_download(info,settings.full_download_max_bytes,settings.section_download_min_height)
        job['download_policy']=policy;atomic_json(root/'download-policy.json',policy)
        atomic_json(path,job)
        import threading
        from .local_transcription import transcribe_local
        from .proxy_asr import bind_proxy_asr
        audio_ready=concurrent.futures.Future();asr_done=threading.Event();asr_cancel=threading.Event();asr_lock=threading.Lock();asr_futures=[]
        def audio_available(source):
            if not audio_ready.done():audio_ready.set_result(source)
        def proxy_transfer():
            try:
                result=download_proxy(info,root/'proxy',on_audio_ready=audio_available)
                audio_available(result['source']);return result
            except Exception as exc:
                if not audio_ready.done():audio_ready.set_exception(exc)
                raise
        # Signature-bound checkpoint survives retries; fresh runs use a fresh job root.
        asr_root=root/'proxy-asr'/'selection-draft'
        def local_asr():
            try:
                with stage(state,ident,'local_asr_audio_wait',run_id=run):audio=audio_ready.result()
                target=asr_root
                target.mkdir(parents=True,exist_ok=True)
                with stage(state,ident,'selection_draft_asr',run_id=run) as interval:
                    from .selection_draft import transcribe_selection_draft
                    result=transcribe_selection_draft(audio,target,info.get('language'))
                    interval['cached']=bool(result['transcription_timings'].get('checkpoint_reused'))
                asr_done.set()
                return audio,result,target
            finally:
                if asr_cancel.is_set():asr_done.set()
        def start_asr(reason):
            with asr_lock:
                if not asr_futures:
                    atomic_json(root/'transcript-route.json',{'route':'local ASR','reason':reason,'status':'starting as soon as complete validated proxy audio is available'})
                    asr_futures.append(pool.submit(local_asr))
        def captions():
            caption_root=root/'caption-fetches'/run
            try:
                data=fetch_caption_draft(video,caption_root,float(info['duration']),info=info,timing_hook=lambda name:stage(state,ident,name,run_id=run),fresh_captions=fresh_captions,max_attempts=1,on_failure=start_asr,stop_wait=asr_done)
                atomic_json(root/'transcript.json',data)
                print(json.dumps({'caption_draft_ready':str((root/'transcript.json').resolve()),'job':ident,'run_id':run}),flush=True)
                asr_cancel.set()
                return data
            except Exception as exc:
                # Retain any returned uploaded cues for audit; do not refill
                # gaps or use their text/timing instead of verified ASR.
                from .youtube_transcript import parse_json3
                for raw in caption_root.glob('uploaded-captions.*.json3'):
                    try:
                        body=_read(raw);body['language']=raw.name.split('.')[-2]
                        atomic_json(root/'partial-uploaded-captions.json',parse_json3(body,float(info['duration']),require_coverage=False))
                    except (ValueError,KeyError):pass
                start_asr(getattr(exc,'diagnostic',{'category':'unknown_fetch_failure','yt_dlp_message':str(exc)}))
                raise
        def eligibility_samples():
            from .errors import StageError
            try:
                with stage(state,ident,'eligibility_proxy_wait',run_id=run):accepted=pf.result()
                result=gather_visual_samples(info,root,local_proxy=accepted)
            except StageError as exc:
                with stage(state,ident,'eligibility_proxy_wait',run_id=run):accepted=pf.result()
                with stage(state,ident,'eligibility_local_sampling',run_id=run):result=gather_visual_samples(info,root,local_proxy=accepted)
                result['remote_sampling_failure']=str(exc)
            return result
        if policy['strategy']=='eager-full':
            from .eager_download import start
            job['eager_download']=start(state,job,info);atomic_json(path,job)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            pf=pool.submit(timed,'proxy_download',proxy_transfer)
            cf=pool.submit(timed,'caption_draft',captions)
            ef=pool.submit(timed,'eligibility_sampling',eligibility_samples)
            proxy=pf.result()
            # Whole-source overview can be prepared while local ASR is running.
            def overview_task():
                result=make_overview(proxy['source'],root,interval=30)
                print(json.dumps({'proxy_overview_ready':result['pages'],'job':ident,'run_id':run}),flush=True)
                return result
            overview_future=pool.submit(timed,'proxy_overview',overview_task)
            caption_error=None
            try:data=cf.result()
            except Exception as exc:caption_error=getattr(exc,'diagnostic',{'category':'unknown_fetch_failure','yt_dlp_message':str(exc)});data=None
            if data is not None:
                job.update(proxy=proxy,source=proxy['source'],source_sha256=proxy['source_sha256'],media_kind='proxy',transcript=str((root/'transcript.json').resolve()),status='Transcript and proxy ready for whole-source selection')
                atomic_json(path,job)
                print(json.dumps({'selection_inputs_ready':True,'job':ident,'run_id':run}),flush=True)
            eligibility=ef.result()
            if asr_futures and caption_error:
                audio,asr,used_asr_root=asr_futures[0].result()
                with stage(state,ident,'asr_proxy_audio_binding',run_id=run):
                    from .selection_draft import transcribe_selection_draft
                    data=bind_proxy_asr(audio,used_asr_root,proxy,root,transcribe=lambda source,target:transcribe_selection_draft(source,target,info.get('language')))
                route={'route':'local ASR','reason':caption_error or _read(root/'transcript-route.json')['reason'],'asr_timings':asr['transcription_timings'],'audio_equivalence':data['audio_equivalence'],'caption_retry_not_blocking':True}
            else:
                if asr_futures:
                    try:asr_futures[0].result()
                    except Exception:pass
                route={'route':'captions','caption_kind':data.get('caption_kind','uploaded'),'reason':'Native selection-only track passed coverage checks; selected words still require Whisper small/beam5.','cached':bool(data.get('caption_cached'))}
                atomic_json(root/'transcript.json',data)
            overview=overview_future.result()
        atomic_json(root/'transcript-route.json',route)
        job.update(proxy=proxy,source=proxy['source'],source_sha256=proxy['source_sha256'],media_kind='proxy',transcript=str((root/'transcript.json').resolve()),transcript_route=route,caption_cached=bool(data.get('caption_cached')))
        job['eligibility_samples']=eligibility
        if caption_error:job['caption_failure']=caption_error
        job['overview']={k:overview[k] for k in ('pages','page_files','source_seconds')};atomic_json(path,job)
        job.update(status='Fast selection ready; classify selected passages',gate_pending=True)
        atomic_json(path,job);atomic_json(root/'fast-gate.json',{'eligible':False,'pending':True,'scope':'selected passages','reasons':['Rank the whole source, inspect selected passage frames, then classify each selected passage.'],'transcript_route':route['route']})
        return job
    except Exception as exc:
        job.update(status='Fast preparation failed',error=str(exc));atomic_json(path,job)
        mark(state,ident,'workflow','end',run_id=run,outcome='failed')
        raise


def reject(state,job,root,reasons,normal_analyze=None):
    job.update(status='Fast gate rejected',gate_pending=False,fast_eligible=False,fast_rejection_reasons=reasons)
    saved_gate=Path(root)/'fast-gate.json'
    details=_read(saved_gate) if saved_gate.exists() else {}
    atomic_json(saved_gate,{**details,'eligible':False,'status':'rejected','reasons':reasons,'audio':job.get('speaker_evidence')})
    atomic_json(Path(root)/'job.json',job)
    print(json.dumps({'fast_rejected':reasons,'job':job['id']}),flush=True)
    if not job.get('stop_on_fast_rejection') and normal_analyze:
        with stage(state,job['id'],'normal_fallback',run_id=job['run_id']):result=normal_analyze(url=f"https://www.youtube.com/watch?v={job['video_id']}",clips=job['requested_clips'])
        job['normal_fallback_job']=result['id'];atomic_json(Path(root)/'job.json',job)
    mark(state,job['id'],'workflow','end',run_id=job['run_id'],outcome='rejected')
    return job


def gate(state,job,evidence_path,normal_analyze=None):
    from .passage_gate import classify_selection,require_selected_review
    root=Path(state)/'jobs'/job['id'];selection=_read(evidence_path)
    if not selection.get('candidates') or len(selection['candidates'])>job['requested_clips']:raise ValueError('Classify a nonempty selection within the requested clip count.')
    if file_hash(job['source'])!=job['source_sha256']:raise ValueError('Proxy changed before passage classification.')
    require_selected_review(root,selection,job['source_sha256'])
    records=preparation_classifications(selection,job)
    atomic_json(root/'passage-classifications.json',records)
    if not all(r['eligible'] for r in records):return reject(state,job,root,[r['reason'] for r in records if not r['eligible']],normal_analyze)
    job.update(status='Fast selected passages ready',gate_pending=False,fast_eligible=True,passage_classifications=records)
    atomic_json(root/'fast-gate.json',{'eligible':True,'scope':'selected passages','passages':records})
    atomic_json(root/'job.json',job)
    return job


def parallel_budget(cpu_count=None):
    cores=cpu_count or os.cpu_count() or 1
    workers=2 if cores>=8 else 1
    return {'workers':workers,'threads_per_clip':max(1,min(8,cores//workers)),'logical_cpu_count':cores}


def preparation_classifications(selection,job):
    from .passage_gate import classify_selection
    from .preparation_speed import diarization_needed
    if not job.get('careful_sections'):return classify_selection(selection,job['source_sha256'])
    records=[]
    for c in selection['candidates']:
        e=c.get('passage_evidence',{})
        if e.get('reviewed_by')!='Codex' or e.get('source_sha256')!=job['source_sha256'] or not e.get('reason'):
            raise ValueError('Careful section preparation still requires reviewed source-bound passage evidence')
        records.append({'eligible':True,'classification':e.get('classification','careful character tracking'),
            'crop_strategy':e.get('chosen_strategy','fixed'),'diarization_required':diarization_needed(e),
            'reason':e['reason'],'careful_identity_review_required':True,'editorial_warnings':[] if e.get('identity_confident') is True or e.get('single_narrator') is True else ['Screen identity is unmappable: use a reviewed stable crop; do not infer character identity from audio labels.'],
            'range':[c['start'],c['end']]})
    return records


def prepare_selected(state,job,selection_path,normal_analyze=None):
    """Overlap ONE tight proxy ASR batch with highest-quality section downloads."""
    from .fast_download import download_section,section_range,confirm_section_audio
    from .local_transcription import verify_passages
    root=Path(state)/'jobs'/job['id'];run=job['run_id'];selection=_read(selection_path)
    if not job.get('fast_eligible') or not _read(root/'fast-gate.json').get('eligible'):raise ValueError('Fast preparation requires the accepted evidence gate.')
    proxy=job['proxy']
    if file_hash(proxy['source'])!=proxy['source_sha256']:raise ValueError('Proxy changed after eligibility review.')
    from .passage_gate import classify_selection,require_selected_review
    require_selected_review(root,selection,proxy['source_sha256'])
    classifications=preparation_classifications(selection,{**job,'source_sha256':proxy['source_sha256']})
    if not all(r['eligible'] for r in classifications):raise ValueError('Animated or undecidable selected passage requires careful-pipeline review; fast mode is not forced.')
    atomic_json(root/'passage-classifications.json',classifications)
    skip_flags=[not r['diarization_required'] for r in classifications]
    skip_diarization=skip_flags[0] if len(set(skip_flags))==1 else skip_flags
    candidates=selection['candidates'];duration=min(float(job['metadata']['duration']),float(proxy.get('duration',job['metadata']['duration'])))
    if not candidates or len(candidates)>job['requested_clips']:raise ValueError('Selection count exceeds the requested target.')
    ranges=[]
    for c in candidates:
        a,b=float(c['start']),float(c['end'])
        if not 30<=b-a<=60 or not c.get('reason') or not c.get('opening') or not c.get('ending'):raise ValueError('Fast selection requires complete evidenced 30–60 second stories.')
        if any(min(b,y)-max(a,x)>.1*(b-a) for x,y in ranges):raise ValueError('Fast candidates substantially overlap.')
        ranges.append((a,b))
    padded=[section_range(a,b,duration) for a,b in ranges]
    atomic_json(root/'selection-report.json',selection)
    def verify():
        from .speech_worker import request
        with stage(state,job['id'],'selected_speech_verification',run_id=run):
            return request(root,run,'verify',{'source':proxy['source'],'root':str(root),'ranges':padded,'skip_diarization':skip_diarization},timing={'state':str(state),'job':job['id']})
    def sections():
        if job.get('eager_download') or job.get('eager_full'):
            from .eager_download import await_result
            with stage(state,job['id'],'full_quality_wait_after_selection',run_id=run):
                media=job.get('eager_full') or await_result(job['eager_download'])
            if file_hash(media['source'])!=media['source_sha256']:raise ValueError('Eager full-quality file changed before selected preparation.')
            with stage(state,job['id'],'full_quality_reused_after_selection',run_id=run,cached=True):
                return [{**media,'padded_range':bounds,'cached':True} for bounds in padded]
        with stage(state,job['id'],'section_metadata',run_id=run):
            info=json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',f"https://www.youtube.com/watch?v={job['video_id']}"]))
        from .fast_download import sections_or_full
        return sections_or_full(info,root,ranges,duration,
            full_download=lambda:youtube.download(SimpleNamespace(video_id=job['video_id'],config={'min_source_height':settings.min_source_height},created=job['created']),root/'full-fallback',info=info,no_retries=True),
            timing_hook=lambda name:stage(state,job['id'],name,run_id=run))
    def dense():
        from .detail import make_details
        with stage(state,job['id'],'dense_frame_extraction',run_id=run):return make_details(proxy['source'],root/'preparation-details',padded)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        vf=pool.submit(verify);sf=pool.submit(sections);df=pool.submit(dense)
        verification=vf.result();media=sf.result();dense_report=df.result()
    verified=_read(verification['verified_passages']);passages=[next(p for p in verified['passages'] if p['range']==bounds) for bounds in padded]
    attention={'passages':[{'range':p['range'],'low_confidence_words':[w for w in p['words'] if w.get('confidence',0)<.6 or w['end']<=w['start'] or w['end']-w['start']>1.5]} for p in passages],'policy':'Fast rechecks restricted to flagged speech; local word IDs required.'}
    atomic_json(root/'speech-attention.json',attention)
    clips=[]
    for i,(c,m,p) in enumerate(zip(candidates,media,passages)):
        classification=classifications[i]
        ident=job['id']+f'-clip{i+1}';folder=Path(state)/'jobs'/ident;folder.mkdir(parents=True,exist_ok=True)
        existing=_read(folder/'job.json') if (folder/'job.json').exists() else {}
        if existing.get('publishing') or existing.get('post_id'):raise ValueError('Existing publication state is preserved; reconcile it before reprocessing this clip.')
        with stage(state,job['id'],f'offset_check_{i+1}',run_id=run):
            check=confirm_section_audio(proxy['source'],m['source'],m['padded_range'] if m['kind']=='section' else [0,duration],p['words'])
        if check['offset_verified']:
            offset=check['source_offset'];words=copy.deepcopy(p['words']);route='proxy_verified_anchor_matched'
            for w in words:w['original_source_start']=w['start'];w['original_source_end']=w['end'];w['start']-=offset;w['end']-=offset
            local_range=[p['range'][0]-offset,p['range'][1]-offset]
            turns=[{**t,'start':t['start']-offset,'end':t['end']-offset} for t in p.get('speaker_turns',[])]
        else:
            # Proxy times are discarded. Broadly verify this tight downloaded section in the same cached process.
            atomic_json(folder/'transcript.json',{'provider':'youtube-captions','language':_read(root/'transcript.json').get('language'),'words':[],'requires_selected_verification':True})
            with stage(state,job['id'],f'section_verification_{i+1}',run_id=run):
                section_duration=float(probe(m['source'])['format']['duration'])
                bounds=m['padded_range'] if m['kind']=='full' else [0,section_duration]
                from .speech_worker import request
                verification_section=request(root,run,'verify',{'source':m['source'],'root':str(folder),'ranges':[list(bounds)],'skip_diarization':skip_flags[i]})
                local=_read(verification_section['verified_passages'])['passages'][0];words=local['words'];local_range=list(bounds)
            atomic_json(folder/'transcript.json',{'provider':'youtube-captions','language':_read(root/'transcript.json').get('language'),'words':[],'requires_selected_verification':True})
            child={'id':ident,'source_job_id':job['id'],'source':m['source'],'source_sha256':file_hash(m['source']),'transcript':str((folder/'transcript.json').resolve()),'metadata':job['metadata'],'fast':bool(job.get('fast')),'fast_eligible':True,'media_kind':m['kind'],'source_time_offset':None,'status':'Needs section editorial boundaries','run_id':run,'timing_job':job['id'],'original_candidate':c,'verified_words':str((folder/'verified-passages.json').resolve()),'verification_route':'section_verified_proxy_times_discarded','final_height':m['height']}
            child.update(crop_strategy=classification['crop_strategy'],passage_classification=classification,editorial_warnings=classification['editorial_warnings'])
            child=save_clip_record(folder,child);atomic_json(folder/'verification-route.json',{'route':'section_verified_proxy_times_discarded','offset_check':check,'status':'Needs section editorial boundaries','original_candidate':c})
            atomic_json(folder/'speech-attention.json',{'passages':[{'range':local_range,'low_confidence_words':[w for w in words if w.get('confidence',0)<.6 or w['end']<=w['start'] or w['end']-w['start']>1.5]}],'policy':attention['policy']})
            clips.append(child);continue
        # Clip records bind verified words to FINAL media, not the proxy's media hash.
        finalhash=file_hash(m['source']);atomic_json(folder/'verified-passages.json',{'source_sha256':finalhash,'passages':[{'range':local_range,'words':words,'speaker_turns':turns,'signature':p['signature'],'route':route,'proxy_source_sha256':proxy['source_sha256'],'offset_check':check,'word_timings_reused':bool(p.get('timings',{}).get('full_source_asr_reused'))}]})
        atomic_json(folder/'transcript.json',{'provider':'youtube-captions','language':_read(root/'transcript.json').get('language'),'words':[],'requires_selected_verification':True})
        child={'id':ident,'source_job_id':job['id'],'source':m['source'],'source_sha256':finalhash,'transcript':str((folder/'transcript.json').resolve()),'metadata':job['metadata'],'fast':bool(job.get('fast')),'fast_eligible':True,'media_kind':m['kind'],'source_time_offset':offset,'status':'Awaiting Codex edit','run_id':run,'timing_job':job['id'],'candidate_local':{**c,'start':c['start']-offset,'end':c['end']-offset},'verified_words':str((folder/'verified-passages.json').resolve()),'verification_route':route,'final_height':m['height']}
        child.update(crop_strategy=classification['crop_strategy'],passage_classification=classification,editorial_warnings=classification['editorial_warnings'])
        child=save_clip_record(folder,child);atomic_json(folder/'verification-route.json',{'route':route,'offset_check':check,'proxy_timings_used':True,'source_time_offset':offset,'word_timings_reused':bool(p.get('timings',{}).get('full_source_asr_reused'))});clips.append(child)
        atomic_json(folder/'speech-attention.json',{'passages':[{'range':local_range,'low_confidence_words':[w for w in words if w.get('confidence',0)<.6 or w['end']<=w['start'] or w['end']-w['start']>1.5]}],'policy':attention['policy']})
    job.update(status='Fast clips awaiting edit',clips=[{'id':c['id'],'status':c['status']} for c in clips]);atomic_json(root/'job.json',job)
    from .speech_worker import request
    request(root,run,'stop')
    return {'job':job['id'],'clips':clips,'verification':verification,'dense_proxy_frames':dense_report,'parallel_budget':parallel_budget()}


def check_recheck_ranges(root,ranges):
    attention=Path(root)/'speech-attention.json'
    if not attention.exists():raise ValueError('Fast rechecks require speech-attention flags first.')
    words=[w for p in _read(attention)['passages'] for w in p['low_confidence_words']]
    allowed=[]
    for w in sorted(words,key=lambda w:w['start']):
        a,b=max(0,w['start']-.6),w['end']+.6
        if allowed and a<=allowed[-1][1]:allowed[-1][1]=max(b,allowed[-1][1])
        else:allowed.append([a,b])
    if any(not any(x<=a<b<=y for x,y in allowed) for a,b in ranges):
        raise ValueError('Fast rechecks may cover only speech-attention flagged words with short audio margins.')
