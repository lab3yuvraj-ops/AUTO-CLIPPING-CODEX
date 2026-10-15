import subprocess
import shutil

from PIL import Image
import pytest

from reel_engine import fast_gate as gate
from reel_engine.errors import StageError


def evidence(count=1, strategy='fixed'):
    return {'visual_samples_sha256':'abc','overview_hashes':{'page1':'hash1'},'reviewed_by':'Codex',
            'live_action':True,'animated':False,'faces_reliable':True,'speakers_reliable':True,
            'speaker_count':count,'chosen_strategy':strategy,'confidence':.95,
            'classification':'multi-speaker dialogue' if strategy=='speaker-switching' else 'single/dominant-presenter',
            'evidence':'Reviewed all six actual source samples; visible identities and proposed composition are feasible.'}


def evaluate(visual, captions=True, audio=None):
    return gate.evaluate_gate(captions, audio, visual, 'abc', {'page1':'hash1'})


def test_gate_requires_actual_hash_bound_visual_review():
    assert evaluate(evidence())['eligible']
    assert evaluate(None)['status'] == 'pending'
    visual = evidence()
    visual['overview_hashes'] = {'page1':'changed'}
    assert 'overview_pages' in evaluate(visual)['failed_checks']


@pytest.mark.parametrize('count,strategy', [(1,'fixed'),(2,'face-tracked'),(3,'speaker-switching'),(4,'speaker-switching'),(5,'fixed')])
def test_multiple_speakers_and_all_strategies_are_supported(count, strategy):
    report = evaluate(evidence(count,strategy), audio={'known':False,'dominant_fraction':.2,'overlap_fraction':.8})
    assert report['eligible'] and report['chosen_strategy'] == strategy
    assert report['speaker_count'] == count
    assert 'dominant_speaker' not in report['checks'] and 'low_overlap' not in report['checks']


@pytest.mark.parametrize('field,value,failed', [
    ('animated',True,'live_action'),('classification','unknown','passage_classification'),
    ('chosen_strategy','automatic','tracking_strategy'),('evidence','','explicit_review'),
    ('reviewed_by','automatic-detector','explicit_review')])
def test_unreliable_visual_evidence_rejects(field, value, failed):
    visual = evidence()
    visual[field] = value
    report = evaluate(visual)
    assert not report['eligible'] and failed in report['failed_checks']


def test_missing_captions_and_uncertain_identity_do_not_reject_reviewed_passage():
    visual=evidence(6,'speaker-switching');visual['faces_reliable']=False;visual['confidence']=.5
    report=evaluate(visual,captions=False)
    assert report['eligible'] and report['requires_stable_context'] and report['editorial_warnings']


def test_frame_cap_is_six_even_for_long_sources():
    assert len(gate.sample_times(7200)) == 6
    assert gate.sample_times(6) == [.5,1.5,2.5,3.5,4.5,5.5]


def test_samples_are_six_actual_hash_bound_frames_and_no_speaker_model(monkeypatch, tmp_path):
    calls = []
    info = {'id':'abcdefghijk','duration':100,'formats':[{'format_id':'low','vcodec':'h264','height':480,'url':'https://example.test/?private=secret'}]}
    def seek(fmt, timestamp, path):
        calls.append(timestamp)
        Image.new('RGB',(640,360),'gray').save(path)
        return timestamp+.01
    monkeypatch.setattr(gate,'_seek_frame',seek)
    monkeypatch.setattr(gate,'_faces',lambda p: [])
    report = gate.gather_visual_samples(info,tmp_path)
    assert len(calls) == 6 and len(report['frames']) == 6
    assert not report['cached'] and len(report['page_files']) == 1
    saved = (tmp_path/'visual-samples.json').read_text()
    assert 'secret' not in saved and 'example.test' not in saved
    assert report['overview_hashes'] and report['visual_samples_sha256']
    assert gate.gather_visual_samples(info,tmp_path)['cached'] and len(calls) == 6


def test_remote_seek_timeout_does_not_leak_url(monkeypatch,tmp_path):
    def fail(args, **kwargs):
        raise subprocess.TimeoutExpired(args,35,stderr='private signed URL')
    monkeypatch.setattr(gate.subprocess,'run',fail)
    with pytest.raises(StageError) as error:
        gate._seek_frame({'url':'https://example.test/?token=secret'},30,tmp_path/'frame.jpg')
    assert 'secret' not in str(error.value) and '35-second' in str(error.value)


def test_stream_quality_choice_is_only_proxy_quality():
    info = {'formats':[{'vcodec':'h264','height':2160,'url':'https://a'},
                       {'vcodec':'h264','height':480,'url':'https://b'},
                       {'vcodec':'none','height':480,'url':'https://c'}]}
    assert gate._sample_format(info)['url'] == 'https://b'


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg is not installed')
def test_actual_local_seek_keeps_original_source_timestamp(tmp_path):
    source = tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=25:duration=9',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True,timeout=20)
    stamp = gate._seek_frame({'url':str(source)},7.5,tmp_path/'frame.jpg')
    assert abs(stamp-7.5)<.05


def test_remote403_fallback_samples_complete_local_proxy_without_second_download(monkeypatch,tmp_path):
    proxy = tmp_path/'source.mkv'
    proxy.write_bytes(b'accepted proxy')
    info = {'id':'abcdefghijk','duration':100,'formats':[]}
    monkeypatch.setattr(gate,'probe',lambda p: {'streams':[{'codec_type':'video','height':480},{'codec_type':'audio'}],'format':{'duration':'100'}})
    calls = []
    def seek(fmt, timestamp, path):
        calls.append(fmt['url'])
        Image.new('RGB',(640,360),'gray').save(path)
        return timestamp+.01
    monkeypatch.setattr(gate,'_seek_frame',seek)
    monkeypatch.setattr(gate,'_faces',lambda p: [])
    result = gate.gather_visual_samples(info,tmp_path/'samples',local_proxy=proxy)
    assert result['route'] == 'local_proxy_after_remote403'
    assert len(calls) == 6 and all(url == str(proxy.resolve()) for url in calls)
    assert result['sampling_seconds'] >= 0 and 'only after' in result['overlap_note']
    assert result['local_proxy_sha256'] == gate.file_hash(proxy)


def test_local_proxy_partial_not_accepted_for_frame_sampling(tmp_path):
    proxy = tmp_path/'source.mkv.part'
    proxy.write_bytes(b'partial')
    with pytest.raises(StageError,match='never a partial'):
        gate.gather_visual_samples({'id':'abcdefghijk','duration':100},tmp_path/'samples',local_proxy=proxy)
