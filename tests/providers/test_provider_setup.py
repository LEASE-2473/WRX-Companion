from fastapi.testclient import TestClient
from app.main import app
from app.providers import routes as main
from app.providers import profiles as provider_store
import httpx
from app.providers.client import OpenAICompatibleLlm


def test_missing_profile_is_configuration_failure():
    with TestClient(app) as client:
        for endpoint in ('llm/missing/models', 'llm/missing/connection', 'llm/missing/test', 'stt/missing/test', 'tts/missing/test'):
            result = client.post('/api/provider-profiles/' + endpoint).json()
            assert result['ok'] is False
            assert result['stages']['configuration']['status'] == 'failed'
            assert result['stages']['network_auth']['status'] == 'not_completed'


def test_saved_draft_fetches_models_without_model_and_preserves_key(monkeypatch):
    calls = []
    async def fake_models(profile):
        calls.append(profile)
        return ['deepseek-chat', 'deepseek-reasoner']
    monkeypatch.setattr(main, 'fetch_llm_models', fake_models)
    with TestClient(app) as client:
        client.put('/api/provider-profiles/llm/existing', json=dict(name='Existing', api_key='fake-existing', model='test'))
        original_active = client.get('/api/provider-profiles').json()['active_llm_profile_id']
        draft = dict(name='DeepSeek', base_url='https://api.deepseek.com', api_key='fake-test-key', model='')
        saved = client.put('/api/provider-profiles/llm/draft', json=draft).json()
        assert saved['active_llm_profile_id'] == original_active
        assert all(not item['api_key'] for item in saved['llm_profiles'])
        result = client.post('/api/provider-profiles/llm/draft/models').json()
        assert result['ok'] and result['models'] == ['deepseek-chat', 'deepseek-reasoner']
        assert calls[0].base_url == draft['base_url'] and calls[0].api_key == 'fake-test-key'
        draft.update(api_key='', model='deepseek-chat')
        client.put('/api/provider-profiles/llm/draft', json=draft)
        assert provider_store.get_profile('llm', 'draft').api_key == 'fake-test-key'


def test_connection_and_model_list_only_issue_one_metadata_get_each(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={'data': [{'id': 'flash'}, {'id': 'pro'}]})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(OpenAICompatibleLlm, 'client', lambda self: upstream)
    with TestClient(app) as client:
        client.put('/api/provider-profiles/llm/metadata', json=dict(name='Metadata', base_url='https://example.test/v1', api_key='fake-key', model=''))
        for endpoint in ('connection', 'models'):
            count = len(calls)
            result = client.post('/api/provider-profiles/llm/metadata/' + endpoint).json()
            assert result['ok']
            assert result['models'] == ['flash', 'pro']
            assert len(calls) == count + 1
            assert calls[-1].method == 'GET'
            assert str(calls[-1].url) == 'https://example.test/v1/models'
            assert calls[-1].content == b''
