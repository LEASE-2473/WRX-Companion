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


import asyncio
import json
import pytest
from app.memory import vector_store, role as role_memory


@pytest.mark.parametrize('kind,endpoint', [('embedding','embeddings'), ('rerank','rerank')])
def test_independent_vector_profiles_use_correct_metadata_and_inference_endpoints(monkeypatch, kind, endpoint):
    calls = []
    def handle(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'data':[{'id':'vector-model'}]})
        if request.url.path.endswith('/embeddings'):
            return httpx.Response(200, json={'data':[{'index':0, 'embedding':[0.1,0.2]}]})
        return httpx.Response(200, json={'results':[{'index':0,'relevance_score':0.9}, {'index':1,'relevance_score':0.1}]})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    async def vector_client():
        return upstream
    monkeypatch.setattr(vector_store, '_client', vector_client)
    async def forbid_llm(*args):
        raise AssertionError('向量模型不得调用LLM客户端')
    monkeypatch.setattr(main, 'fetch_llm_models', forbid_llm)
    monkeypatch.setattr(main, 'test_llm_stream', forbid_llm)
    with TestClient(app) as client:
        prefix = f'/api/provider-profiles/{kind}/vector'
        saved = client.put(prefix, json={'name':'独立向量模型','base_url':f'http://localhost:11434/v1/{endpoint}','model':'vector-model'}).json()
        assert len(saved[kind + '_profiles']) == 1
        assert not saved['llm_profiles']
        assert 'purpose' not in saved[kind + '_profiles'][0]
        assert client.post(prefix + '/models').json()['ok']
        assert str(calls[-1].url) == 'http://localhost:11434/v1/models'
        assert 'authorization' not in calls[-1].headers
        assert client.post(prefix + '/test').json()['ok']
        assert str(calls[-1].url) == f'http://localhost:11434/v1/{endpoint}'
        payload = json.loads(calls[-1].content)
        assert 'messages' not in payload
        assert ('input' in payload) if kind == 'embedding' else ('query' in payload and 'documents' in payload)
        client.put(prefix, json={'name':'独立向量模型','base_url':f'https://example.test/v1/{endpoint}', 'models_url':'https://example.test/catalog/models', 'api_key':'vector-secret','model':''})
        assert client.post(prefix + '/models').json()['ok']
        assert str(calls[-1].url) == 'https://example.test/catalog/models'
        assert calls[-1].headers['authorization'] == 'Bearer vector-secret'
        public = client.put(prefix, json={'name':'独立向量模型','base_url':'https://example.test', 'api_key':'','model':'vector-model'}).json()
        assert public[kind + '_profiles'][0]['api_key'] == ''
        assert provider_store.get_profile(kind, 'vector').api_key == 'vector-secret'
        assert client.post(prefix + '/test').json()['ok']
        assert str(calls[-1].url) == f'https://example.test/v1/{endpoint}'
    asyncio.run(upstream.aclose())


def test_legacy_vector_profile_migration_preserves_ids_keys_and_llm_selection(tmp_path):
    path = tmp_path / 'profiles.json'
    path.write_text(json.dumps({'schema_version':1,'active_llm_profile_id':'chat', 'llm_profiles':[
        {'id':'chat','name':'对话','api_key':'chat-secret','model':'chat-model'},
        {'id':'embed','name':'向量','purpose':'embedding','base_url':'https://example.test/v1/embeddings','api_key':'embed-secret','model':'embed-model'},
        {'id':'rank','name':'精排','purpose':'rerank','base_url':'https://example.test/v1/rerank','api_key':'rank-secret','model':'rank-model'}]}), encoding='utf-8')
    from app.models import ProviderProfilesState
    unselected = ProviderProfilesState.model_validate({'llm_profiles':[{'id':'chat','name':'对话'}], 'active_llm_profile_id':None})
    assert unselected.active_llm_profile_id is None
    state = provider_store.load_provider_profiles(path)
    assert [p.id for p in state.llm_profiles] == ['chat']
    assert state.embedding_profiles[0].id == 'embed'
    assert state.embedding_profiles[0].api_key == 'embed-secret'
    assert state.rerank_profiles[0].id == 'rank'
    assert state.rerank_profiles[0].api_key == 'rank-secret'
    assert state.active_llm_profile_id == 'chat'
    provider_store.save_provider_profiles(state, path)
    assert provider_store.load_provider_profiles(path) == state
    public = json.dumps(provider_store.public_provider_profiles(state))
    assert not any(secret in public for secret in ('chat-secret','embed-secret','rank-secret'))
    with pytest.raises(ValueError):
        provider_store.upsert_provider_profile('llm', {'id':'bad','name':'错误','purpose':'embedding'}, path)
    with pytest.raises(KeyError):
        provider_store.get_profile('llm', 'embed', path)


