"""Local Codex-operated Reel workflow. No web server or text/vision API."""
import argparse,hashlib,json,math,os,re,shutil,sys,time
from pathlib import Path
from types import SimpleNamespace
import httpx
from reel_engine.config import settings,ROOT
from reel_engine import youtube,publishing
from reel_engine.local_transcription import transcribe_local
from reel_engine.render import render_clip,validate_render,probe
from reel_engine.timeline import build_edit,silence_intervals
from reel_engine.visual_focus import validate_targets

STATE=ROOT/'workflow'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def engine_version():
    """Invalidate cached previews when the local editing implementation changes."""
    h=hashlib.sha256()
    rules=[ROOT/'AGENTS.md'] if (ROOT/'AGENTS.md').is_file() else []
    for path in sorted([ROOT/'reel.py',*(ROOT/'reel_engine').glob('*.py'),*rules]):
        h.update(path.name.encode());h.update(path.read_bytes())
    return h.hexdigest()
def job_path(ident):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}',ident):raise ValueError('Invalid job ID.')
    return STATE/'jobs'/ident/'job.json'
def connect(channel):
    if re.fullmatch(r'UC[A-Za-z0-9_-]{22}',channel):ident=channel
    else:
        if not re.fullmatch(r'https://(?:www\.)?youtube\.com/(?:@[A-Za-z0-9_.-]+|channel/UC[A-Za-z0-9_-]{22})/?',channel):raise ValueError('Use a YouTube channel ID or channel URL.')
        r=httpx.get(channel,timeout=30,follow_redirects=True);r.raise_for_status()
        ids=re.findall(r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"',r.text)
        if not ids:raise ValueError('Could not resolve this channel. Supply its UC channel ID.')
        ident=ids[0]
    save(STATE/'connection.json',{'channel_id':ident,'channel_url':channel})
    return {'channel_id':ident}
def latest():
    if not (STATE/'connection.json').exists():raise ValueError('No YouTube channel is connected. Say onboarding in Codex to configure your own channel first.')
    channel=read(STATE/'connection.json')['channel_id']
    r=httpx.get(youtube.topic(channel),headers={'Cache-Control':'no-cache'},timeout=30);r.raise_for_status()
    stamps=youtube.feed_published(r.content)
    videos=[v for v,c in youtube.feed_ids(r.content) if c==channel and 0<stamps.get(v,0)<=time.time()]
    if not videos:
        # RSS can lag a newly released upload. Read the channel's selected
        # Videos tab, not unrelated recommendations or arbitrary page IDs.
        response=httpx.get(f'https://www.youtube.com/channel/{channel}/videos',headers={'Cache-Control':'no-cache'},timeout=30,follow_redirects=True);response.raise_for_status()
        text=getattr(response,'text','');match=re.search(r'(?:var\s+)?ytInitialData\s*=\s*',text)
        data=json.JSONDecoder().raw_decode(text[match.end():])[0] if match else {}
        tabs=data.get('contents',{}).get('twoColumnBrowseResultsRenderer',{}).get('tabs',[])
        candidates=[]
        def visit(node):
            if isinstance(node,dict):
                renderer=node.get('videoRenderer',{})
                vid=renderer.get('videoId')
                if re.fullmatch(r'[A-Za-z0-9_-]{11}',vid or '') and not renderer.get('upcomingEventData'):candidates.append(vid)
                modern=node.get('lockupViewModel',{})
                vid=modern.get('contentId')
                if re.fullmatch(r'[A-Za-z0-9_-]{11}',vid or '') and modern.get('contentType')=='LOCKUP_CONTENT_TYPE_VIDEO':candidates.append(vid)
                for value in node.values():visit(value)
            elif isinstance(node,list):
                for value in node:visit(value)
        for tab in tabs:
            renderer=tab.get('tabRenderer',{})
            if renderer.get('selected'):visit(renderer.get('content',{}))
        if candidates:return candidates[0],channel
        raise ValueError('No released upload found in the connected channel’s feed or Videos tab.')
    return max(videos,key=lambda v:stamps[v]),channel

def use_section_preparation(file=None,full_local=False,full_source=False):
    return not file and not full_local and not full_source
def analyze(url=None,file=None,clips=None,full_local=False):
    if clips is not None and (not isinstance(clips,int) or isinstance(clips,bool) or clips<1):raise ValueError('Requested clip count must be a positive integer.')
    channel=None
    if file:
        source=Path(file).resolve();ident=digest(source)
    elif url:ident=youtube.video_id(url)
    else:ident,channel=latest()
    path=job_path(ident);root=path.parent
    job=read(path) if path.exists() else {'id':ident,'created':time.time(),'status':'Detected','config':{'min_source_height':settings.min_source_height,'channel_id':channel,'verify_channel':bool(channel),'auto_publish':False}}
    if clips is not None:
        job['requested_clips']=clips;save(path,job)
    if job.get('status')=='Published':return job
    if job.get('status')=='Needs approval':
        if job.get('engine_version') and job['engine_version']!=engine_version():
            job['status']='Awaiting Codex update';job['error']='Editing implementation changed. Review and render the saved edit with the current version.';save(path,job)
        return job
    try:
        if not job.get('source'):
            root.mkdir(parents=True,exist_ok=True);job['status']='Downloading';save(path,job)
            download_started=time.perf_counter()
            if file:
                destination=root/'source.mp4';shutil.copy2(source,destination);job['source']=str(destination)
            else:
                attempts=job.get('download_attempts',0)
                if attempts>=3:raise ValueError('Download retry limit reached. Resolve the saved error, then reset download_attempts explicitly.')
                job['download_attempts']=attempts+1;save(path,job)
                result=youtube.download(SimpleNamespace(video_id=ident,config=job['config'],created=job['created']),root)
                job.update(result)
            job['source_sha256']=digest(Path(job['source']));job['download_seconds']=time.perf_counter()-download_started;save(path,job)
        job['status']='Transcribing';save(path,job)
        from reel_engine.youtube_transcript import transcript_for_selection
        job.update(transcript_for_selection(job['source'],root,ident if not file and len(ident)==11 else None,force_local=full_local))
        from reel_engine.overview import make_overview
        overview=make_overview(job['source'],root)
        job['overview']={'pages':overview['pages'],'seconds':overview['seconds_this_run'],'cache_reused':overview['cache_reused'],'source_seconds':overview['source_seconds']}
        job['status']='Awaiting Codex edit';job.pop('error',None);save(path,job)
    except Exception as exc:
        job['error']=str(exc);save(path,job);raise
    return job

def draft(url=None,clips=None):
    """Make whole-source editorial text available before starting the download."""
    from reel_engine.youtube_transcript import fetch_caption_draft
    if clips is not None and (not isinstance(clips,int) or isinstance(clips,bool) or clips<1):
        raise ValueError('Requested clip count must be a positive integer.')
    ident,channel=(youtube.video_id(url),None) if url else latest()
    path=job_path(ident);root=path.parent;root.mkdir(parents=True,exist_ok=True)
    job=read(path) if path.exists() else {'id':ident,'created':time.time(),'status':'Detected',
        'config':{'min_source_height':settings.min_source_height,'channel_id':channel,'verify_channel':bool(channel),'auto_publish':False}}
    # Preserve exact previews, full transcripts and publication state.
    if job.get('transcript') and Path(job['transcript']).exists():
        return {'id':ident,'status':job['status'],'transcript':job['transcript'],
                'metadata':job.get('metadata',{}),'checkpoint_reused':True}
    if job.get('video') or job.get('publishing') or job.get('post_id'):
        raise ValueError('This job has a preview or publication. Restore its transcript before drafting; saved output is preserved.')
    started=time.perf_counter()
    info=json.loads(youtube.ytdlp(['--skip-download','--dump-single-json',f'https://www.youtube.com/watch?v={ident}'],timeout=90))
    if info.get('availability') not in (None,'public') or info.get('is_live') or info.get('live_status') in ('is_upcoming','is_live','post_live'):
        raise ValueError('Wait for a released, public, processed video before drafting.')
    duration=info.get('duration')
    if not duration or not 0<float(duration)<=settings.max_source_seconds:
        raise ValueError('Source duration is missing or exceeds the configured limit.')
    if channel and info.get('channel_id')!=channel:raise ValueError('Latest upload does not belong to the connected channel.')
    try:
        data=fetch_caption_draft(ident,root,float(duration),info=info)
    except Exception:
        # No full-local fallback is attempted without the actual source file.
        raise ValueError('Draft captions unavailable. Run analyze normally to download and use local transcription.') from None
    save(root/'transcript.json',data)
    job.update(status='Draft ready; source required',transcript=str((root/'transcript.json').resolve()),
               metadata={k:info.get(k) for k in ('id','title','duration','channel_id','upload_date')},
               draft_timings={'seconds_this_run':time.perf_counter()-started,'provider':'youtube-captions'})
    if clips is not None:job['requested_clips']=clips
    save(path,job)
    return {'id':ident,'status':job['status'],'transcript':job['transcript'],'metadata':job['metadata'],
            'seconds_this_run':job['draft_timings']['seconds_this_run'],
            'next':'Start analyze with the same source URL; read the draft while downloading. Selection remains tentative until source frames and local speech are reviewed.'}
def prepare_edit(job,spec,root):
    from reel_engine.youtube_transcript import require_verified_words
    if job.get('fast'):
        transcript=Path(job.get('transcript',''))
        evidence=transcript.parent/'verified-passages.json'
        if not transcript.is_file() or not evidence.is_file():
            raise ValueError('Fast clips require saved transcript and verified word evidence before review/render.')
        if read(transcript).get('provider') not in ('youtube-captions','local-asr-draft'):
            raise ValueError('Fast clips must retain the selected-word verification guard.')
        if digest(Path(job['source']))!=job.get('source_sha256'):
            raise ValueError('Final source changed after speech verification.')
        if job.get('verification_route')=='section_verified_proxy_times_discarded' and not spec.get('section_boundary_evidence'):
            raise ValueError('Inspect section-local speech and record section_boundary_evidence after discarding proxy offsets.')
        from reel_engine.fast_captions import apply_policy
        spec,caption_coverage=apply_policy(job,spec,root,settings)
    require_verified_words(job,spec)
    if job.get('media_kind')=='proxy':raise ValueError('Editorial proxy pixels cannot be used in a final render.')
    if job.get('fast') and (not job.get('fast_eligible') or not job.get('verification_route')):raise ValueError('Fast clip needs accepted eligibility and verified final-media timing route.')
    plan=spec['candidate'];words=spec['words'];tracking=spec['tracking']
    duration=float(probe(job['source'])['format']['duration'])
    if not 0<=plan['start']<plan['end']<=duration or not 30<=plan['end']-plan['start']<=60:raise ValueError('Select a complete source passage of 30–60 seconds within the video.')
    if (not words and not job.get('fast')) or len({w['id'] for w in words})!=len(words) or any(not w.get('roman') or not math.isfinite(w['start']) or not math.isfinite(w['end']) or not plan['start']<=w['start']<w['end']<=plan['end'] for w in words):raise ValueError('Supply unique Roman word IDs with valid source timing inside the passage.')
    tracking={**tracking,'mode':'auto','composition':'fill','crop_policy':'full_source_height_horizontal_only','camera_smoothing':True,'camera_easing_seconds':1.2}
    if job.get('fast') and job.get('passage_classification',{}).get('requires_stable_context'):
        from reel_engine.speaker_camera import build_speaker_camera
        scenes=tracking.get('context_scenes') or tracking.get('speaker_plan',{}).get('scenes')
        if not scenes:raise ValueError('Uncertain or widely separated speakers need reviewed stable context scenes before rendering.')
        camera=build_speaker_camera([],scenes,[],start=plan['start'],end=plan['end'])
        tracking={**tracking,**camera}
    elif job.get('fast') and job.get('crop_strategy')=='speaker-switching':
        from reel_engine.speaker_camera import build_speaker_camera
        speaker_plan=tracking.get('speaker_plan')
        if not speaker_plan:raise ValueError('Speaker-switching clips require reviewed scene-scoped visual/audio associations.')
        verified=read(root/'verified-passages.json')
        passage=next(p for p in verified['passages'] if p['range'][0]<=plan['start'] and plan['end']<=p['range'][1])
        associations=[] if job.get('passage_classification',{}).get('requires_stable_context') else speaker_plan['associations']
        camera=build_speaker_camera(passage.get('speaker_turns',[]),speaker_plan['scenes'],associations,start=plan['start'],end=plan['end'],min_hold_seconds=speaker_plan.get('min_hold_seconds',1.2))
        tracking={**tracking,**camera}
    tracking['visual_targets']=validate_targets(tracking.get('visual_targets',[]),plan['start'],plan['end'])
    if job.get('fast') and caption_coverage['caption_coverage_low']:
        tracking.setdefault('editorial_warnings',[]).append('caption coverage low')
    silence=root/'silences.json'
    if not silence.exists():save(silence,silence_intervals(job['source']))
    edit=build_edit(plan,words,read(silence));edit['caption_positions']=[]
    if not 30<=edit['duration']<=60:raise ValueError('Edited duration must remain 30–60 seconds.')
    return edit,tracking

def review(ident,edit_path):
    job=read(job_path(ident))
    if job.get('fast'):
        from reel_engine.timing import stage
        with stage(STATE,job.get('timing_job',ident),'review_'+ident[-5:],run_id=job.get('run_id')) as interval:
            result=_review(ident,edit_path)
            interval['cached']=bool(result.get('cache_reused'))
            return result
    return _review(ident,edit_path)

def _review(ident,edit_path):
    from reel_engine.review import make_review
    path=job_path(ident);job=read(path);spec=read(Path(edit_path))
    from reel_engine.preflight import snap_spec,preflight
    from reel_engine.review_policy import register_round,save_policy
    spec=snap_spec(job['source'],spec,path.parent)
    register_round(path.parent,spec);save(Path(edit_path),spec)
    edit,tracking=prepare_edit(job,spec,path.parent)
    checks=preflight(job['source'],spec,edit,tracking,path.parent,settings.crop_safety_margin)
    from reel_engine.preflight import crop_review_flags
    tracking['flagged_output_seconds']=sorted(set(tracking.get('flagged_output_seconds',[])+crop_review_flags(checks)))
    policy=save_policy(path.parent,job,spec,checks)
    tracking['review_coverage']='all-scenes' if policy['full_first_pass'] else 'baseline-exceptions'
    result=make_review(job['source'],edit,tracking,path.parent)
    result['preflight']=checks
    result['review_policy']=policy
    result['review_engine_version']=engine_version()
    result['crop_action_warnings']=checks['crop_safety'].get('action_summary',[])
    save(path.parent/'review-result.json',result)
    return result

def prepare(ident,ranges,rechecks):
    """One invocation for selected verification and all known uncertain passages."""
    from reel_engine.local_transcription import verify_passages,recheck_local
    path=job_path(ident);job=read(path);root=Path(job['transcript']).parent
    if job.get('fast'):
        raise ValueError('Fast mode uses fast-prepare once for selected passages; speech rechecks are disabled. Reuse saved words when boundaries are unchanged.')
    started=time.perf_counter()
    verification=verify_passages(job['source'],root,ranges)
    checks=recheck_local(root,rechecks) if rechecks else {'rechecks':[]}
    from reel_engine.detail import make_details
    details=make_details(job['source'],root,ranges)
    evidence=read(Path(verification['verified_passages']))
    selected=[p for p in evidence['passages'] if p['range'] in verification['ranges']]
    attention={'language':read(Path(job['transcript'])).get('language'),
        'passages':[{'range':p['range'],
            'low_confidence_words':[w for w in p['words'] if w.get('confidence',0)<.6],
            'uncertain_speaker_word_ids':[w['id'] for w in p['words'] if w.get('speaker_uncertain') or w.get('overlapping_speech')],
            'asr_reused':p.get('timings',{}).get('full_source_asr_reused',False)} for p in selected],
        'policy':'Batch genuinely unclear speech once; at most two overlapping rechecks before human review. Confidence flags are evidence, not automatic caption edits or identity assignments.'}
    save(root/'speech-attention.json',attention)
    result={'verification':verification,'rechecks':checks,
            'details':{'seconds_this_run':details['seconds_this_run'],'passages':[{k:v for k,v in p.items() if k not in ('frames','page_files')} for p in details['passages']]},
            'seconds_this_run':time.perf_counter()-started,'speech_attention':str((root/'speech-attention.json').resolve()),
            'device':settings.local_device,'note':'Editorial evidence only; no selection, timing replacement, render or publication approval.'}
    save(root/'prepare-report.json',result)
    return result

def batch(manifest,operation,keep_lossless=False):
    """Review/render separate clips in one command; no implicit publishing."""
    manifest=Path(manifest).resolve();items=read(manifest)
    if not isinstance(items,list) or not items:raise ValueError('Batch manifest must be a nonempty list of job/edit records.')
    seen=set();validated=[]
    for item in items:
        ident=item['job'];job_path(ident)
        if ident in seen:raise ValueError('Each clip needs a distinct job ID in the batch.')
        seen.add(ident)
        edit=(manifest.parent/item['edit']).resolve()
        if not edit.is_file() or not job_path(ident).exists():raise ValueError('Batch job or edit file is missing.')
        validated.append((ident,edit))
    started=time.perf_counter();results=[]
    from reel_engine.fast import parallel_budget
    def parallel_safe(item):
        ident,edit_path=item;job=read(job_path(ident))
        revised=bool(job.get('video') and job.get('edit_spec_hash') and job['edit_spec_hash']!=hashlib.sha256(json.dumps(read(edit_path),sort_keys=True).encode()).hexdigest())
        return job.get('fast') and not job.get('keep_lossless') and not revised
    budget=parallel_budget() if all(parallel_safe(item) for item in validated) and not keep_lossless else {'workers':1,'threads_per_clip':None}
    def process(item):
        ident,edit=item
        clock=time.perf_counter()
        try:
            result=review(ident,edit) if operation=='review' else render(ident,edit,keep_lossless=keep_lossless,threads=budget['threads_per_clip'])
            return {'job':ident,'ok':True,'seconds':time.perf_counter()-clock,
                'result':{k:v for k,v in result.items() if k not in ('publishing','config')}}
        except Exception:
            # Details stay in the local exception/job state, never serialize
            # arbitrary provider responses or credentials into the batch report.
            return {'job':ident,'ok':False,'seconds':time.perf_counter()-clock,
                            'error':'Stage failed. Inspect this job and retry its saved stage.'}
    if budget['workers']>1:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=budget['workers']) as pool:results=list(pool.map(process,validated))
    else:results=[process(item) for item in validated]
    report={'operation':operation,'results':results,'seconds':time.perf_counter()-started,
            'all_succeeded':all(r['ok'] for r in results),'publication_authorized':False,'parallel_budget':budget}
    save(manifest.with_name(manifest.stem+'-'+operation+'-report.json'),report)
    return report

