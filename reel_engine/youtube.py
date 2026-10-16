import hashlib
import json
import re
import subprocess
import sys
import time
import os
import concurrent.futures
import threading
import shutil
from collections import deque
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import httpx
from defusedxml import ElementTree


from .config import settings,ROOT

from .errors import StageError,ActionRequired
from .style import approved_config


def video_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.port:
        raise ValueError('Use a public https://youtube.com or https://youtu.be video URL.')
    host = (parsed.hostname or '').lower()
    if host == 'youtu.be':
        value = parsed.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        value = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else parsed.path.split('/')[-1] if parsed.path.startswith(('/shorts/', '/live/')) else ''
    else:
        value = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        raise ValueError('Enter a single YouTube video URL, not a channel or playlist.')
    return value


def download_error(stderr):
    error=_download_error(stderr)
    # Preserve safe downloader diagnostics for caption classification. Never
    # persist signed URLs, cookie headers or configured credential paths.
    from .caption_errors import sanitize_message
    safe=sanitize_message(stderr)
    error.diagnostic={'yt_dlp_message':safe}
    return error

def _download_error(stderr):
    """Classify failures without leaking cookies or signed media URLs."""
    text=stderr.lower()
    if 'not a bot' in text or 'sign in to confirm' in text:
        return ActionRequired('YouTube requires verification. Refresh the authorized local cookie file, then retry; a YouTube API key cannot resolve this challenge.')
    if '429' in text:
        return StageError('YouTube rate-limited this connection (HTTP 429). Stop retries and wait before retrying the saved download.',delay=1800)
    if '403' in text:
        return ActionRequired('YouTube refused the media stream (HTTP 403). Refresh authorized cookies or retry on a permitted network; no lower-quality source was accepted.')
    if 'certificate_verify_failed' in text:
        return ActionRequired('YouTube HTTPS certificate verification failed. Repair the local trust store; certificate checking remains enabled.')
    if 'timed out' in text or 'timeout' in text:
        return StageError('YouTube connection or media read timed out. Saved partial streams can resume; check the network before retrying.',delay=60)
    if 'name resolution' in text or 'getaddrinfo' in text:
        return StageError('YouTube DNS lookup failed. Check network/DNS and retry the saved stage.',delay=60)
    return StageError('YouTube extraction/download failed. Check public availability, cookie authorization and the local JS runtime. No source was accepted.',delay=60)


def stop_download(process):
    """Terminate only our own subprocess tree, including its JS/FFmpeg child."""
    if process.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10)
    else:
        import signal
        os.killpg(process.pid,signal.SIGKILL)
    if process.poll() is None:process.kill()


def complete_audio(path,expected_duration):
    """A renamed stream is usable early only after complete decode checks."""
    from .render import probe
    path=Path(path)
    if not path.is_file() or path.suffix in ('.part','.aria2') or any(Path(str(path)+suffix).exists() for suffix in ('.part','.aria2')):return False
    media=probe(path);streams=media['streams']
    audio=next((s for s in streams if s.get('codec_type')=='audio'),None)
    if not audio or any(s.get('codec_type')=='video' for s in streams):return False
    if abs(float(media['format']['duration'])-float(expected_duration))>2 or abs(float(audio.get('start_time',0)))>.08:return False
    result=subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-vn','-progress','pipe:1','-f','null','-'],capture_output=True,text=True,timeout=60)
    times=re.findall(r'out_time_us=(\d+)',result.stdout)
    return result.returncode==0 and bool(times) and abs(int(times[-1])/1000000-float(expected_duration))<=2


def timeout_diagnostic(error,stderr,phase):
    """Keep downloader evidence when our watchdog, rather than yt-dlp, exits.

    Never persist stdout metadata (which contains signed media URLs).
    """
    from .caption_errors import sanitize_message
    error.diagnostic={**getattr(error,'diagnostic',{}),
        'yt_dlp_message':sanitize_message(stderr).strip() or str(error),
        'watchdog_message':str(error),'failure_phase':phase}
    return error