def test_memory_uses_independent_vector_profiles_and_protects_bound_deletion():
    with TestClient(app) as client:
        client.put('/api/provider-profiles/embedding/embed', json={'name':'向量','base_url':'https://example.test/v1','model':'embed','api_key':'embed-secret'})
        client.put('/api/provider-profiles/rerank/rank', json={'name':'精排','base_url':'https://example.test','model':'rank','api_key':'rank-secret'})
        config = client.get('/api/role-memory/settings').json()
        config.update(embedding_profile_id='embed', rerank_profile_id='rank')
        response = client.put('/api/role-memory/settings', json=config)
        assert response.status_code == 200
        actual = role_memory.settings()
        assert actual.vector.api_key == 'embed-secret'
        assert actual.vector.rerank_key == 'rank-secret'
        assert actual.vector.rerank_url == 'https://example.test/v1/rerank'
        assert client.delete('/api/provider-profiles/embedding/embed').status_code == 409
        assert client.delete('/api/provider-profiles/rerank/rank').status_code == 409
        config['embedding_profile_id'] = 'rank'
        assert client.put('/api/role-memory/settings', json=config).status_code == 404



def test_legacy_vector_binding_survives_read_and_save_migration():
    from app.chat import store
    provider_store.PROVIDER_PROFILES_FILE.write_text(json.dumps({'llm_profiles':[
        {'id':'legacy-embed','name':'旧向量','purpose':'embedding','base_url':'https://example.test/v1/embeddings','api_key':'old-vector-key','model':'old-vector'},
        {'id':'legacy-rank','name':'旧精排','purpose':'rerank','base_url':'https://example.test/v1/rerank','api_key':'old-rank-key','model':'old-rank'}]}), encoding='utf-8')
    with TestClient(app) as client:
        store.save_setting('role_memory', {'profiles_migrated':True, 'embedding_profile_id':'legacy-embed','rerank_profile_id':'legacy-rank','vector':{'enabled':True,'rerank_enabled':True}})
        config = client.get('/api/role-memory/settings').json()
        assert config['embedding_profile_id'] == 'legacy-embed'
        assert config['rerank_profile_id'] == 'legacy-rank'
        assert config['vector']['api_key'] == ''
        assert client.put('/api/role-memory/settings', json=config).status_code == 200
        actual = role_memory.settings()
        assert actual.vector.api_key == 'old-vector-key'
        assert actual.vector.rerank_key == 'old-rank-key'
        state = provider_store.load_provider_profiles()
        provider_store.save_provider_profiles(state)
        document = json.loads(provider_store.PROVIDER_PROFILES_FILE.read_text(encoding='utf-8'))
        assert document['schema_version'] == 2
        assert document['llm_profiles'] == []
        assert document['embedding_profiles'][0]['id'] == config['embedding_profile_id']
        assert document['rerank_profiles'][0]['id'] == config['rerank_profile_id']


def test_invalid_migration_does_not_replace_existing_profile_file(tmp_path):
    path = tmp_path / 'profiles.json'
    raw = json.dumps({'llm_profiles':[{'id':'same','name':'旧','purpose':'embedding'}], 'embedding_profiles':[{'id':'same','name':'新'}]})
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        provider_store.upsert_provider_profile('llm', {'id':'chat','name':'新对话'}, path)
    assert path.read_text(encoding='utf-8') == raw
