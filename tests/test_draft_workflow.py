import json
import pytest
import reel


def test_draft_reuses_metadata_and_requires_actual_source(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    info={'id':'testvideo01','duration':60,'availability':'public','channel_id':'owner','title':'Story'}
    requests=[]
    monkeypatch.setattr(reel.youtube,'ytdlp',lambda *a,**k:requests.append(a) or json.dumps(info))
    def fetch(ident,root,duration,info=None):
        assert info['title']=='Story'
        return {'provider':'youtube-captions','words':[],'cues':[{'start':0,'end':60,'text':'draft'}]}
    monkeypatch.setattr('reel_engine.youtube_transcript.fetch_caption_draft',fetch)
    result=reel.draft('https://youtu.be/testvideo01',clips=1)
    job=reel.read(tmp_path/'jobs/testvideo01/job.json')
    assert not job.get('source') and job['requested_clips']==1
    assert result['metadata']['duration']==60
    assert len(requests)==1
    assert reel.draft('https://youtu.be/testvideo01')['checkpoint_reused']
    assert len(requests)==1


def test_draft_preserves_existing_preview_and_rejects_scheduled_upload(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    path=tmp_path/'jobs/testvideo01/job.json'
    reel.save(path,{'id':'testvideo01','status':'Needs approval','video':'approved-preview.mp4'})
    with pytest.raises(ValueError,match='preserved'):reel.draft('https://youtu.be/testvideo01')
    assert reel.read(path)['status']=='Needs approval'
    monkeypatch.setattr(reel.youtube,'ytdlp',lambda *a,**k:json.dumps({'duration':60,'live_status':'is_upcoming'}))
    with pytest.raises(ValueError,match='released'):reel.draft('https://youtu.be/testvideo02')
    assert not (tmp_path/'jobs/testvideo02/job.json').exists()
