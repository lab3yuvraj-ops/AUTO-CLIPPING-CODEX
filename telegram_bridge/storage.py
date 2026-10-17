from pathlib import Path
from reel_engine.youtube_transcript import atomic_json as _atomic_json


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    _atomic_json(path,value)