def provider_options():
    """Explicit optional, on-demand local provider. Never a hosted token service."""
    if not settings.youtube_po_token_home:return []
    home=Path(settings.youtube_po_token_home).resolve()
    if any(c in str(home) for c in (';', '\n', '\r')):
        raise ActionRequired('PO provider path contains an invalid extractor-argument delimiter.')
    if not (home/'build/generate_once.js').is_file():
        raise ActionRequired('Configured local PO provider is not built. Run tools/setup_youtube_po.ps1 first.')
    if not shutil.which('node'):
        raise ActionRequired('The optional local PO provider requires Node.js 22 or newer.')
    from importlib.metadata import version,PackageNotFoundError
    try:installed=version('bgutil-ytdlp-pot-provider')
    except PackageNotFoundError:raise ActionRequired('Install requirements-youtube-po-token.txt in the active Python environment.') from None
    if installed!='2.0.2':raise ActionRequired('Use matching bgutil provider/plugin version 2.0.2; do not silently mix releases.')
    return ['--extractor-args','youtube:player_client=mweb',
            '--extractor-args','youtubepot-bgutilscript:server_home='+home.as_posix()]


def download_environment():
    env={**os.environ,'PYTHONUNBUFFERED':'1'}
    if settings.youtube_po_token_home:
        env['XDG_CACHE_HOME']=str(ROOT/'workflow'/'private-provider-cache')
        trust=env.get('SSL_CERT_FILE')
        if trust and Path(trust).is_file():env.setdefault('NODE_EXTRA_CA_CERTS',trust)
    return env


