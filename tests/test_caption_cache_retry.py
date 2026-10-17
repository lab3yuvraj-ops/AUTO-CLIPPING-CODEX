import json
from contextlib import contextmanager
from datetime import datetime,timezone
import pytest
from reel_engine import original_captions as captions,timing,youtube
from reel_engine.caption_errors import CaptionFetchError,classify_caption_failure


def info():return {'id':'abcdefghijk','language':'en','subtitles':{'en':[{'ext':'json3'}]}}
def fixture():return {'events':[{'tStartMs':i*1000,'dDurationMs':1000,'segs':[{'utf8':'the complete original caption'}]} for i in range(60)]}


def downloader(calls):
    def fetch(args,**kwargs):
        calls.append((args,kwargs))
        assert kwargs['metadata_input']==info() and not any('youtube.com' in arg for arg in args)
        root=__import__('pathlib').Path(args[args.index('-o')+1]).parent
        (root/'uploaded-captions.en.json3').write_text(json.dumps(fixture()))
    return fetch


def test_shared_hit_miss_hash_validation_and_fresh_bypass(tmp_path,monkeypatch):
    calls=[];cache=tmp_path/'cache'
    monkeypatch.setattr(captions.youtube,'ytdlp',downloader(calls))
    first=captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'one',60,info(),cache_dir=cache)
    assert not first['caption_cached'] and len(calls)==1
    record=json.loads((cache/'abcdefghijk/record.json').read_text())
    assert record['language']=='en' and record['format']=='json3' and record['fetched_at']>0 and len(record['sha256'])==64
    hook=lambda name:timing.stage(tmp_path,'abcdefghijk','cache_'+name,run_id='cachetest')
    hit=captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'two',60,info(),hook,cache_dir=cache)
    assert hit['caption_cached'] and len(calls)==1
    assert timing.report(tmp_path,'abcdefghijk')['intervals'][0]['cached']
    bypass=captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'three',60,info(),cache_dir=cache,fresh_captions=True)
    assert not bypass['caption_cached'] and len(calls)==2
    (cache/'abcdefghijk/uploaded.json3').write_text('{}')
    captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'four',60,info(),cache_dir=cache)
    assert len(calls)==3
    captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'four',60,info(),cache_dir=cache)
    assert len(calls)==3,'No second policy fetch in the same run'


def test_retry_after_seconds_date_and_invalid():
    assert captions.retry_delay({'retry_after':'125'},1,now=0)==125
    assert captions.retry_delay({'retry_after':'Thu, 01 Jan 1970 00:02:00 GMT'},1,now=0)==120
    assert captions.retry_delay({'retry_after':'invalid'},2)==180
    assert captions.retry_delay({},3)==600
    assert classify_caption_failure('HTTP Error 429\nRetry-After: 71')['retry_after']=='71'


def test_uploaded_shared_cache_rejects_wrong_audio_language(tmp_path,monkeypatch):
    import hashlib
    from reel_engine.youtube_transcript import atomic_json
    cache=tmp_path/'cache';folder=cache/'abcdefghijk';folder.mkdir(parents=True)
    raw=json.dumps(fixture()).encode();(folder/'uploaded.json3').write_bytes(raw)
    atomic_json(folder/'record.json',{'caption_kind':'uploaded','format':'json3','video_id':'abcdefghijk',
        'source_duration':60.,'language':'ar','sha256':hashlib.sha256(raw).hexdigest()})
    calls=[];monkeypatch.setattr(captions.youtube,'ytdlp',downloader(calls))
    result=captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'job',60,info(),cache_dir=cache)
    assert result['language']=='en' and not result['caption_cached'] and len(calls)==1


def test_wrong_language_run_receipt_does_not_refetch(tmp_path,monkeypatch):
    from reel_engine.youtube_transcript import atomic_json
    atomic_json(tmp_path/'caption-request.json',{'video_id':'abcdefghijk'})
    atomic_json(tmp_path/'uploaded-transcript.json',{'language':'ar'})
    monkeypatch.setattr(captions.youtube,'ytdlp',lambda *a,**k:pytest.fail('No second fetch'))
    with pytest.raises(CaptionFetchError) as exc:
        captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info(),cache_dir=tmp_path/'cache')
    assert 'contradicts' in exc.value.diagnostic['yt_dlp_message']


