import json
from pathlib import Path
import pytest
from reel_engine.cleanup import plan_cleanup,inside

def put(root,path,body=b'x'):
    p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body);return p

def test_cleanup_preserves_automation_models_secrets_reference_and_publications(tmp_path):
    for path in ('reel.py','.env','workflow/connection.json','workflow/output-defaults.json','data/models/model.bin','assets/cta/watch-full-video.mp4','.venv/python.exe','workflow/caption-cache/track.json'):
        put(tmp_path,path)
    for ident,published in [('old',False),('published',True),('web3approved',False)]:
        put(tmp_path,f'workflow/jobs/{ident}/job.json',json.dumps({'post_id':'kept' if published else None}).encode())
        put(tmp_path,f'workflow/jobs/{ident}/source.mkv')
        put(tmp_path,f'workflow/jobs/{ident}/spec.json')
    put(tmp_path,'data/legacy/source.mkv');put(tmp_path,'workflow/benchmarks/old/edited.mkv');put(tmp_path,'workflow/benchmarks/old/timing.json')
    plan=plan_cleanup(tmp_path,'test')
    deleted=plan['delete_files'];trees=plan['delete_trees']
    assert any(p.endswith('old\\source.mkv') or p.endswith('old/source.mkv') for p in deleted)
    assert len(plan['archive_moves'])==1 and plan['archive_moves'][0]['source'].endswith('old')
    assert all(not any(key in p for key in ('published','web3approved','model.bin','.env','connection.json','spec.json','timing.json')) for p in deleted)
    assert str(tmp_path/'data/legacy') in trees and str(tmp_path/'data/models') not in trees

def test_cleanup_paths_cannot_escape_or_target_root(tmp_path):
    with pytest.raises(ValueError):inside(tmp_path,tmp_path)
    with pytest.raises(ValueError):inside(tmp_path.parent/'outside',tmp_path)

def test_default_youtube_route_is_sections_and_recovery_is_explicit():
    from reel import use_section_preparation
    assert use_section_preparation()
    assert not use_section_preparation(file='local.mp4')
    assert not use_section_preparation(full_local=True)
    assert not use_section_preparation(full_source=True)

def test_cookie_file_inside_legacy_data_is_preserved(tmp_path):
    cookie=put(tmp_path,'data/legacy/cookies.txt')
    media=put(tmp_path,'data/legacy/source.mkv')
    plan=plan_cleanup(tmp_path,'test',protected_paths=[cookie])
    assert str(tmp_path/'data/legacy') not in plan['delete_trees']
    assert str(cookie) not in plan['delete_files'] and str(media) in plan['delete_files']
