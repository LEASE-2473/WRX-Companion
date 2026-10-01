import asyncio
from datetime import timedelta
import json
import pytest
from fastapi.testclient import TestClient
from app import companion_store as store, role_memory as memory
from app.main import app
from app.models import TokenUsage

def record(content='记得一起旅行', tags=None):
    return {'content': content, 'tags': tags or ['旅行'], 'occurred_at': store.utcnow().isoformat()}

def test_scope_and_hot_budget():
    a = store.create_conversation()
    b = store.create_conversation()
    local = memory.put('event', 'default', a.id, record())
    shared = memory.put('diary', 'default', a.id, record() | {'scope': 'character'})
    records, messages, usage = memory.hot_context('default', b.id)
    assert [r['id'] for r in records] == [shared['id']]
    assert usage['estimated_tokens'] > 0 and usage['by_kind']['event'] == 0
    assert local['id'] in [r['id'] for r in memory.hot_context('default', a.id)[0]]

def test_cold_failure_edit_and_model_change(monkeypatch):
    conv = store.create_conversation()
    config = memory.settings(); config.vector.enabled = True; config.vector.api_url = 'https://example.test'; memory.save_settings(config.model_dump())
    r = memory.put('diary', 'default', conv.id, record())
    async def fail(*args): raise ValueError('offline')
    monkeypatch.setattr(memory, 'get_embeddings', fail)
    with pytest.raises(ValueError): asyncio.run(memory.switch('default', r['id'], 'cold'))
    assert memory.all_records('default')[0]['mode'] == 'hot'
    async def embed(*args): return [[1.0, 0.0]]
    monkeypatch.setattr(memory, 'get_embeddings', embed)
    asyncio.run(memory.switch('default', r['id'], 'cold'))
    assert memory.all_records('default')[0]['mode'] == 'cold'
    edited = memory.put('diary', 'default', conv.id, record('新内容'), r['id'])
    assert edited['mode'] == 'hot' and edited['vector'] is None

def test_external_and_activity_constraints():
    conv = store.create_conversation()
    with pytest.raises(ValueError): memory.put('activity', 'default', conv.id, record())
    with pytest.raises(ValueError): memory.put('event', 'default', conv.id, record(tags=['a','b']))
    books = asyncio.run(memory.import_book('default', conv.id, '朋友', '第一片\n---\n第二片'))
    assert len(books) == 2 and all(r['mode'] == 'cold' for r in books)
    with pytest.raises(ValueError): asyncio.run(memory.switch('default', books[0]['id'], 'hot'))

def test_api_keys_redacted_and_retained():
    config = memory.settings(); config.presets['diary'].llm.api_key = 'private-test'; config.vector.api_key = 'embed-test'
    memory.save_settings(config.model_dump())
    public = memory.public_settings()
    assert 'private-test' not in json.dumps(public) and public['presets']['diary']['llm']['api_key_set']
    memory.save_settings(public)
    assert memory.settings().presets['diary'].llm.api_key == 'private-test'

def test_independent_diary_idempotence(monkeypatch):
    conv = store.create_conversation()
    date = store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    store.begin_turn(conv.id, 'source-turn', '今天约好去旅行', conv.timezone, 'web', 'OFF')
    store.finish_turn('source-turn', '好的', TokenUsage(), [], [], {})
    config = memory.settings(); config.presets['diary'].llm.model = 'diary-only'; memory.save_settings(config.model_dump())
    calls = []
    class Fake:
        last_usage = TokenUsage(input_tokens=10, output_tokens=5)
        def __init__(self, profile): assert profile.model == 'diary-only'
        def set_generation_parameters(self, value): pass
        async def complete(self, messages):
            calls.append(messages)
            return '{"content":"今天我们约好旅行。","tags":["旅行"]}'
    monkeypatch.setattr(memory, 'OpenAICompatibleLlm', Fake)
    assert asyncio.run(memory.generate('diary', conv.id, date))['status'] == 'done'
    assert asyncio.run(memory.generate('diary', conv.id, date))['status'] == 'already_processed'
    assert len(calls) == 1 and len(memory.all_records('default')) == 1
    assert len(store.get_conversation(conv.id).messages) == 2
    assert memory.all_records('default')[0]['sources']

def test_route_validation_and_safety():
    conv = store.create_conversation()
    with TestClient(app) as client:
        response = client.post('/api/role-memory/default/event', json=record() | {'conversation_id': conv.id})
        assert response.status_code == 200
        assert client.post('/api/role-memory/default/activity', json=record() | {'conversation_id': conv.id}).status_code == 422
        response = client.get('/api/role-memory/default', params={'conversation_id': conv.id})
        assert response.status_code == 200 and len(response.json()['records']) == 1

