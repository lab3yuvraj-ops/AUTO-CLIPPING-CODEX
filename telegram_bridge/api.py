"""Bot API transport. Never propagate httpx URLs (which contain the token)."""
import time
import httpx


class TelegramError(Exception):
    def __init__(self, status=0, retry_after=0):
        super().__init__(f'Telegram request failed (HTTP {status}); no secret response was logged.')
        self.status=status; self.retry_after=retry_after


class API:
    def __init__(self, token, client=None):
        self.base='https://api.telegram.org/bot'+token+'/'
        self.client=client or httpx.Client(timeout=httpx.Timeout(70,connect=15),follow_redirects=False)

    def call(self, method, data=None, files=None):
        try:
            response=self.client.post(self.base+method,data=data or {},files=files,
                timeout=httpx.Timeout(600,connect=15) if files else httpx.Timeout(70,connect=15))
            body=response.json()
            if not response.is_success or body.get('ok') is not True:
                raise TelegramError(response.status_code,int(body.get('parameters',{}).get('retry_after',0)))
            return body['result']
        except TelegramError: raise
        except (httpx.HTTPError,ValueError,KeyError,TypeError):
            raise TelegramError() from None

    def updates(self, offset, timeout=30):
        return self.call('getUpdates',{'offset':offset,'timeout':timeout,'allowed_updates':'["message"]'})

    def text(self, chat, text):
        # Callers pass constant status strings; never model output or stderr.
        return self.call('sendMessage',{'chat_id':chat,'text':text[:4000]})

    def video(self, chat, path):
        with path.open('rb') as stream:
            return self.call('sendVideo',{'chat_id':chat,'supports_streaming':'true',
                'caption':'Generated Reel preview. Not published to Instagram.'},
                {'video':('reel.mp4',stream,'video/mp4')})
