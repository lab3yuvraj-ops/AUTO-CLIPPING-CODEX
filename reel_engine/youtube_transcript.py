"""Original-language YouTube captions for editorial selection, never final word timing."""
import json, math, re, time, http.cookiejar
import httpx
from pathlib import Path
from . import youtube


def atomic_json(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def parse_json3(data, duration, require_coverage=True):
    cues=[]
    for event in data.get('events',[]):
        text=' '.join(''.join(s.get('utf8','') for s in event.get('segs',[])).split())
        if not text:continue
        start=float(event.get('tStartMs',0))/1000
        end=start+float(event.get('dDurationMs',0))/1000
        if not math.isfinite(start+end) or not 0<=start<end:continue
        if start>=duration:continue
        cue={'id':len(cues),'start':start,'end':min(end,duration),'text':text,
             'timing_precision':'caption cue, not verified spoken-word timing'}
        # Some rolling caption tracks duplicate the same update at one timestamp.
        if cues and all(cues[-1][k]==cue[k] for k in ('start','end','text')):continue
        cues.append(cue)
    cues.sort(key=lambda c:c['start'])
    for i,c in enumerate(cues):c['id']=i
    count=sum(len(c['text'].split()) for c in cues)
    if not require_coverage:
        return {'provider':'partial-uploaded-captions','language':data.get('language','original'),
                'cues':cues,'words':[], 'text':' '.join(c['text'] for c in cues),
                'requires_selected_verification':True,'warning':'Partial cue text is audit context only, never word timing or caption fallback.'}
    if count<30 or not cues or cues[-1]['end']<duration*.8:
        raise ValueError('Caption coverage is insufficient for whole-source selection.')
    # A long unsupported region needs full local transcription, not guessed content.
    covered=0
    for cue in cues:
        if cue['start']-covered>45:raise ValueError('Caption track has a substantial coverage gap.')
        covered=max(covered,cue['end'])
    if duration-covered>45:raise ValueError('Caption track is missing the source ending.')
    return {'provider':'youtube-captions','language':data.get('language','original'),
            'cues':cues,'words':[], 'text':' '.join(c['text'] for c in cues),
            'requires_selected_verification':True,
            'warning':'YouTube captions are draft editorial evidence. Inspect whole-source frames, verify selected speech locally and reassess selections when wording changes.'}


def fetch_caption_draft(ident, root, duration, info=None,require_uploaded=False,timing_hook=None,fresh_captions=False,max_attempts=4,on_failure=None,stop_wait=None):
    """Do not repeat a failed draft fetch immediately after a download."""
    if require_uploaded:
        from .original_captions import fetch_uploaded_captions
        return fetch_uploaded_captions(ident,root,duration,info,timing_hook,fresh_captions=fresh_captions,max_attempts=max_attempts,on_failure=on_failure,stop_wait=stop_wait)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    draft=root/'youtube-transcript.json';failure=root/'caption-fetch-failure.json'
    if draft.exists() and json.loads(draft.read_text(encoding='utf-8')).get('video_id')==ident:
        return json.loads(draft.read_text(encoding='utf-8'))
    if failure.exists():
        saved=json.loads(failure.read_text(encoding='utf-8'))
        if saved.get('video_id')==ident and time.time()<saved.get('retry_after',0):
            raise ValueError('Original captions recently failed. Use local transcription; caption fetch may be retried after the saved cooldown.')
    try:
        result=_fetch_caption_draft(ident,root,duration,info)
    except Exception:
        atomic_json(failure,{'video_id':ident,'retry_after':time.time()+900,
            'reason':'Caption fetch failed or coverage was insufficient; no provider payload saved.'})
        raise
    if failure.exists():failure.unlink()
    return result


def _fetch_caption_draft(ident, root, duration, info=None):
    """Bounded fetch; callers may fall back to local ASR. Never persist signed URLs."""
    root=Path(root);started=time.perf_counter();draft=root/'youtube-transcript.json'
    if draft.exists():
        cached=json.loads(draft.read_text(encoding='utf-8'))
        if cached.get('video_id')==ident:return cached
    if info is None:
        info=json.loads(youtube.ytdlp(['--skip-download','--dump-single-json',f'https://www.youtube.com/watch?v={ident}'],timeout=90))
    automatic=info.get('automatic_captions',{})
    originals=[k for k in automatic if k.endswith('-orig')]
    native=(info.get('language') or '').split('-')[0]
    language=next((k for k in originals if native and k.split('-')[0]==native),
                  next((k for k in originals if k.startswith('hi')),next(iter(originals),None)))
    if not language:raise ValueError('No original automatic caption track available.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',language):raise ValueError('Unsupported caption language identifier.')
    raw=root/f'youtube-captions.{language}.json3'
    if not raw.exists():
        track=next((t for t in automatic[language] if t.get('ext')=='json3' and t.get('url')),None)
        if track:
            # Reuse the extractor's URL immediately; avoid a second slow extraction.
            # URLs and cookies remain in memory and are never persisted or printed.
            from .config import settings
            jar=http.cookiejar.MozillaCookieJar()
            if settings.youtube_cookie_file:
                jar=http.cookiejar.MozillaCookieJar(settings.youtube_cookie_file)
                jar.load(ignore_discard=True,ignore_expires=True)
            try:
                with httpx.Client(cookies=jar,timeout=20,follow_redirects=True) as client:
                    response=client.get(track['url'],headers=info.get('http_headers',{}))
                if response.status_code==200:
                    body=response.json()
                    if body.get('events'):atomic_json(raw,body)
            except (httpx.HTTPError,ValueError):pass
        if not raw.exists():
            youtube.ytdlp(['--skip-download','--write-auto-subs','--sub-langs',language,'--sub-format','json3',
                          '--retries','1','-o',str(root/'youtube-captions.%(ext)s'),f'https://www.youtube.com/watch?v={ident}'],timeout=90)
    data=json.loads(raw.read_text(encoding='utf-8'));data['language']=language
    result=parse_json3(data,duration)
    result.update(video_id=ident,seconds_this_run=time.perf_counter()-started,raw_caption_file=str(raw.resolve()))
    atomic_json(draft,result)
    return result


def transcript_for_selection(source,root,ident=None,force_local=False):
    from .local_transcription import transcribe_local
    root=Path(root);existing=root/'transcript.json'
    if existing.exists():
        cached=json.loads(existing.read_text(encoding='utf-8'))
        if not force_local or cached.get('provider')!='youtube-captions':
            return {'transcript':str(existing.resolve()),'transcription_timings':{'checkpoint_reused':True}}
    if ident and not force_local:
        try:
            from .render import probe
            result=fetch_caption_draft(ident,root,float(probe(source)['format']['duration']))
            atomic_json(existing,result)
            return {'transcript':str(existing.resolve()),'transcription_timings':{
                'provider':'youtube-captions','seconds_this_run':result['seconds_this_run'],
                'selected_speech_verification_required':True}}
        except Exception:
            # Preserve a useful recovery message without provider payloads or cookie paths.
            atomic_json(root/'caption-fallback.json',{'reason':'Original YouTube captions unavailable, challenged, malformed or insufficient. Using full local transcription.'})
    # Preserve any previous caption draft when explicitly upgrading to full local ASR.
    if existing.exists() and json.loads(existing.read_text(encoding='utf-8')).get('provider')=='youtube-captions':
        existing.replace(root/'youtube-transcript.json')
    return transcribe_local(source,root)


def require_verified_words(job,spec):
    """A draft cannot silently supply cue-derived highlighting or guessed speaker labels."""
    transcript=Path(job['transcript']) if job.get('transcript') else None
    if not transcript or not transcript.exists():return
    if json.loads(transcript.read_text(encoding='utf-8')).get('provider') not in ('youtube-captions','local-asr-draft','local-selection-draft'):return
    evidence=transcript.parent/'verified-passages.json'
    if not evidence.exists():raise ValueError('Run reel.py verify JOB_ID --range START:END before editing a YouTube-caption draft.')
    verified=json.loads(evidence.read_text(encoding='utf-8'))
    if verified['source_sha256']!=job['source_sha256']:raise ValueError('Verified speech belongs to a different source.')
    a,b=spec['candidate']['start'],spec['candidate']['end']
    passages=[p for p in verified['passages'] if p['range'][0]<=a and b<=p['range'][1]]
    if not passages:raise ValueError('Selected story is outside the locally verified passage. Verify its complete range.')
    for word in spec['words']:
        matched=False
        for passage in passages:
            lookup={w['id']:w for w in passage['words']}
            ids=word.get('source_word_ids') or [word['id']]
            if ids and all(i in lookup for i in ids):
                originals=[lookup[i] for i in ids]
                if abs(word['start']-min(w['start'] for w in originals))<.03 and abs(word['end']-max(w['end'] for w in originals))<.03:
                    matched=True;break
        if not matched:raise ValueError('Caption word timing must align to locally verified word IDs; cue-level timing cannot be rendered.')
