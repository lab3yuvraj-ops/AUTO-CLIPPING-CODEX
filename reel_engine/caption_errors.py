"""Caption-specific causes; availability is distinct from a failed request."""
import re


def sanitize_message(message):
    from .config import settings
    text=str(message)
    text=re.sub(r'https?://\S+','[URL redacted]',text)
    text=re.sub(r'(?im)(\b(?:GET|HEAD|POST)\s+)\S+\?\S+',r'\1[request target redacted]',text)
    text=re.sub(r'(?im)^.*(?:cookie:|authorization:|set-cookie:).*$', '[credential header redacted]',text)
    text=re.sub(r'(?:gh[pousr]_|hf_|sk-)[A-Za-z0-9_-]{15,}','[key redacted]',text)
    text=re.sub(r'''(?i)(["']?(?:po[_-]?token|visitor[_-]?data|content[_-]?binding)["']?\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;}\]]+)''',r'\1[private provider value redacted]',text)
    if settings.youtube_cookie_file:text=text.replace(settings.youtube_cookie_file,'[private cookie path]')
    return text


def classify_caption_failure(message, *, language=None, status=None):
    text=sanitize_message(message);low=text.lower()
    if status is None:
        match=re.search(r'HTTP\s+(?:Error|status|error code)?\s*:?\s*(\d{3})',text,re.I)
        status=int(match[1]) if match else None
    category='unknown_fetch_failure';transient=False;content_rejection=False
    if 'no original uploaded captions' in low:category='no_original_captions';content_rejection=True
    elif 'coverage' in low or 'caption track has a substantial' in low or 'missing the source ending' in low:category='incomplete_original_captions';content_rejection=True
    elif 'not a bot' in low or 'sign in to confirm' in low:category='bot_check'
    elif status==429:category='rate_limiting';transient=True
    elif status in (408,500,502,503,504) or 'timed out' in low or 'timeout' in low:category='temporary_network_failure';transient=True
    elif status==403:category='endpoint_access_failure'
    elif 'json3' in low or 'language' in low or 'no subtitle format' in low:category='language_format_mismatch'
    elif 'certificate' in low:category='local_tls_failure'
    elif status in (400,404,410) or 'extractor' in low or 'player' in low:category='extractor_endpoint_issue'
    after=re.search(r'Retry-After\s*:\s*([^\r\n]+)',text,re.I)
    return {'category':category,'http_status':status,'yt_dlp_message':text,'requested_language':language,'retry_after':after[1].strip() if after else None,
            'transient':transient,'content_rejection':content_rejection}


class CaptionFetchError(ValueError):
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        prefix='No original captions exist' if diagnostic['category']=='no_original_captions' else 'Original captions incomplete' if diagnostic['content_rejection'] else 'Original caption fetch failed'
        super().__init__(f"{prefix}: {diagnostic['category']}"+(f" (HTTP {diagnostic['http_status']})" if diagnostic.get('http_status') else '')+f"; requested language {diagnostic.get('requested_language') or 'not yet selected'}.")
        if diagnostic.get('attempt_count'):
            self.args=(str(self)+f" Attempts: {diagnostic['attempt_count']}; suggested retry after {diagnostic.get('suggested_retry_at','the reported cooldown')}; no transcript substituted.",)