def bounded_extract(command,timeout,input_info=None):
    """Stop rate-limit responses immediately; expose only safe phase labels."""
    process=subprocess.Popen(command,stdin=subprocess.PIPE if input_info is not None else None,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf-8',errors='replace',start_new_session=os.name!='nt',env=download_environment())
    lines=[];rate_limited=threading.Event();started=time.monotonic()
    def errors():
        for line in process.stderr:
            lines.append(line)
            if re.search(r'HTTP\s+(?:Error|status|error code)\s*:?\s*429\b',line,re.I):rate_limited.set()
            for label in ('Downloading webpage','Downloading player','Downloading m3u8 information','Downloading MPD manifest'):
                if label in line:
                    print(json.dumps({'youtube_stage':label,'seconds':round(time.monotonic()-started,1)}),flush=True);break
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        output=pool.submit(process.stdout.read);reader=pool.submit(errors)
        if input_info is not None:
            def supply():
                try:process.stdin.write(json.dumps(input_info));process.stdin.close()
                except BrokenPipeError:pass
            writer=pool.submit(supply)
        try:
            while process.poll() is None:
                if rate_limited.wait(.2):
                    raise download_error(''.join(lines) or 'HTTP Error 429')
                if time.monotonic()-started>=timeout:
                    raise StageError('YouTube metadata extraction exceeded its 60-second budget. Network/player requests are slow or challenged; no transfer was started.',delay=60)
            reader.result(timeout=10);stdout=output.result(timeout=10)
            stderr=''.join(lines)
            if process.returncode:raise download_error(stderr)
            return stdout
        except StageError as exc:
            if process.poll() is None:stop_download(process)
            reader.result(timeout=15)
            raise timeout_diagnostic(exc,''.join(lines),'metadata')
        finally:
            if process.poll() is None:stop_download(process)
            reader.result(timeout=15);output.result(timeout=15)


def watched_download(command,root,info,timeout,stall_seconds=45,on_audio_ready=None):
    """Bound stalled transfers by byte growth, not a four-hour total timeout."""
    root=Path(root);started=time.monotonic();last_growth=started
    def byte_counts():
        counts={}
        for path in root.glob('source.*'):
            try:
                if path.suffix not in ('.json',):counts[path.name]=path.stat().st_size
            except FileNotFoundError:pass
        return counts
    def writes():
        result={}
        for p in root.glob('source.*'):
            try:
                if p.suffix not in ('.json','.aria2'):result[p.name]=(p.stat().st_size,p.stat().st_mtime_ns)
            except FileNotFoundError:pass
        return result
    activity=writes();last_report=0
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf-8',errors='replace',start_new_session=os.name!='nt',
        env=download_environment())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(process.communicate,json.dumps(info))
        audio_notified=False
        try:
            while True:
                try:
                    stdout,stderr=result.result(timeout=1)
                    if process.returncode:raise download_error(stderr)
                    return stdout
                except concurrent.futures.TimeoutError:pass
                if on_audio_ready and not audio_notified:
                    for candidate in root.glob('source.f*.*'):
                        if candidate.suffix in ('.part','.aria2','.json') or Path(str(candidate)+'.part').exists():continue
                        try:
                            if not complete_audio(candidate,info['duration']):continue
                            target=root/('early-audio'+candidate.suffix)
                            shutil.copy2(candidate,target)
                            on_audio_ready(str(target.resolve()));audio_notified=True;break
                        except (RuntimeError,ValueError,OSError,KeyError,subprocess.TimeoutExpired):continue
                now=time.monotonic();current=byte_counts()
                recent=writes()
                # Parallel range writes may not increase a sparse file's size.
                # Watch real media writes, not aria2's periodic control saves.
                if any(value!=activity.get(name) for name,value in recent.items()):last_growth=now
                activity=recent
                if now-last_report>=5:
                    from .youtube_transcript import atomic_json
                    progress={'stage':'Downloading / merging','elapsed_seconds':round(now-started,1),
                        'bytes_on_disk':sum(current.values()),'seconds_since_growth':round(now-last_growth,1)}
                    atomic_json(root/'download-progress.json',progress)
                    print(json.dumps({'download_progress':progress}),flush=True);last_report=now
                if now-last_growth>=stall_seconds:
                    raise StageError(f'YouTube media transfer made no byte progress for {stall_seconds} seconds. Stopped the stalled downloader; partial files are retained. Check the connection and retry.',delay=60)
                if now-started>=timeout:
                    raise StageError('Download time budget exceeded. Partial streams are retained for resuming; no incomplete video was accepted.',delay=60)
        except StageError as exc:
            if process.poll() is None:stop_download(process)
            stdout,stderr=result.result(timeout=15)
            error=timeout_diagnostic(exc,stderr,'media_transfer')
            from .caption_errors import sanitize_message
            # Only known transfer progress lines; never metadata JSON or
            # arbitrary stdout. This distinguishes pre-FFmpeg stalls next time.
            error.diagnostic['transfer_progress']=sanitize_message('\n'.join(
                line for line in stdout.splitlines() if line.startswith(('[info]','[download]','[youtube]'))))
            raise error
        finally:
            if process.poll() is None:stop_download(process)
            result.result(timeout=15)


_REQUEST_LOCK=threading.Lock()
_LAST_REQUEST={}

def throttle_video(ident):
    if not ident:return
    with _REQUEST_LOCK:
        now=time.monotonic();wait=max(0,_LAST_REQUEST.get(ident,0)+max(0,settings.youtube_request_delay_seconds)-now)
        if wait:time.sleep(wait)
        _LAST_REQUEST[ident]=time.monotonic()