def test_auto_cold_and_manual_hot(monkeypatch):
    conv = store.create_conversation()
    config = memory.settings(); config.vector.enabled = True; config.vector.api_url = 'https://example.test'; memory.save_settings(config.model_dump())
    old = (store.utcnow() - timedelta(days=8)).isoformat()
    a = memory.put('diary', 'default', conv.id, record() | {'occurred_at': old})
    b = memory.put('diary', 'default', conv.id, record() | {'occurred_at': old, 'injection_mode': 'hot'})
    async def embed(*args): return [[1, 0]]
    monkeypatch.setattr(memory, 'get_embeddings', embed)
    asyncio.run(memory.maintenance())
    result = {r['id']: r for r in memory.all_records('default')}
    assert result[a['id']]['mode'] == 'cold' and result[b['id']]['mode'] == 'hot'

def test_recall_scope_model_and_budget(monkeypatch):
    conv = store.create_conversation(); other = store.create_conversation()
    config = memory.settings(); config.vector.enabled = True; config.vector.api_url = 'https://example.test'; memory.save_settings(config.model_dump())
    a = memory.put('event', 'default', conv.id, record())
    b = memory.put('event', 'default', other.id, record('其他会话秘密'))
    async def embed(*args): return [[1, 0]]
    monkeypatch.setattr(memory, 'get_embeddings', embed)
    asyncio.run(memory.switch('default', a['id'], 'cold')); asyncio.run(memory.switch('default', b['id'], 'cold'))
    seen = []
    async def retrieve(query, state):
        seen.extend(c.id for lib in state.libraries for c in lib.chunks)
        return [{'content':'旅行约定','chunk_id':a['id']}]
    monkeypatch.setattr(memory, 'retrieve_vector_memories', retrieve)
    assert asyncio.run(memory.recall('default', conv.id, '旅行'))
    assert seen == [a['id']]
    config.vector.model = 'new-model'; memory.save_settings(config.model_dump()); seen.clear()
    asyncio.run(memory.recall('default', conv.id, '旅行')); assert seen == []

def test_invalid_batch_does_not_partially_write(monkeypatch):
    conv = store.create_conversation(); date = store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    store.begin_turn(conv.id, 'batch-source', '约好了旅行和聚会', conv.timezone, 'web', 'OFF')
    store.finish_turn('batch-source', '好', TokenUsage(), [], [], {})
    config = memory.settings(); config.presets['event'].llm.model = 'event'; memory.save_settings(config.model_dump())
    class Fake:
        def __init__(self, profile): pass
        def set_generation_parameters(self, value): pass
        async def complete(self, messages): return '{"records":[{"content":"旅行","tags":["旅行"]},{"content":"聚会","tags":[]}]}'
    monkeypatch.setattr(memory, 'OpenAICompatibleLlm', Fake)
    with pytest.raises(ValueError): asyncio.run(memory.generate('event', conv.id, date))
    assert not memory.all_records('default')
    assert memory.job_status('default')[0]['status'] == 'error'

def test_activity_fact_saved_even_without_llm():
    conv = store.create_conversation()
    first = asyncio.run(memory.record_activity(conv.id, 'actual-activity', '阅读论坛帖子', {'status':'completed','title':'实际返回标题'}))
    assert first['note_status'] == 'error' and first['execution_result']['status'] == 'completed'
    second = asyncio.run(memory.record_activity(conv.id, 'actual-activity', '阅读论坛帖子', {'status':'completed'}))
    assert second['id'] == first['id'] and len(memory.all_records('default')) == 1

def test_hot_history_respects_depth_and_zero():
    from app.runtime_settings_store import save_runtime_settings
    from app.models import RuntimeSettings, TokenUsage
    conv = store.create_conversation()
    store.begin_turn(conv.id, 'history-test', '历史用户', 'Asia/Shanghai', 'web', 'OFF')
    store.finish_turn('history-test', '历史回复', TokenUsage(), [], [], {})
    memory.put('diary', 'default', conv.id, record())
    save_runtime_settings(RuntimeSettings(history_depth=1))
    usage = memory.hot_context('default', conv.id)[2]
    assert usage['history_count'] == 1 and usage['by_kind']['history'] > 0
    save_runtime_settings(RuntimeSettings(history_depth=0))
    without = memory.hot_context('default', conv.id)[2]
    assert without['history_count'] == 0 and without['by_kind']['history'] == 0
    assert usage['estimated_tokens'] - without['estimated_tokens'] == usage['by_kind']['history']


def test_recall_does_not_truncate_long_ranked_result(monkeypatch):
    conv = store.create_conversation()
    async def ranked(*args):
        return [{'content': '长记忆' * 4000, 'id': 'long'}]
    monkeypatch.setattr(memory, 'retrieve_vector_memories', ranked)
    result = asyncio.run(memory.recall('default', conv.id, '长记忆'))
    assert len(result) == 1 and len(result[0]['content']) == 12000


def test_diary_date_without_occurrence_time():
    conv=store.create_conversation()
    r=memory.put('diary','default',conv.id,{'content':'今天的日记','tags':['旅行'],'date':'2026-10-01'})
    r=next(x for x in memory.all_records('default') if x['id']==r['id'])
    assert r['date']=='2026-10-01' and 'occurred_at' not in r
    assert '2026-10-01' in memory.serialize(r)
