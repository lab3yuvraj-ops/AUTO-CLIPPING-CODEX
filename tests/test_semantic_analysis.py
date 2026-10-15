import pytest
from reel_engine import semantic_analysis as semantic
from reel_engine.config import Settings


def test_disabled_provider_never_calls_network(tmp_path,monkeypatch):
    from reel_engine import gemini_free
    monkeypatch.setattr(gemini_free.httpx,'post',lambda *a,**k:pytest.fail('No request'))
    r=semantic.analyze({}, {}, {}, tmp_path,settings=Settings(_env_file=None))
    assert r['status']=='needs_review' and r['api_calls_this_run']==0


@pytest.mark.parametrize('endpoint',['https://api.openai.com/chat','http://localhost:8080/chat','https://other.example/chat'])
def test_legacy_providers_rejected(tmp_path,endpoint):
    with pytest.raises(ValueError,match='disabled'):
        semantic.analyze({}, {}, {}, tmp_path,endpoint=endpoint,model='old',allow_remote=True)