def render(ident,edit_path,keep_lossless=False,threads=None):
    job=read(job_path(ident))
    if job.get('fast'):
        from reel_engine.timing import stage
        with stage(STATE,job.get('timing_job',ident),'render_'+ident[-5:],run_id=job.get('run_id')):
            return _render(ident,edit_path,keep_lossless,threads)
    return _render(ident,edit_path,keep_lossless,threads)

def _pre_render_review_guard(job,spec,edit,tracking,root):
    if tracking.get('semantic_review_required') and (tracking.get('confirmed') is not True or tracking.get('unresolved') is not False):
        raise ValueError('Gemini semantic proposal is unreviewed/unresolved. Establish visual evidence before preflight/render; confidence is not approval.')
    from reel_engine.preflight import preflight,crop_review_flags
    from reel_engine.review_policy import register_round,inspection_plan,save_policy
    register_round(root,spec)
    checks=preflight(job['source'],spec,edit,tracking,root,settings.crop_safety_margin)
    job['crop_action_warnings']=checks.get('crop_safety',{}).get('action_summary',[])
    tracking['editorial_warnings']=[*tracking.get('editorial_warnings',[]),*checks.get('editorial_warnings',[])]
    tracking['flagged_output_seconds']=sorted(set(tracking.get('flagged_output_seconds',[])+crop_review_flags(checks)))
    policy=save_policy(root,job,spec,checks);job['review_policy']=policy
    save(root/'job.json',job)
    if not checks['passed']:raise ValueError('Pre-render boundary/crop check failed. Inspect preflight.json; no render started.')
    reviewed=read(root/'review'/'review.json') if (root/'review'/'review.json').exists() else {}
    result=read(root/'review-result.json') if (root/'review-result.json').exists() else {}
    if (result.get('preflight',{}).get('spec_sha256')!=checks['spec_sha256']
        or result.get('review_policy')!=policy or result.get('review_engine_version')!=engine_version()
        or reviewed.get('final_source_sha256')!=job['source_sha256']):
        raise ValueError('Spec or review policy changed. Generate and inspect the current baseline and required scene pages before rendering.')
    if not reviewed or inspection_plan(root,'pre',reviewed['pages'])['required_pages']:
        raise ValueError('Inspect the baseline and all required first-pass pages; later passes inspect changed or flagged pages only.')


