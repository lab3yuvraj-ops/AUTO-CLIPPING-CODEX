import json
import sys
import time

import pytest

from reel_engine.youtube import watched_download,download_error,bounded_extract
from reel_engine.errors import StageError,ActionRequired


def test_stalled_zero_byte_transfer_stops_and_retains_partial(tmp_path):
    code='import sys,json,time; from pathlib import Path; d=json.load(sys.stdin); Path(d["file"]).touch(); time.sleep(30)'
    started=time.monotonic()
    with pytest.raises(StageError,match='no byte progress'):
        watched_download([sys.executable,'-c',code],tmp_path,{'file':str(tmp_path/'source.mp4.part')},10,stall_seconds=2)
    assert time.monotonic()-started<10
    assert (tmp_path/'source.mp4.part').exists()
    assert not (tmp_path/'source.mkv').exists()


def test_active_transfer_can_run_beyond_stall_window(tmp_path):
    code='import sys,json,time; from pathlib import Path; d=json.load(sys.stdin); f=Path(d["file"]).open("wb"); [(f.write(b"x"),f.flush(),time.sleep(.2)) for _ in range(16)]; f.close(); print("done")'
    result=watched_download([sys.executable,'-c',code],tmp_path,{'file':str(tmp_path/'source.mp4.part')},10,stall_seconds=2)
    assert 'done' in result and (tmp_path/'source.mp4.part').stat().st_size==16


def test_provider_error_does_not_expose_signed_url(tmp_path):
    code='import sys,json; json.load(sys.stdin); sys.stderr.write("HTTP Error 403: https://cdn.example/?token=private"); sys.exit(1)'
    with pytest.raises(ActionRequired) as error:
        watched_download([sys.executable,'-c',code],tmp_path,{},10)
    assert '403' in str(error.value) and 'private' not in str(error.value)
    assert not download_error('CERTIFICATE_VERIFY_FAILED').retry
    assert download_error('HTTP Error 429').delay==1800


def test_metadata_rate_limit_stops_without_waiting_for_process_timeout():
    code='import sys,time; sys.stderr.write("HTTP Error 429: https://cdn.example/?token=private\\n"); sys.stderr.flush(); time.sleep(30)'
    started=time.monotonic()
    with pytest.raises(StageError) as error:bounded_extract([sys.executable,'-c',code],10)
    assert error.value.delay==1800 and 'private' not in str(error.value)
    assert time.monotonic()-started<5


def test_metadata_stdout_is_not_mixed_with_progress():
    code='import sys; sys.stderr.write("[youtube] Downloading webpage\\n"); print("{\\"id\\":\\"video\\"}")'
    assert json.loads(bounded_extract([sys.executable,'-c',code],5))=={'id':'video'}


def test_sparse_media_writes_do_not_trigger_false_stall(tmp_path):
    code='import sys,json,time; from pathlib import Path; d=json.load(sys.stdin); f=Path(d["file"]).open("wb"); f.truncate(1000); [(f.seek(0),f.write(b"x"),f.flush(),time.sleep(.2)) for _ in range(16)]; f.close()'
    watched_download([sys.executable,'-c',code],tmp_path,{'file':str(tmp_path/'source.mp4.part')},10,stall_seconds=2)
    assert (tmp_path/'source.mp4.part').stat().st_size==1000


def test_partial_backend_cannot_be_switched_silently(monkeypatch,tmp_path):
    from reel_engine import youtube
    monkeypatch.setattr(youtube.settings,'parallel_downloads',True)
    monkeypatch.setattr(youtube.shutil,'which',lambda p:'aria2c')
    (tmp_path/'source.mp4.part').touch()
    assert '--downloader' not in youtube.transfer_options(tmp_path)
    (tmp_path/'source.mp4.part.aria2').touch()
    assert '--downloader' in youtube.transfer_options(tmp_path)
