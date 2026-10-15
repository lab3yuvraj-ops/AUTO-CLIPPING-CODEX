import json
import pytest
from reel_engine.caption_errors import classify_caption_failure,CaptionFetchError
from reel_engine import original_captions as captions

@pytest.fixture(autouse=True)
def isolated_shared_cache(tmp_path,monkeypatch):
    from reel_engine.config import settings
    monkeypatch.setattr(settings,'caption_cache_dir',tmp_path/'shared-cache')


@pytest.mark.parametrize('message,category,transient,rejected',[
    ('No original uploaded captions exist.','no_original_captions',False,True),
    ('Caption coverage is insufficient','incomplete_original_captions',False,True),
    ('ERROR: Unable to download video subtitles: HTTP Error 429: Too Many Requests','rate_limiting',True,False),
    ('Sign in to confirm you are not a bot','bot_check',False,False),
    ('HTTP Error 503: Service Unavailable','temporary_network_failure',True,False),
    ('HTTP Error 403: Forbidden','endpoint_access_failure',False,False),
    ('No subtitle format json3','language_format_mismatch',False,False),
    ('player extraction failed','extractor_endpoint_issue',False,False),
    ('certificate verify failed','local_tls_failure',False,False),
])
def test_classification(message,category,transient,rejected):
    result=classify_caption_failure(message,language='en')
    assert (result['category'],result['transient'],result['content_rejection'])==(category,transient,rejected)
    assert result['requested_language']=='en'


def test_sanitization_removes_signed_urls_headers_and_keys():
    result=classify_caption_failure('HTTP Error 429 https://server/path?secret=hidden\nAuthorization: Bearer hidden')
    assert 'secret=hidden' not in str(result) and 'Bearer hidden' not in str(result)
    assert result['http_status']==429


def info():return {'language':'en','subtitles':{'en':[{'ext':'json3'}]},'automatic_captions':{'en-orig':[{'ext':'json3'}]}}


def test_no_uploaded_track_never_substitutes_auto():
    with pytest.raises(CaptionFetchError) as exc:captions.uploaded_language({'automatic_captions':{'en-orig':[]}})
    assert exc.value.diagnostic['category']=='no_original_captions'


def test_uploaded_language_selection_is_native_not_translation():
    assert captions.uploaded_language(info())=='en'
    with pytest.raises(CaptionFetchError):captions.uploaded_language({'language':'en','subtitles':{'hi':[{'ext':'json3'}]}})


def test_transient_attempts_bounded_and_backoffs_timed(tmp_path,monkeypatch):
    calls=[];sleeps=[];stages=[]
    from contextlib import contextmanager
    @contextmanager
    def hook(name):stages.append(name);yield
    def fail(args,**kwargs):
        calls.append(args)
        assert '--write-subs' in args and '--no-write-auto-subs' in args and '--write-auto-subs' not in args
        raise RuntimeError('ERROR: HTTP Error 429: Too Many Requests')
    monkeypatch.setattr(captions.youtube,'ytdlp',fail)
    with pytest.raises(CaptionFetchError):captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info(),hook,sleeps.append)
    assert len(calls)==3 and sum(sleeps)==240 and max(sleeps)<=30
    assert stages==['caption_attempt_1','caption_backoff_1','caption_attempt_2','caption_backoff_2','caption_attempt_3']
    record=json.loads((tmp_path/'caption-fetch-failure.json').read_text())
    assert record['category']=='rate_limiting' and not record['content_rejection'] and len(record['attempts'])==3


def test_content_failure_has_no_network_retry(tmp_path,monkeypatch):
    monkeypatch.setattr(captions.youtube,'ytdlp',lambda *a,**k:pytest.fail('No substitution/request'))
    with pytest.raises(CaptionFetchError):captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,{'subtitles':{},'automatic_captions':{'en-orig':[]}})


def test_retry_success_preserves_uploaded_provenance(tmp_path,monkeypatch):
    calls=[]
    def download(args,**kwargs):
        calls.append(args)
        if len(calls)==1:raise RuntimeError('HTTP Error 503')
        body={'events':[{'tStartMs':i*1000,'dDurationMs':1000,'segs':[{'utf8':'a complete original sentence'}]} for i in range(60)]}
        (tmp_path/'uploaded-captions.en.json3').write_text(json.dumps(body))
    monkeypatch.setattr(captions.youtube,'ytdlp',download)
    result=captions.fetch_uploaded_captions('abcdefghijk',tmp_path,60,info(),sleep=lambda _:None)
    assert result['caption_kind']=='uploaded' and result['language']=='en' and result['words']==[]
    assert len(result['caption_fetch_attempts'])==2


@pytest.mark.parametrize('message', ['HTTP Error 429','No original uploaded captions exist.','HTTP Error 403'])
def test_fast_caption_failure_falls_back_to_local_asr_and_logs_route(tmp_path,monkeypatch,message):
    from reel_engine import fast,fast_download,fast_gate,local_transcription,proxy_asr,overview
    monkeypatch.setattr(fast.youtube,'ytdlp',lambda *a,**k:json.dumps({'id':'abcdefghijk','duration':60,'formats':[]}))
    def fail(*a,**k):raise CaptionFetchError(classify_caption_failure(message,language='en'))
    monkeypatch.setattr(fast,'fetch_caption_draft',fail)
    monkeypatch.setattr(fast_download,'download_proxy',lambda *a,**k:{'source':'proxy','source_sha256':'hash'})
    monkeypatch.setattr(fast_gate,'gather_visual_samples',lambda *a,**k:{'overview_hashes':{},'visual_samples_sha256':'hash'})
    monkeypatch.setattr(overview,'make_overview',lambda *a,**k:{'pages':[],'page_files':[],'source_seconds':60})
    calls=[]
    from reel_engine import selection_draft
    monkeypatch.setattr(selection_draft,'transcribe_selection_draft',lambda *a,**k:calls.append(a) or {'transcription_timings':{'asr_seconds':5}})
    from reel_engine import speech_worker
    monkeypatch.setattr(speech_worker,'request',lambda root,run,op,args=None,**kw:local_transcription.transcribe_local(args['source'],args['root']))
    monkeypatch.setattr(proxy_asr,'bind_proxy_asr',lambda *a,**k:{'audio_equivalence':{'identical_pcm':True}})
    result=fast.analyze_fast(tmp_path,'https://www.youtube.com/watch?v=abcdefghijk',2,normal_analyze=lambda **k:pytest.fail('Caption failure does not switch to full pipeline'))
    assert result['status']=='Fast selection ready; classify selected passages'
    assert len(calls)==1 and result['transcript_route']['route']=='local ASR'
    route=json.loads((tmp_path/'jobs'/result['id']/'transcript-route.json').read_text())
    assert route['reason']['category']==classify_caption_failure(message)['category']