def _render(ident,edit_path,keep_lossless=False,threads=None):
    path=job_path(ident);job=read(path);root=path.parent;spec=read(Path(edit_path))
    plan=spec['candidate'];edit,tracking=prepare_edit(job,spec,root)
    _pre_render_review_guard(job,spec,edit,tracking,root)
    version=engine_version()
    edit_spec_hash=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    revised=bool(job.get('video') and job.get('edit_spec_hash') and job['edit_spec_hash']!=edit_spec_hash)
    keep_lossless=keep_lossless or revised or job.get('keep_lossless',False)
    direct=bool((job.get('fast') or settings.render_backend=='direct') and not keep_lossless)
    # Legacy reviewed context-scene jobs remain supported. The new strict
    # contract applies to scene-table plans or explicitly selected direct mode;
    # it must not block the existing fast skip-once caption/context workflow.
    if settings.render_backend=='direct' or (tracking.get('visual_targets') and all(t.get('full_subject_bounds_confirmed') for t in tracking['visual_targets'])):
        from reel_engine.editing_plan import save_plan
        save_plan(root,job,spec,backend='direct' if direct else 'legacy',preset=settings.x264_preset if direct else 'fast')
    from reel_engine.outro import resolve_outro,append_outro
    outro=resolve_outro(spec,STATE/'output-defaults.json')
    signature=hashlib.sha256(json.dumps({'source':job['source_sha256'],'edit':edit,'tracking':tracking,'outro':outro,'engine_version':version,'font':'Creepster','caption_y':1420,'single_pass':direct,'preset':settings.x264_preset if direct else 'fast'},sort_keys=True).encode()).hexdigest()
    if job.get('render_signature')==signature and Path(job.get('video','')).is_file() and digest(Path(job['video']))==job.get('render_sha256'):
        if job.get('fast') and not job.get('publishing') and not job.get('post_id'):
            job['status']='Validation failed' if any(c['status']=='fail' for c in job.get('checks',[])) else 'Needs approval';save(path,job)
        return job
    if job.get('publishing'):raise ValueError('A publication exists for this render. Reconcile it before changing the video.')
    job['status']='Rendering';save(path,job)
    video=root/'reel.mp4'
    body=root/'story.mp4' if outro else video
    from reel_engine.performance import measure
    with measure(root,'render'):
        if direct:
            from reel_engine.fast_render import fast_render_clip
            info=fast_render_clip(job['source'],edit,tracking,body,{'font':'Creepster','caption_y':1420,'x264_preset':settings.x264_preset},threads=threads)
        else:info=render_clip(job['source'],edit,tracking,body,{'font':'Creepster','caption_y':1420})
    validation_started=time.perf_counter()
    checks=validate_render(body,edit,60,tracking,info['caption_events'],minimum=30,render_info=info)
    info['timings']['validation_seconds']=time.perf_counter()-validation_started
    if outro:
        started=time.perf_counter();info['outro']=append_outro(body,video,outro)
        info['timings']['outro_seconds']=time.perf_counter()-started
        checks+=info['outro']['checks']
    save(root/'edit.json',{'candidate':plan,'edit':edit,'tracking':tracking,'render_info':info})
    job.update(status='Validation failed' if any(c['status']=='fail' for c in checks) else 'Needs approval',video=str(video),render_sha256=digest(video),render_signature=signature,engine_version=version,checks=checks,caption=spec.get('caption',''),edit_spec_hash=edit_spec_hash,keep_lossless=bool(keep_lossless),render_mode='single_pass' if direct else 'lossless')
    job['editorial_warnings']=[*job.get('passage_classification',{}).get('editorial_warnings',[]),*tracking.get('editorial_warnings',[])]
    if job.get('fast'):
        job['caption_coverage']=read(root/'skipped-words.json')
    from reel_engine.final_review import sample_final
    job['review_strategy']=job['review_policy']['policy']
    from reel_engine.timing import stage
    with stage(STATE,job.get('timing_job',ident),'final_sampling_'+ident[-5:],run_id=job.get('run_id')) as interval:
        job['final_mp4_review']=sample_final(video,edit,tracking,root)
        interval['cached']=job['final_mp4_review']['cache_reused']
    job.pop('approval',None);save(path,job);return job
