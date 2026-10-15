"""Strict uploaded native-language captions; never substitute automatic ASR."""
import json
import time
from pathlib import Path
from contextlib import nullcontext
from . import youtube
from .caption_errors import CaptionFetchError,classify_caption_failure
from .youtube_transcript import atomic_json,parse_json3


def uploaded_language(info):
    uploaded=info.get('subtitles',{})
    if not uploaded:raise CaptionFetchError(classify_caption_failure('No original uploaded captions exist.'))
    native=(info.get('language') or '').split('-')[0]
    if not native:
        originals=[k[:-5] for k in info.get('automatic_captions',{}) if k.endswith('-orig')]
        native=originals[0] if len(originals)==1 else None
    if not native or native not in uploaded:
        raise CaptionFetchError(classify_caption_failure('Original uploaded caption language is unavailable or ambiguous.',language=native))
    if not any(t.get('ext')=='json3' for t in uploaded[native]):
        raise CaptionFetchError(classify_caption_failure('Uploaded native track lacks json3 format.',language=native))
    return native


def retry_delay(diagnostic, attempt, now=None):
    import email.utils
    import datetime
    value=diagnostic.get('retry_after')
    if value is not None:
        try:return max(0,float(value))
        except (ValueError,TypeError):
            try:return max(0,email.utils.parsedate_to_datetime(value).timestamp()-(time.time() if now is None else now))
            except (ValueError,TypeError,OverflowError):pass
    return (60.,180.,600.)[min(attempt-1,2)]


def fetch_uploaded_captions(ident,root,duration,info=None,timing_hook=None,sleep=time.sleep,*,fresh_captions=False,cache_dir=None,max_attempts=4,wait_cap=None,on_failure=None,stop_wait=None):
    import hashlib
    import re
    from datetime import datetime,timezone
    from .config import settings
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ident):raise ValueError('Invalid caption video ID.')
    if not 1<=max_attempts<=4:raise ValueError('Caption attempts must be between one and four.')
    cap=settings.caption_retry_wait_cap_seconds if wait_cap is None else float(wait_cap)
    if not 0<=cap<=3600:raise ValueError('Caption total wait cap must be 0–3600 seconds.')
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    cache=Path(cache_dir or settings.caption_cache_dir)/ident;record=cache/'record.json';payload=cache/'uploaded.json3'
    draft=root/'uploaded-transcript.json';failure=root/'caption-fetch-failure.json'
    # The root is the run boundary: repeated invocation must not refetch this ID.
    receipt=root/'caption-request.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        if saved.get('video_id')==ident:
            if saved.get('failure'):raise CaptionFetchError(saved['failure'])
            if draft.exists():return json.loads(draft.read_text(encoding='utf-8'))
    if not fresh_captions and record.exists() and payload.exists():
        saved=json.loads(record.read_text());raw=payload.read_bytes()
        if saved.get('caption_kind')=='uploaded' and saved.get('format')=='json3' and saved.get('video_id')==ident and saved.get('source_duration')==float(duration) and saved.get('sha256')==hashlib.sha256(raw).hexdigest():
            with timing_hook('caption_cache_hit') if timing_hook else nullcontext() as timing:
                if timing is not None:timing['cached']=True
                body=json.loads(raw);body['language']=saved['language'];data=parse_json3(body,duration)
                data.update(video_id=ident,caption_kind='uploaded',requested_language=saved['language'],caption_cached=True,caption_cache=saved,caption_fetch_attempts=[])
                atomic_json(draft,data);atomic_json(receipt,{'video_id':ident,'cached':True})
                return data
    language=None;attempts=[];waited=0.
    try:
        if info is None:info=json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',f'https://www.youtube.com/watch?v={ident}']))
        language=uploaded_language(info)
        for attempt in range(1,max_attempts+1):
            try:
                with timing_hook(f'caption_attempt_{attempt}') if timing_hook else nullcontext():
                    # Same metadata pass supplies both track inventory and its signed download URL.
                    try:
                        youtube.ytdlp(['--skip-download','--write-subs','--no-write-auto-subs','--sub-langs',language,'--sub-format','json3','--retries','0','--extractor-retries','0','-o',str(root/'uploaded-captions.%(ext)s')],metadata_input=info)
                    except Exception as exc:
                        raise CaptionFetchError(classify_caption_failure(getattr(exc,'diagnostic',{}).get('yt_dlp_message',str(exc)),language=language)) from None
                    raw=root/f'uploaded-captions.{language}.json3'
                    if not raw.exists():raise ValueError('Uploaded caption language/format was listed but no file was returned.')
                    body=json.loads(raw.read_text(encoding='utf-8'));body['language']=language
                    data=parse_json3(body,duration)
                attempts.append({'attempt':attempt,'outcome':'success'})
                raw_bytes=raw.read_bytes();cache.mkdir(parents=True,exist_ok=True)
                temporary=payload.with_suffix('.tmp');temporary.write_bytes(raw_bytes);temporary.replace(payload)
                cached={'video_id':ident,'caption_kind':'uploaded','language':language,'format':'json3','fetched_at':time.time(),'source_duration':float(duration),'sha256':hashlib.sha256(raw_bytes).hexdigest()}
                atomic_json(record,cached)
                data.update(video_id=ident,caption_kind='uploaded',requested_language=language,caption_cached=False,caption_cache=cached,caption_fetch_attempts=attempts,raw_caption_file=str(raw.resolve()))
                atomic_json(draft,data);atomic_json(receipt,{'video_id':ident,'cached':False})
                if failure.exists():failure.unlink()
                return data
            except Exception as exc:
                diag=exc.diagnostic if isinstance(exc,CaptionFetchError) else classify_caption_failure(getattr(exc,'diagnostic',{}).get('yt_dlp_message',str(exc)),language=language)
                attempts.append({'attempt':attempt,'outcome':'failed',**diag})
                delay=retry_delay(diag,attempt)
                diag.update(attempt_count=attempt,suggested_retry_at=datetime.fromtimestamp(time.time()+delay,timezone.utc).isoformat())
                if on_failure:on_failure(diag)
                atomic_json(root/'caption-fetch-attempts.json',{'attempts':attempts})
                if not diag['transient'] or attempt==max_attempts or waited+delay>cap:
                    diag['wait_cap_seconds']=cap;diag['waited_seconds']=waited
                    raise CaptionFetchError({**diag,'attempts':attempts}) from None
                attempts[-1]['backoff_seconds']=delay
                with timing_hook(f'caption_backoff_{attempt}') if timing_hook else nullcontext():
                    # Short sleep chunks keep cancellation responsive; never shorten Retry-After.
                    remaining=delay
                    while remaining>0:
                        if stop_wait and stop_wait.is_set():
                            diag['retry_cancelled']='Local ASR completed; pending caption retry is not needed.'
                            raise CaptionFetchError({**diag,'attempts':attempts})
                        amount=min(1 if stop_wait else 30,remaining);sleep(amount);remaining-=amount
                waited+=delay
    except Exception as exc:
        diag=exc.diagnostic if isinstance(exc,CaptionFetchError) else classify_caption_failure(getattr(exc,'diagnostic',{}).get('yt_dlp_message',str(exc)),language=language)
        atomic_json(failure,{'video_id':ident,**diag,'attempts':attempts});atomic_json(receipt,{'video_id':ident,'failure':diag})
        raise CaptionFetchError(diag) from None
