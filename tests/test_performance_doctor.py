import json
from types import SimpleNamespace
from reel_engine.performance import measure,summarize
from reel_engine.doctor import check


def test_measure_records_failures_without_arguments_or_secrets(tmp_path):
    try:
        with measure(tmp_path,'render'):
            raise RuntimeError('private payload must not enter the log')
    except RuntimeError:pass
    d=summarize(tmp_path)
    assert d['full_render_attempts']==1 and not d['records'][0]['succeeded']
    assert d['records'][0]['wall_seconds']>=0
    assert 'private payload' not in (tmp_path/'performance-metrics.jsonl').read_text()


def test_doctor_never_exposes_credentials_or_needs_network(tmp_path):
    settings=SimpleNamespace(local_device='cpu',zernio_api_key='secret-key',zernio_instagram_id='secret-id',
                             semantic_vision_url='',semantic_vision_model='',local_model_dir=tmp_path/'models')
    d=check(tmp_path,settings)
    assert d['instagram_configured'] and d['cpu_only'] and not d['ready_for_media']
    assert 'secret-key' not in json.dumps(d) and 'secret-id' not in json.dumps(d)