def ytdlp(args, timeout=60, info=None, progress_root=None,metadata_input=None,on_audio_ready=None):
    try:return _ytdlp_call(args,timeout,info,progress_root,metadata_input,on_audio_ready)
    except Exception as exc:
        from .caption_errors import classify_caption_failure
        from .timing import _locked
        diagnostic={**getattr(exc,'diagnostic',{}),**classify_caption_failure(getattr(exc,'diagnostic',{}).get('yt_dlp_message',str(exc)))}
        if '--sub-langs' in args:diagnostic['requested_language']=args[args.index('--sub-langs')+1]
        ident=(metadata_input or info or {}).get('id')
        if not ident:
            for arg in args:
                try:ident=video_id(arg);break
                except (ValueError,TypeError):pass
        path=ROOT/'workflow'/'stage-failures.jsonl'
        with _locked(path):
            with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps({'stage':'youtube_request','video_id':ident,'at':time.time(),'diagnostic':diagnostic})+'\n')
        raise

def _ytdlp_call(args, timeout=60, info=None, progress_root=None,metadata_input=None,on_audio_ready=None):
    if settings.youtube_cookie_file and not Path(settings.youtube_cookie_file).is_file():
        raise ActionRequired('The configured YouTube cookie file does not exist. Correct YOUTUBE_COOKIE_FILE, restart the worker, then retry this stage.')
    extra=provider_options()+(['--cookies',settings.youtube_cookie_file] if settings.youtube_cookie_file else [])
    if settings.youtube_cookies_from_browser:extra+=['--cookies-from-browser',settings.youtube_cookies_from_browser]
    ident=(metadata_input or info or {}).get('id')
    if not ident:
        for arg in args:
            try:ident=video_id(arg);break
            except (ValueError,TypeError):pass
    throttle_video(ident)
    command=[sys.executable, '-m', 'yt_dlp', '--ignore-config', '--compat-options','no-certifi',
        '--js-runtimes','node','--no-playlist','--socket-timeout','10',
        '--extractor-retries','1','--retries','1','--fragment-retries','1','--retry-sleep','1',*extra,*args]
    if '--write-subs' in args:command[2]='reel_engine.caption_downloader'
    if info is not None:
        command+=['--load-info-json','-']
        if progress_root is None:raise ValueError('A watched download requires its job directory.')
        return watched_download(command,progress_root,info,timeout,on_audio_ready=on_audio_ready) if on_audio_ready else watched_download(command,progress_root,info,timeout)
    if metadata_input is not None:command+=['--load-info-json','-']
    return bounded_extract(command,min(timeout,60),input_info=metadata_input) if metadata_input is not None else bounded_extract(command,min(timeout,60))


def transfer_options(root=None):
    """Use a bounded four-connection downloader when locally installed."""
    executable=shutil.which('aria2c')
    bundled=ROOT/'tools/vendor/aria2/aria2c.exe'
    if not executable and bundled.is_file():executable=str(bundled)
    controls=list(Path(root).glob('source.*.aria2')) if root else []
    native_partials=list(Path(root).glob('source.*.part')) if root else []
    if controls and not executable:
        raise ActionRequired('This partial transfer belongs to aria2. Install aria2c to resume it; do not resume sparse parallel files with the native downloader.')
    # Never silently change the backend of an existing partial transfer.
    if not controls and (native_partials or not settings.parallel_downloads):return ['--concurrent-fragments','4']
    if not executable:return ['--concurrent-fragments','4']
    options='aria2c:-x4 -s4 -k1M --file-allocation=none --auto-file-renaming=false --max-tries=2 --retry-wait=1 --connect-timeout=10 --timeout=10'
    trust=ROOT/'.venv/ca.pem'
    if trust.is_file():options+=' --ca-certificate="'+str(trust)+'"'
    return ['--downloader',executable,'--downloader-args',options]