def test_header_exceeding_cap_stops_without_shortening_wait(tmp_path,monkeypatch):
    calls=[];waits=[]
    def fail(*args,**kwargs):calls.append(True);raise RuntimeError('HTTP Error 429\nRetry-After: 601')
    monkeypatch.setattr(youtube,'ytdlp',fail)
    with pytest.raises(CaptionFetchError) as exc:
        captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info(),sleep=waits.append,cache_dir=tmp_path/'cache',wait_cap=600)
    assert calls==[True] and waits==[]
    assert exc.value.diagnostic['attempt_count']==1 and not exc.value.diagnostic['content_rejection']
    assert exc.value.diagnostic['suggested_retry_at']
    with pytest.raises(CaptionFetchError):captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info(),cache_dir=tmp_path/'cache')
    assert calls==[True]


def test_header_wait_honored_and_full_failure_logged(tmp_path,monkeypatch):
    calls=[];waits=[]
    long='ERROR: HTTP Error 429: Too Many Requests\nRetry-After: 7\n'+'context '*800
    def fail(*args,**kwargs):calls.append(True);raise RuntimeError(long)
    monkeypatch.setattr(youtube,'ytdlp',fail)
    hook=lambda name:timing.stage(tmp_path,'abcdefghijk',name,run_id='retrytest')
    with pytest.raises(CaptionFetchError):captions.fetch_uploaded_captions('abcdefghijk',tmp_path/'job',60,info(),hook,waits.append,cache_dir=tmp_path/'cache',wait_cap=10)
    assert waits==[7] and len(calls)==2
    failed=[i for i in timing.report(tmp_path,'abcdefghijk')['intervals'] if i['outcome']=='failed']
    assert len(failed)==2 and all(i['diagnostic']['http_status']==429 and len(i['diagnostic']['yt_dlp_message'])>4000 for i in failed)


def test_browser_cookie_option_default_off_and_explicit(monkeypatch):
    from reel_engine.config import settings
    commands=[]
    monkeypatch.setattr(settings,'youtube_cookie_file','')
    monkeypatch.setattr(settings,'youtube_cookies_from_browser','')
    monkeypatch.setattr(youtube,'throttle_video',lambda _:None)
    monkeypatch.setattr(youtube,'bounded_extract',lambda command,*a,**k:commands.append(command) or '')
    youtube.ytdlp(['--list-subs','https://www.youtube.com/watch?v=abcdefghijk'])
    assert '--cookies-from-browser' not in commands[-1]
    monkeypatch.setattr(settings,'youtube_cookies_from_browser','chrome')
    youtube.ytdlp(['--list-subs','https://www.youtube.com/watch?v=abcdefghijk'])
    assert commands[-1][commands[-1].index('--cookies-from-browser')+1]=='chrome'


def test_same_video_call_spacing(monkeypatch):
    from reel_engine.config import settings
    monkeypatch.setattr(settings,'youtube_request_delay_seconds',2)
    monkeypatch.setattr(youtube.time,'monotonic',lambda:100)
    waits=[];monkeypatch.setattr(youtube.time,'sleep',waits.append)
    youtube._LAST_REQUEST.clear()
    youtube.throttle_video('abcdefghijk');youtube.throttle_video('abcdefghijk');youtube.throttle_video('lmnopqrstuv')
    assert waits==[2]


def test_info_file_error_cannot_trigger_hidden_url_reextraction(monkeypatch):
    import io
    from reel_engine.caption_downloader import CaptionDownloader
    downloader=object.__new__(CaptionDownloader)
    monkeypatch.setattr('sys.stdin',io.StringIO(json.dumps({'id':'abcdefghijk','webpage_url':'https://www.youtube.com/watch?v=abcdefghijk'})))
    monkeypatch.setattr(downloader,'sanitize_info',lambda data:data)
    def fail(*args,**kwargs):raise RuntimeError('HTTP Error 429')
    monkeypatch.setattr(downloader,'process_ie_result',fail)
    monkeypatch.setattr(downloader,'download',lambda _:pytest.fail('No hidden re-extraction'))
    with pytest.raises(RuntimeError,match='429'):downloader.download_with_info_file('-')


def test_retry_after_header_exposed_without_credential_headers(monkeypatch,capsys):
    from reel_engine.caption_downloader import CaptionDownloader
    import yt_dlp
    downloader=object.__new__(CaptionDownloader)
    monkeypatch.setattr(yt_dlp.YoutubeDL,'report_error',lambda *a,**k:None)
    class HttpFailure(Exception):headers={'Retry-After':'123','Authorization':'private'}
    try:raise HttpFailure('HTTP Error 429')
    except HttpFailure:downloader.report_error('HTTP Error 429')
    output=capsys.readouterr().err
    assert output=='Retry-After: 123\n' and 'private' not in output
