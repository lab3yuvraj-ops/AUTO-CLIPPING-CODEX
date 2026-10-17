import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import dotenv_values


@dataclass(frozen=True)
class Config:
    root: Path
    token: str = ''
    owner: int = 0
    codex: str = 'codex'
    timeout: int = 3600
    max_clips: int = 5
    upload_bytes: int = 49_000_000
    default_clips: int = 1
    reselection_attempts: int = 2

    @property
    def state(self):
        return self.root/'workflow/telegram'

    @classmethod
    def load(cls, root):
        root=Path(root).resolve(); values={**dotenv_values(root/'.env'), **os.environ}
        def number(name, default, low, high):
            value=int(values.get(name, default))
            if not low <= value <= high: raise ValueError('Invalid Telegram numeric configuration.')
            return value
        token=values.get('TELEGRAM_BOT_TOKEN','') or ''
        if token and (':' not in token or any(c.isspace() for c in token)):
            raise ValueError('Invalid Telegram bot token format; configure it privately.')
        return cls(root, token, number('TELEGRAM_ALLOWED_USER_ID',0,0,2**63-1),
                   values.get('TELEGRAM_CODEX_PATH','codex'),
                   number('TELEGRAM_JOB_TIMEOUT_SECONDS',3600,60,14400),
                   number('TELEGRAM_MAX_CLIPS',5,1,10),
                   number('TELEGRAM_UPLOAD_MAX_BYTES',49_000_000,1,49_000_000),
                   number('TELEGRAM_DEFAULT_CLIPS',1,1,5),
                   number('TELEGRAM_RESELECTION_ATTEMPTS',2,0,2))

    def require_private_owner(self):
        if not self.token or not self.owner:
            raise ValueError('Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID privately before starting.')