def download(job, root, info=None,no_retries=False):
    url = f'https://www.youtube.com/watch?v={job.video_id}'
    if info is None:info=json.loads(ytdlp(['--dump-single-json','--skip-download',url]))
    if info.get('is_live') or info.get('live_status') in ('is_upcoming', 'is_live', 'post_live'):
        raise StageError('Waiting for the scheduled/live video to finish and become a processed public upload.', delay=1800)
    if info.get('availability') not in (None, 'public'):
        raise StageError('Video is not public. Make it public, then retry.', False)
    if not info.get('duration') or info['duration'] > settings.max_source_seconds:
        raise StageError(f'Video is missing a duration or exceeds the {settings.max_source_seconds // 60}-minute source limit.', False)
    if job.config.get('channel_id') and (job.config.get('from_monitor') or job.config.get('verify_channel')) and info.get('channel_id') != job.config['channel_id']:
        raise StageError('Notification channel does not match the video owner.', False)
    if job.config.get('from_monitor') and (info.get('release_timestamp') or info.get('timestamp') or time.time()) < job.config.get('monitor_since',0):
        raise StageError('This upload predates channel monitoring. A title/description update does not make it a new upload. Use manual input to process it.',False)
    height = max((f.get('height') or 0 for f in info.get('formats', []) if f.get('vcodec') != 'none'), default=0)
    if height < job.config.get('min_source_height', settings.min_source_height):
        waiting = time.time() - job.created < settings.quality_wait_hours * 3600
        raise StageError(f'Only {height}p is available; waiting for the configured source quality. Lower the quality floor explicitly if this is the original resolution.', waiting, 1800)
    root.mkdir(parents=True, exist_ok=True)
    # Keep expiring URLs in memory and send metadata over stdin, eliminating
    # the second extraction. Never persist the full info JSON or signed URLs.
    metadata = {k: info.get(k) for k in ['id','title','duration','channel_id','upload_date','width','height','fps']}
    metadata['best_available_height']=height
    (root/'source.json').write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
    options=transfer_options(root)
    if no_retries:options=[x.replace('--max-tries=2','--max-tries=1') for x in options]+['--retries','0','--fragment-retries','0','--extractor-retries','0']
    ytdlp([*options,'-f','bv*+ba/b','--merge-output-format','mkv','--remux-video','mkv',
        '--continue','--abort-on-unavailable-fragments','--max-filesize','12G','-o',str(root/'source.%(ext)s')],
        timeout=900,info=info,progress_root=root)
    path = root / 'source.mkv'
    if not path.exists():
        raise StageError('Download completed without the expected source file.')
    from .render import probe
    media=probe(path)
    video=next((s for s in media['streams'] if s.get('codec_type')=='video'),{})
    audio=next((s for s in media['streams'] if s.get('codec_type')=='audio'),{})
    actual=float(media['format'].get('duration',0))
    if not audio or video.get('height',0)<height or abs(actual-float(info['duration']))>2:
        raise StageError('Downloaded media is incomplete or below the highest advertised resolution. Files are retained for diagnosis; no source was accepted.',False)
    metadata = {k: info.get(k) for k in ['id','title','duration','channel_id','upload_date','width','height','fps']}
    metadata['best_available_height'] = height
    (root / 'source.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    from .youtube_transcript import atomic_json
    atomic_json(root/'download-progress.json',{'stage':'Complete','source_seconds':actual,
        'height':video['height'],'bytes_on_disk':path.stat().st_size})
    return {'source': str(path.resolve()), 'metadata': metadata}


def topic(channel):
    return f'https://www.youtube.com/feeds/videos.xml?channel_id={channel}'


def feed_ids(xml):
    root = ElementTree.fromstring(xml)
    return [(e.findtext('{http://www.youtube.com/xml/schemas/2015}videoId'), e.findtext('{http://www.youtube.com/xml/schemas/2015}channelId')) for e in root.findall('{http://www.w3.org/2005/Atom}entry')]


def feed_published(xml):
    from datetime import datetime
    root=ElementTree.fromstring(xml)
    result={}
    for e in root.findall('{http://www.w3.org/2005/Atom}entry'):
        stamp=e.findtext('{http://www.w3.org/2005/Atom}published')
        vid=e.findtext('{http://www.youtube.com/xml/schemas/2015}videoId')
        if stamp and vid:
            result[vid]=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
    return result