def publish(ident,confirmed=False):
    path=job_path(ident);job=read(path)
    if job.get('post_id'):return job
    if not confirmed:raise ValueError('Use --confirmed only after the user says “good to go” for this exact render.')
    if job.get('status') not in ('Needs approval','Publishing') or any(c['status']=='fail' for c in job.get('checks',[])) or not job.get('checks'):raise ValueError('Render and resolve failed checks before publishing.')
    if digest(Path(job['video']))!=job['render_sha256']:raise ValueError('Video changed after validation. Render and review again.')
    if not settings.zernio_instagram_id:raise ValueError('Set ZERNIO_INSTAGRAM_ID to the connected Zernio Instagram account ID.')
    record=job.get('publishing')
    if record and record['account_id']!=settings.zernio_instagram_id:raise ValueError('Account changed; reconcile the existing publication.')
    job['approval']={'command':'good to go','at':time.time(),'render_sha256':job['render_sha256']};save(path,job)
    if not record:
        signed=publishing.request('POST','/media/presign',payload={'filename':'reel.mp4','contentType':'video/mp4','size':Path(job['video']).stat().st_size})
        if not signed['uploadUrl'].startswith('https://') or not signed['publicUrl'].startswith('https://'):raise ValueError('Invalid upload URL.')
        with Path(job['video']).open('rb') as f:
            response=httpx.put(signed['uploadUrl'],content=f,headers={'Content-Type':'video/mp4'},timeout=600);response.raise_for_status()
        payload={'content':job['caption'],'mediaItems':[{'type':'video','url':signed['publicUrl']}],'platforms':[{'platform':'instagram','accountId':settings.zernio_instagram_id,'platformSpecificData':{'shareToFeed':True}}],'publishNow':True}
        record={'account_id':settings.zernio_instagram_id,'started':time.time(),'payload':payload,'key':'codex-reel-'+job['render_sha256']}
        job.update(publishing=record,status='Publishing');save(path,job)
    if not record.get('provider_post_id'):
        if time.time()-record['started']>23*3600:raise ValueError('Safe retry window expired. Reconcile the original Zernio post; do not resubmit.')
        result=publishing.request('POST','/posts',payload=record['payload'],key=record['key'])
        post_id=result.get('post',{}).get('_id') or result.get('postId')
        if not post_id:raise ValueError('Provider returned no post ID; saved idempotency key retained.')
        record['provider_post_id']=str(post_id);save(path,job)
    result=publishing.request('GET','/posts/'+record['provider_post_id']);post=result.get('post',{})
    target=next((p for p in post.get('platforms',[]) if p.get('platform')=='instagram' and str(p.get('accountId',{}).get('_id') if isinstance(p.get('accountId'),dict) else p.get('accountId'))==record['account_id']),None)
    if not target:raise ValueError('Instagram target not confirmed in provider response.')
    if target.get('status')=='published' and target.get('platformPostId'):
        job.update(status='Published',post_id=str(target['platformPostId']),permalink=target.get('platformPostUrl'));save(path,job)
    elif target.get('status') in ('failed','cancelled'):raise ValueError('Publication failed. Correct or retry the existing post in Zernio; do not create a new one.')
    return job
