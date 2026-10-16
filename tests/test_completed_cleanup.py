import hashlib
import json
from pathlib import Path
import pytest
from reel_engine.completed_cleanup import cleanup_completed, cleanup_install_cache


PARENT = 'abcdefghijk-transcript-test'


def put(path, body=b'working media'):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
    return path


def save(path, data):
    put(path, json.dumps(data).encode())


def family(tmp_path, count=1):
    state=tmp_path/'workflow'; parent=state/'jobs'/PARENT
    source=put(parent/'sections/clip-1/source.mkv')
    put(parent/'audio-reference/source.webm')
    put(parent/'selection.json',b'{}')
    clips=[]
    for i in range(count):
        ident=PARENT+f'-clip{i+1}'; folder=state/'jobs'/ident
        final=put(folder/'reel.mp4',b'validated final MP4')
        for name in ('story.mp4','edited.mkv','local-audio.wav','details/page-01.jpg','review/page-01.jpg','partial.mkv.part'):
            put(folder/name)
        for name in ('spec.json','verified-passages.json','edit.json','timing-report.json','review/review.json'):
            put(folder/name,b'{}')
        save(folder/'job.json',{'id':ident,'source_job_id':PARENT,'source':str(source),
            'status':'Needs approval','review_mode':'single-pass','video':str(final),
            'render_sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
            'checks':[{'status':'pass'},{'status':'review'}],
            'approval':{'unchanged':'private saved state'}})
        clips.append({'id':ident})
    save(parent/'job.json',{'id':PARENT,'video_id':'abcdefghijk','transcript_first':True,'clips':clips})
    return state,parent,state/'jobs'/clips[0]['id']


def test_completed_cleanup_keeps_exports_evidence_and_private_state(tmp_path):
    state,parent,clip=family(tmp_path)
    model=put(tmp_path/'data/models/model.bin'); secret=put(tmp_path/'.env')
    cache=put(state/'caption-cache/cues.json'); connection=put(state/'connection.json')
    result=cleanup_completed(state,clip.name)
    assert result['completed'] and result['deleted_bytes']>0
    assert not (parent/'sections/clip-1/source.mkv').exists()
    for name in ('reel.mp4','spec.json','verified-passages.json','edit.json','timing-report.json','review/review.json'):
        assert (clip/name).exists()
    assert all(p.exists() for p in (model,secret,cache,connection))
    job=json.loads((clip/'job.json').read_text())
    assert job['storage_cleanup']['source_removed'] and job['approval']=={'unchanged':'private saved state'}
    again=cleanup_completed(state,clip.name)
    assert again['deleted_bytes']==result['deleted_bytes']


@pytest.mark.parametrize('change',[
    {'status':'Rendering'}, {'status':'Validation failed'}, {'status':'Publishing'},
    {'checks':[{'status':'fail'}]}, {'checks':[]}, {'keep_lossless':True},
    {'review_mode':'careful'}, {'render_sha256':'changed'}, {'publishing':{'provider_post_id':'pending'}}])
def test_failed_active_retained_or_unreviewed_sibling_prevents_cleanup(tmp_path,change):
    state,parent,clip=family(tmp_path,2)
    path=state/'jobs'/(PARENT+'-clip2')/'job.json'; job=json.loads(path.read_text());job.update(change);save(path,job)
    result=cleanup_completed(state,clip.name)
    assert not result['completed'] and (clip/'story.mp4').exists()
    assert (parent/'sections/clip-1/source.mkv').exists()


def test_external_source_shared_references_models_and_cta_are_protected(tmp_path):
    state,parent,clip=family(tmp_path)
    source=parent/'sections/clip-1/source.mkv'
    save(state/'jobs'/'another-job1'/'job.json',{'source':str(source)})
    cookie=put(parent/'cookies.jpg'); model=put(parent/'models/model.npy')
    reference=put(clip/'reference.mp4'); cta=put(clip/'my-cta.mp4')
    save(state/'approved-reference.json',{'video':str(reference)})
    save(state/'output-defaults.json',{'outro':{'path':str(cta)}})
    external=put(tmp_path/'original.mp4')
    path=clip/'job.json';job=json.loads(path.read_text());job['source']=str(external);save(path,job)
    cleanup_completed(state,clip.name,protected_paths=[cookie,model.parent])
    assert all(p.exists() for p in (source,cookie,model,reference,cta,external))


def test_no_cleanup_for_non_owned_local_input(tmp_path):
    state,parent,clip=family(tmp_path)
    p=parent/'job.json';j=json.loads(p.read_text());j['transcript_first']=False;save(p,j)
    assert not cleanup_completed(state,clip.name)['completed']
    assert (clip/'story.mp4').exists()


