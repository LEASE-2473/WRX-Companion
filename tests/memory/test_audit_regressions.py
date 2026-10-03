"""覆盖目录审查发现的真实故障路径，全部使用隔离存储和模拟供应商。"""
import asyncio
import json
import httpx
import pytest
from app.chat import store
from app.memory import role, vector_routes, vector_store
from app.models import VectorMemoryConfig, VectorMemoryState, VectorLibrary, VectorChunk


@pytest.mark.parametrize('changed_model', [False, True])
def test_cold_diary_falls_back_without_usable_embedding(monkeypatch, changed_model):
    conv = store.create_conversation()
    config = role.settings()
    config.vector.enabled = True
    config.vector.api_url = 'https://audit.invalid'
    config.vector.model = 'before'
    role.save_settings(config.model_dump())
    record = role.put('diary', 'default', conv.id, {'content': '需要记住的事实'})
    async def embed(*args): return [[1.0, 0.0]]
    monkeypatch.setattr(role, 'get_embeddings', embed)
    asyncio.run(role.switch('default', record['id'], 'cold'))
    assert record['id'] not in [r['id'] for r in role.hot_context('default', conv.id)[0]]
    config = role.settings()
    if changed_model: config.vector.model = 'after'
    else: config.vector.enabled = False
    role.save_settings(config.model_dump())
    hot = role.hot_context('default', conv.id)
    assert record['id'] in [r['id'] for r in hot[0]]
    assert any('需要记住的事实' in m.content for m in hot[1])
    assert asyncio.run(role.recall('default', conv.id, '事实')) == []


@pytest.mark.parametrize('name,args', [
    ('test_vector_memory_provider', ()), ('vector_memory_models', ({},)),
    ('test_vector_memory_rerank', ()), ('run_vectorization', ('library',)),
])
def test_vector_errors_are_redacted(monkeypatch, name, args):
    state = VectorMemoryState()
    state.config.api_key = state.config.rerank_key = 'audit-secret'
    monkeypatch.setattr(vector_routes, 'freeze_vector_memory', lambda: state)
    async def fail(*args): raise ValueError('provider failure audit-secret')
    for attr in ('get_embeddings', 'fetch_vector_models', 'get_rerank_scores', 'vectorize_library'):
        monkeypatch.setattr(vector_routes, attr, fail)
    from fastapi import HTTPException
    if name == 'run_vectorization':
        with pytest.raises(HTTPException) as error:
            asyncio.run(getattr(vector_routes, name)(*args))
        assert error.value.status_code == 502
        result = error.value.detail
    else:
        result = asyncio.run(getattr(vector_routes, name)(*args))
        assert result['ok'] is False
    assert 'audit-secret' not in str(result)


def test_rerank_scores_every_candidate_before_final_limit(monkeypatch):
    config = VectorMemoryConfig(enabled=True, rerank_enabled=True,
        rerank_url='https://audit.invalid/rerank', rerank_model='fake', max_results=2)
    state = VectorMemoryState(config=config, libraries=[VectorLibrary(id='audit', name='audit',
        chunks=[VectorChunk(id=str(i), content=str(i), vector=[1.0, 0.0]) for i in range(4)])])
    async def embed(*args): return [[1.0, 0.0]]
    monkeypatch.setattr(vector_store, 'get_embeddings', embed)
    def handler(request):
        body = json.loads(request.content)
        assert body['top_n'] == len(body['documents']) == 4
        return httpx.Response(200, json={'results': [
            {'index': i, 'relevance_score': (i + 1) / 5} for i in range(body['top_n'])]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(vector_store, '_HTTP_CLIENT', client)
            return await vector_store.retrieve_vector_memories('事实', state)
    found = asyncio.run(run())
    assert [r['chunk_id'] for r in found] == ['3', '2']
    assert all(r['rerank_status'] == 'applied' for r in found)
