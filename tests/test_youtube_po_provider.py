from pathlib import Path
import importlib.metadata
import pytest
from reel_engine import youtube
from reel_engine.errors import ActionRequired


def test_provider_is_opt_in(monkeypatch):
    monkeypatch.setattr(youtube.settings,'youtube_po_token_home','')
    assert youtube.provider_options()==[]


def test_missing_provider_fails_without_starting_network(tmp_path,monkeypatch):
    monkeypatch.setattr(youtube.settings,'youtube_po_token_home',str(tmp_path))
    with pytest.raises(ActionRequired,match='not built'):youtube.provider_options()


def test_configures_local_script_and_explicit_client(tmp_path,monkeypatch):
    (tmp_path/'build').mkdir();(tmp_path/'build/generate_once.js').write_text('')
    monkeypatch.setattr(youtube.settings,'youtube_po_token_home',str(tmp_path))
    monkeypatch.setattr(youtube.shutil,'which',lambda *a:'node')
    monkeypatch.setattr(importlib.metadata,'version',lambda *a:'2.0.2')
    args=youtube.provider_options()
    assert 'youtube:player_client=mweb' in args
    assert 'youtubepot-bgutilscript:server_home='+tmp_path.as_posix() in args
    assert not any('http:' in arg or 'https:' in arg for arg in args)
    monkeypatch.setattr(importlib.metadata,'version',lambda *a:'1.0.0')
    with pytest.raises(ActionRequired,match='mix releases'):youtube.provider_options()


def test_provider_cache_stays_in_ignored_workspace(monkeypatch,tmp_path):
    monkeypatch.setattr(youtube.settings,'youtube_po_token_home',str(tmp_path))
    cert=tmp_path/'cert.pem';cert.write_text('test')
    monkeypatch.setenv('SSL_CERT_FILE',str(cert));monkeypatch.delenv('NODE_EXTRA_CA_CERTS',raising=False)
    env=youtube.download_environment()
    assert Path(env['XDG_CACHE_HOME'])==youtube.ROOT/'workflow/private-provider-cache'
    assert env['NODE_EXTRA_CA_CERTS']==str(cert)
    assert 'XDG_CACHE_HOME' not in __import__('os').environ or __import__('os').environ['XDG_CACHE_HOME']!=env['XDG_CACHE_HOME']


def test_private_provider_fields_are_redacted():
    from reel_engine.caption_errors import sanitize_message
    text=sanitize_message('po_token=SECRET_ONE "poToken": "SECRET_TWO" visitor_data=SECRET_THREE content_binding=SECRET_FOUR')
    assert 'SECRET_' not in text
    assert text.count('[private provider value redacted]')==4
    assert 'signed-secret' not in sanitize_message('request: GET /videoplayback?sig=signed-secret&pot=private HTTP/1.1')