def test_links_abort_before_any_file_is_removed(tmp_path):
    state,parent,clip=family(tmp_path);outside=put(tmp_path/'outside.mp4')
    try:(clip/'linked.mp4').symlink_to(outside)
    except OSError:pytest.skip('Windows developer-mode/symlink privilege unavailable')
    with pytest.raises(ValueError,match='symlink|reparse'):cleanup_completed(state,clip.name)
    assert outside.exists() and (clip/'story.mp4').exists()


def test_install_cleanup_only_touches_our_explicit_cache(tmp_path):
    state=tmp_path/'workflow'; cached=put(state/'install-cache/http/file.body')
    model=put(tmp_path/'data/models/model.bin');global_cache=put(tmp_path/'global-pip-cache/file.whl')
    package=put(tmp_path/'.venv/site-packages/package.py')
    result=cleanup_install_cache(state)
    assert result['completed'] and not cached.exists()
    assert all(p.exists() for p in (model,global_cache,package))
    assert cleanup_install_cache(state)['deleted_bytes']==0


def test_setup_only_cleans_project_cache_after_successful_dependency_checks():
    script=(Path(__file__).resolve().parents[1]/'tools/setup_local.ps1').read_text()
    assert '--cache-dir $setupPipCache' in script and 'pip cache purge' not in script
    assert script.index('-m pip check')<script.index('reel.py cleanup-install-cache')
    assert 'CPU-only PyTorch required' in script


def test_cleaned_render_reuses_final_or_explains_revision(tmp_path,monkeypatch):
    import reel
    state,parent,clip=family(tmp_path);spec={'candidate':{'start':0,'end':35}}
    spec_path=clip/'spec.json';save(spec_path,spec)
    path=clip/'job.json';job=json.loads(path.read_text())
    job.update(storage_cleanup={'source_removed':True},engine_version=reel.engine_version(),
        edit_spec_hash=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest())
    save(path,job);monkeypatch.setattr(reel,'STATE',state)
    monkeypatch.setattr(reel,'prepare_edit',lambda *a:pytest.fail('Must not reopen deleted source for identical export'))
    assert reel._render(clip.name,spec_path)['video']==job['video']
    save(spec_path,{'candidate':{'start':1,'end':36}})
    with pytest.raises(ValueError,match='reacquire'):reel._render(clip.name,spec_path)


def test_render_hook_waits_for_siblings_then_cleans_family(tmp_path,monkeypatch):
    import reel
    state,parent,clip=family(tmp_path,2); second=state/'jobs'/(PARENT+'-clip2')
    pending=json.loads((second/'job.json').read_text());pending['status']='Rendering';save(second/'job.json',pending)
    monkeypatch.setattr(reel,'STATE',state)
    monkeypatch.setattr(reel.settings,'auto_cleanup_completed',True)
    monkeypatch.setattr(reel,'_render',lambda ident,*a:json.loads((state/'jobs'/ident/'job.json').read_text()))
    result=reel.render(clip.name,clip/'spec.json')
    assert not result['cleanup_result']['completed'] and (clip/'edited.mkv').exists()
    pending['status']='Needs approval';save(second/'job.json',pending)
    result=reel.render(second.name,second/'spec.json')
    assert result['cleanup_result']['completed'] and not (clip/'edited.mkv').exists()
    assert (clip/'reel.mp4').exists() and (second/'reel.mp4').exists()


def test_retention_switch_disables_render_cleanup(tmp_path,monkeypatch):
    import reel
    state,parent,clip=family(tmp_path)
    monkeypatch.setattr(reel,'STATE',state)
    monkeypatch.setattr(reel.settings,'auto_cleanup_completed',False)
    monkeypatch.setattr(reel,'_render',lambda *a:json.loads((clip/'job.json').read_text()))
    reel.render(clip.name,clip/'spec.json')
    assert (clip/'edited.mkv').exists()


def test_locked_file_records_partial_cleanup_without_losing_preview(tmp_path,monkeypatch):
    state,parent,clip=family(tmp_path);original=Path.unlink
    def locked(path,*args,**kwargs):
        if path.name=='local-audio.wav':raise PermissionError('file locked')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',locked)
    with pytest.raises(PermissionError):cleanup_completed(state,clip.name)
    saved=json.loads((clip/'job.json').read_text())
    assert not saved['storage_cleanup']['completed'] and saved['storage_cleanup']['source_removed']
    assert (clip/'reel.mp4').exists() and (clip/'local-audio.wav').exists()
    monkeypatch.setattr(Path,'unlink',original)
    assert cleanup_completed(state,clip.name)['completed']