def main():
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr,"reconfigure"):sys.stderr.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('connect');p.add_argument('channel')
    p=sub.add_parser('onboarding');p.add_argument('--channel',required=True);p.add_argument('--from-env',action='store_true',help='Read credentials privately from .env instead of terminal prompts.')
    p=sub.add_parser('prepare-models');p.add_argument('--download',action='store_true',help='Authorize one-time local model downloads; later runs use cached models offline.')
    p=sub.add_parser('analyze');group=p.add_mutually_exclusive_group();group.add_argument('--url');group.add_argument('--file');p.add_argument('--clips',type=int,help='Requested clip count; Codex reports fewer when the source lacks strong complete moments.');p.add_argument('--full-local',action='store_true',help='Use full local transcription when the YouTube draft is unreliable.')
    p.add_argument('--sections',action='store_true',help='Explicit alias for default proxy/selected-section preparation.');p.add_argument('--full-source',action='store_true',help='Explicit recovery: download whole highest-quality YouTube source before selection.');p.add_argument('--fast',action='store_true');p.add_argument('--fresh',action='store_true');p.add_argument('--stop-on-fast-rejection',action='store_true');p.add_argument('--fresh-captions',action='store_true');p.add_argument('--caption-attempts',type=int,default=4);p.add_argument('--cookies-from-browser',default=None)
    p=sub.add_parser('captions');p.add_argument('--url',required=True);p.add_argument('--fresh-captions',action='store_true');p.add_argument('--caption-attempts',type=int,default=4);p.add_argument('--cookies-from-browser',default=None)
    p=sub.add_parser('draft');p.add_argument('--url');p.add_argument('--clips',type=int)
    p=sub.add_parser('render');p.add_argument('job');p.add_argument('--edit',required=True)
    p.add_argument('--keep-lossless',action='store_true')
    p=sub.add_parser('review');p.add_argument('job');p.add_argument('--edit',required=True)
    for command in ('review-batch','render-batch'):
        p=sub.add_parser(command);p.add_argument('--manifest',required=True,help='JSON list of distinct job/edit records. Paths relative to manifest.')
        p.add_argument('--keep-lossless',action='store_true')
    p=sub.add_parser('recheck');p.add_argument('job');p.add_argument('--force',action='store_true',help='Explicitly override the two overlapping recheck limit.');p.add_argument('--range',action='append',required=True,help='Source seconds START:END; repeat for multiple passages.')
    p=sub.add_parser('verify');p.add_argument('job');p.add_argument('--range',action='append',required=True,help='Selected passage plus surrounding context in source seconds START:END. Repeat to batch clips.')
    p=sub.add_parser('overview');p.add_argument('job');p.add_argument('--interval',type=float,default=12)
    p=sub.add_parser('prepare');p.add_argument('job');p.add_argument('--range',action='append',required=True);p.add_argument('--recheck-range',action='append',default=[])
    p=sub.add_parser('align');p.add_argument('job');p.add_argument('--manifest',required=True,help='JSON passages with source range, exact reviewed text and wording evidence; local audio supplies timings.')
    p=sub.add_parser('scene-build');p.add_argument('--base',required=True);p.add_argument('--table',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('review-inspect');p.add_argument('job');p.add_argument('--phase',choices=('pre','final'),required=True);p.add_argument('--page',action='append',required=True)
    p=sub.add_parser('preflight');p.add_argument('job');p.add_argument('--edit',required=True);p.add_argument('--snap',action='store_true')
    p=sub.add_parser('publish');p.add_argument('job');p.add_argument('--confirmed',action='store_true')
    p=sub.add_parser('status');p.add_argument('job')
    p=sub.add_parser('stage-mark');p.add_argument('job');p.add_argument('stage');p.add_argument('--event',choices=('start','end'),required=True);p.add_argument('--run-id');p.add_argument('--cached',action='store_true')
    p=sub.add_parser('timing-report');p.add_argument('job');p.add_argument('--run-id')
    p=sub.add_parser('phase');p.add_argument('job');p.add_argument('phase',choices=('selection_reading','scene_planning','spec_writing','review_pass','correction','final_inspection'));p.add_argument('--event',choices=('start','end'),required=True);p.add_argument('--round',type=int,default=1);p.add_argument('--run-id')
    p=sub.add_parser('fast-gate');p.add_argument('job');p.add_argument('--evidence',required=True)
    p=sub.add_parser('fast-prepare');p.add_argument('job');p.add_argument('--selection',required=True)
    p=sub.add_parser('fast-details');p.add_argument('job');p.add_argument('--selection',required=True)
    p=sub.add_parser('plan-check');p.add_argument('job');p.add_argument('--edit',required=True)
    p=sub.add_parser('semantic-plan');p.add_argument('job');p.add_argument('--base',required=True);p.add_argument('--details',required=True);p.add_argument('--estimate-only',action='store_true',help='Local frame/coverage/token admission estimate; no HTTP requests.');p.add_argument('--authorize-gemini',action='store_true',help='Explicitly authorize a bounded free-project semantic request; management checks still required.')
    p=sub.add_parser('gemini-verify');p.add_argument('--confirm-free-tier',action='store_true',help='Confirm AI Studio Free plan/model/quotas. Read-only management checks; no Gemini inference.')
    sub.add_parser('gemini-models',help='Read-only ListModels discovery; never selects a model or generates content.')
    p=sub.add_parser('doctor')
    p=sub.add_parser('performance-report');p.add_argument('job')
    args=parser.parse_args();STATE.mkdir(exist_ok=True)
    if getattr(args,'cookies_from_browser',None) is not None:settings.youtube_cookies_from_browser=args.cookies_from_browser
    # Timing marks must remain usable while a download/verification CLI holds the workflow lock.
    if args.command in ('stage-mark','timing-report','phase'):
        from reel_engine.timing import mark,report,table
        phase_command_started=time.time()
        job_path(args.job)
        if args.command=='phase':
            from reel_engine.timing import interactive_phase
            phase_result=interactive_phase(STATE,args.job,args.phase,args.event,round_number=args.round,run_id=args.run_id)
            print(json.dumps(phase_result))
            # Phase commands used to return before CLI/gap coverage, leaving
            # command-end -> next phase-start time unattributed. Record only
            # actual current endpoints, never infer historical activity.
            from reel_engine.timing import record_command_coverage
            record_command_coverage(STATE,phase_result['job'],'phase',phase_command_started,time.time(),True)
        elif args.command=='stage-mark':print(json.dumps(mark(STATE,args.job,args.stage,args.event,run_id=args.run_id,cached=args.cached)))
        else:
            data=report(STATE,args.job,args.run_id);save(job_path(args.job).parent/'timing-report.json',data);print(table(data))
        return
    import msvcrt
    with (STATE/'.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('Another local workflow command is running.')
        try:
            command_started=time.perf_counter();wall_started=time.time();succeeded=False
            if args.command=='doctor':
                from reel_engine.doctor import check
                result=check(ROOT,settings)
            elif args.command=='performance-report':
                from reel_engine.performance import summarize
                result=summarize(job_path(args.job).parent)
            elif args.command=='gemini-verify':
                from reel_engine.gemini_free import verify_free_project
                if not args.confirm_free_tier:raise ValueError('Confirm the exact key project/model shows Free and active limits in AI Studio; then --confirm-free-tier.')
                settings.gemini_free_tier_confirmed=True
                result=verify_free_project(settings)
                save(STATE/'gemini-free-tier-verification.json',result)
            elif args.command=='gemini-models':
                from reel_engine.gemini_free import list_models
                result=list_models(settings)
                save(STATE/'gemini-model-discovery.json',result)
            elif args.command=='plan-check':
                from reel_engine.editing_plan import save_plan
                result=save_plan(job_path(args.job).parent,read(job_path(args.job)),read(Path(args.edit)),backend=settings.render_backend,preset=settings.x264_preset)
            elif args.command=='semantic-plan':
                from reel_engine.semantic_analysis import analyze as semantic_analyze
                from reel_engine.timing import stage
                job=read(job_path(args.job));details=read(Path(args.details));base=read(Path(args.base))
                if 'passages' in details:
                    details=next(p for p in details['passages'] if p['range'][0]<=base['candidate']['start'] and base['candidate']['end']<=p['range'][1])
                a,b=base['candidate']['start'],base['candidate']['end']
                details={**details,'frames':[f for f in details['frames'] if a<=f['source_seconds']<=b],
                         'source_width':job.get('metadata',{}).get('width'),'source_height':job.get('metadata',{}).get('height')}
                selected_transcript={'words':[{k:w.get(k) for k in ('start','end','text','speaker')} for w in base['words']],
                                     'source_time':True,'wording_is_not_a_visual_identity':True}
                if args.estimate_only:
                    from reel_engine.semantic_frames import estimate
                    from reel_engine.gemini_free import generation_config,semantic_prompt
                    result=estimate(details,selected_transcript,generation_config(settings.gemini_model,settings.gemini_max_output_tokens),settings.gemini_frame_strategy,
                                    prompt=semantic_prompt(base,details,selected_transcript,settings.gemini_model))
                    save(job_path(args.job).parent/('semantic-estimate-'+settings.gemini_frame_strategy+'.json'),result)
                    print(json.dumps(result,indent=2));succeeded=True;return
                with stage(STATE,job.get('timing_job',args.job),'gemini_semantic_analysis',run_id=job.get('run_id')) as interval:
                    result=semantic_analyze(base,details,selected_transcript,job_path(args.job).parent,settings=settings,authorized=args.authorize_gemini)
                    from reel_engine.gemini_free import stage_result
                    interval.update(stage_result(result))
                result={k:v for k,v in result.items() if k!='proposal'}
            elif args.command=='connect':result=connect(args.channel)
            elif args.command=='onboarding':
                from reel_engine.onboarding import onboard
                result=onboard(ROOT,args.channel,connect,args.from_env)
            elif args.command=='scene-build':
                from reel_engine.scene_table import load_table,build_spec,SceneTable
                result=build_spec(read(Path(args.base)),load_table(args.table),settings.scene_pan_threshold,settings.min_subject_width_fraction)
                save(Path(args.output),result);save(Path(args.output).with_name('scene-table.schema.json'),SceneTable.model_json_schema())
                result={'spec':str(Path(args.output).resolve()),'schema':str(Path(args.output).with_name('scene-table.schema.json').resolve())}
            elif args.command=='review-inspect':
                from reel_engine.review_policy import record_inspection
                root=job_path(args.job).parent;folder=root/('review' if args.phase=='pre' else 'final-mp4-review');reviewed=read(folder/'review.json')
                pages=[str(Path(p).resolve()) for p in args.page]
                if any(p not in reviewed['pages'] or digest(Path(p))!=reviewed['page_hashes'][p] for p in pages):raise ValueError('Page is not in the current hash-bound review')
                record_inspection(root,args.phase,pages)
                if args.phase=='final':
                    frames=list(reviewed.get('frame_pixel_hashes',{}))
                    selected=[f for i,p in enumerate(reviewed['pages']) if p in pages for f in frames[i*12:i*12+12]]
                    record_inspection(root,'final_frames',selected)
                result={'inspected_pages':pages,'publication_approved':False}
            elif args.command=='preflight':
                from reel_engine.preflight import snap_spec,preflight
                job=read(job_path(args.job));root=job_path(args.job).parent;spec=read(Path(args.edit))
                if args.snap:
                    spec=snap_spec(job['source'],spec,root);save(Path(args.edit),spec)
                edit,tracking=prepare_edit(job,spec,root)
                result=preflight(job['source'],spec,edit,tracking,root,settings.crop_safety_margin)
            elif args.command=='prepare-models':
                from reel_engine.local_transcription import load_models
                load_models(allow_download=args.download)
                result={'local_models_ready':True,'provider':'local','device':settings.local_device,'whisper_model':settings.whisper_model}
            elif args.command=='analyze':
                if use_section_preparation(args.file,args.full_local,args.full_source):
                    from reel_engine.fast import analyze_fast
                    pinned=args.url or 'https://www.youtube.com/watch?v='+latest()[0]
                    result=analyze_fast(STATE,pinned,args.clips,fresh=args.fresh,stop_on_rejection=args.stop_on_fast_rejection,normal_analyze=analyze,fresh_captions=args.fresh_captions,caption_max_attempts=args.caption_attempts,careful_sections=not args.fast)
                else:
                    if args.fast or args.sections:print('Fast mode is for original-caption YouTube footage; using the normal pipeline.',flush=True)
                    result=analyze(args.url,args.file,args.clips,args.full_local)
            elif args.command=='captions':
                from reel_engine.original_captions import fetch_uploaded_captions
                from reel_engine.caption_errors import CaptionFetchError
                from reel_engine.timing import stage
                import uuid
                ident=youtube.video_id(args.url)+'-captions-'+uuid.uuid4().hex[:8];root=job_path(ident).parent;root.mkdir(parents=True)
                run=uuid.uuid4().hex;result={'id':ident,'run_id':run,'status':'Fetching uploaded captions','fresh_captions':args.fresh_captions}
                save(root/'job.json',result)
                with stage(STATE,ident,'caption_workflow',run_id=run) as workflow_timing:
                    with stage(STATE,ident,'metadata',run_id=run):info=json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',args.url]))
                    try:
                        data=fetch_uploaded_captions(info['id'],root,info['duration'],info,timing_hook=lambda name:stage(STATE,ident,name,run_id=run),fresh_captions=args.fresh_captions,max_attempts=args.caption_attempts)
                        result.update(status='Uploaded captions ready',cached=data['caption_cached'],caption_cache=data['caption_cache'],transcript=str((root/'uploaded-transcript.json').resolve()))
                    except CaptionFetchError as exc:
                        result.update(status='Caption fetch needs recovery' if not exc.diagnostic['content_rejection'] else 'Caption content rejected',error=str(exc),caption_failure=exc.diagnostic,cached=False)
                        workflow_timing.update(outcome='failed',diagnostic=exc.diagnostic)
                    save(root/'job.json',result)
            elif args.command=='draft':result=draft(args.url,args.clips)
            elif args.command=='render':result=render(args.job,args.edit,keep_lossless=args.keep_lossless)
            elif args.command=='review':result=review(args.job,args.edit)
            elif args.command in ('review-batch','render-batch'):result=batch(args.manifest,args.command.split('-')[0],keep_lossless=args.keep_lossless)
            elif args.command=='fast-gate':
                from reel_engine.fast import gate
                result=gate(STATE,read(job_path(args.job)),args.evidence,normal_analyze=analyze)
            elif args.command=='fast-prepare':
                from reel_engine.fast import prepare_selected
                result=prepare_selected(STATE,read(job_path(args.job)),args.selection,normal_analyze=analyze)
            elif args.command=='fast-details':
                from reel_engine.detail import make_details
                job=read(job_path(args.job));selection=read(Path(args.selection))
                cues=read(Path(job['transcript'])).get('cues',[]) if job.get('transcript') else []
                result=make_details(job['source'],job_path(args.job).parent,[(c['start'],c['end']) for c in selection['candidates']],
                    adaptive=settings.adaptive_details,mode=settings.processing_mode,context_times=[c['start'] for c in cues])
                save(job_path(args.job).parent/'selected-details.json',result)
            elif args.command=='overview':
                from reel_engine.overview import make_overview
                path=job_path(args.job);job=read(path)
                report=make_overview(job['source'],path.parent,args.interval)
                result={k:v for k,v in report.items() if k not in ('frames','page_files')}
            elif args.command=='prepare':
                ranges=[tuple(map(float,value.split(':'))) for value in args.range]
                checks=[tuple(map(float,value.split(':'))) for value in args.recheck_range]
                if any(len(pair)!=2 for pair in ranges+checks):raise ValueError('Use START:END for each passage.')
                result=prepare(args.job,ranges,checks)
            elif args.command=='verify':
                from reel_engine.local_transcription import verify_passages
                path=job_path(args.job);job=read(path)
                if job.get('fast'):
                    raise ValueError('Fast mode uses one fast-prepare batch for changed boundaries; reuse saved verified words otherwise.')
                ranges=[tuple(map(float,value.split(':'))) for value in args.range]
                if any(len(pair)!=2 for pair in ranges):raise ValueError('Use START:END for each verified range.')
                result=verify_passages(job['source'],Path(job['transcript']).parent,ranges)
            elif args.command=='recheck':
                from reel_engine.local_transcription import recheck_local
                ranges=[tuple(map(float,value.split(':'))) for value in args.range]
                if any(len(pair)!=2 for pair in ranges):raise ValueError('Use START:END for each recheck range.')
                job=read(job_path(args.job))
                from reel_engine.fast_captions import require_no_speech_retry
                require_no_speech_retry(job)
                if job.get('fast'):
                    from reel_engine.fast import check_recheck_ranges
                    check_recheck_ranges(Path(job['transcript']).parent,ranges)
                # Mapped proxy evidence does not create child audio in either mode.
                from reel_engine.local_transcription import ensure_recheck_audio
                from reel_engine.timing import stage
                with stage(STATE,job.get('timing_job',args.job),'recheck_audio_preparation',run_id=job.get('run_id')):
                    ensure_recheck_audio(job,Path(job['transcript']).parent)
                result=recheck_local(Path(job['transcript']).parent,ranges,force=args.force)
            elif args.command=='align':
                from reel_engine.alignment import align_passages
                job=read(job_path(args.job))
                from reel_engine.fast_captions import require_no_speech_retry
                require_no_speech_retry(job)
                result=align_passages(Path(job['transcript']).parent,args.manifest)
            elif args.command=='publish':result=publish(args.job,args.confirmed)
            else:result=read(job_path(args.job))
            # Do not expose signed upload URLs or provider payloads in chat.
            succeeded=True
            print(json.dumps({k:v for k,v in result.items() if k not in ('publishing','config')},ensure_ascii=False,indent=2))
        except httpx.HTTPError:raise SystemExit('Network or upload request failed. Retry the saved stage; signed URLs are not printed.') from None
        except Exception as exc:raise SystemExit(str(exc)) from None
        finally:
            try:
                # Only an allow-listed command name/job identifier is logged.
                # Never log argument values, channel URLs, keys or API payloads.
                with (STATE/'command-timings.jsonl').open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps({'command':args.command,'job':getattr(args,'job',None),
                        'started':wall_started,'seconds':time.perf_counter()-command_started,'succeeded':succeeded})+'\n')
            finally:
                try:
                    from reel_engine.timing import record_command_coverage
                    ident=getattr(args,'job',None) or (result.get('id') if isinstance(locals().get('result'),dict) else None)
                    identifiers={ident} if ident else set()
                    if succeeded and args.command in ('review-batch','render-batch'):
                        for entry in read(Path(args.manifest)):
                            identifiers.add(entry['job'])
                    for identifier in list(identifiers):
                        path=job_path(identifier)
                        if path.exists():
                            parent=read(path).get('source_job_id')
                            if parent:identifiers.add(parent)
                    for identifier in identifiers:
                        record_command_coverage(STATE,identifier,args.command,wall_started,time.time(),succeeded)
                finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':main()
