"""离线接管基线：使用临时存储与模拟 Provider，不调用付费 API。"""
import asyncio

from fastapi.testclient import TestClient

from app.chat import store as companion_store
from app.memory import vector_store as vector_memory_store
from app.main import app
from app.models import ChatMessage, Lorebook, LorebookEntry, LlmProviderProfile, ProviderProfilesState
from app.prompting.compiler import compile_prompt
from app.prompting.preset_store import default_wrx_preset
from app.providers.profiles import public_provider_profiles


def test_static_page_loads():
    with TestClient(app) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert '/static/settings/app.js' in response.text


def test_conversations_round_trip_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv('WRX_DB_PATH', str(tmp_path / 'companion.sqlite3'))
    with TestClient(app) as client:
        first = client.post('/api/conversations').json()
        second = client.post('/api/conversations').json()
        messages = [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '我在'}]
        companion_store.begin_turn(first['id'], 'baseline', '你好', 'Asia/Shanghai', 'web', 'OFF')
        from app.models import TokenUsage
        companion_store.finish_turn('baseline', '我在', TokenUsage(), [], [], {})
        assert client.put('/api/conversations/' + first['id'], json={'messages': messages}).status_code == 405
        rows = {cid: client.get('/api/conversations/' + cid).json() for cid in [first['id'], second['id']]}
        assert [{'role': m['role'], 'content': m['content']} for m in rows[first['id']]['messages']] == messages
        assert rows[second['id']]['messages'] == []


def test_lore_activation_history_and_vector_injection():
    book = Lorebook(id='book', name='测试', entries=[
        LorebookEntry(id='always', title='常驻', constant=True, content='常驻设定'),
        LorebookEntry(id='hit', title='命中', keys=['咖啡'], content='喜欢拿铁'),
        LorebookEntry(id='miss', title='不命中', keys=['火星'], content='未触发设定'),
    ])
    history = [ChatMessage(role='user', content='旧消息'), ChatMessage(role='assistant', content='上一条')]
    result = compile_prompt(default_wrx_preset(), book, 1, history, '喝咖啡吗', [{'content': '上周去过咖啡店'}])
    contents = [message.content for message in result.messages]
    assert '旧消息' not in contents
    assert '上一条' in contents and '喝咖啡吗' in contents
    assert '常驻设定' in contents and '喜欢拿铁' in contents
    assert '未触发设定' not in contents
    assert any('上周去过咖啡店' in content for content in contents)
    assert len(history) == 2


def test_provider_public_view_hides_key_without_mutating_source():
    state = ProviderProfilesState(llm_profiles=[LlmProviderProfile(id='test', name='测试', api_key='fake-private-value')])
    public = public_provider_profiles(state)
    assert public['llm_profiles'][0]['api_key'] == ''
    assert public['llm_profiles'][0]['api_key_set'] is True
    assert state.llm_profiles[0].api_key == 'fake-private-value'


def test_vector_import_embedding_and_retrieval(tmp_path, monkeypatch):
    path = tmp_path / 'memory.json'
    state, library = vector_memory_store.import_vector_library('测试', '咖啡\n---\n散步', path=path)
    state.config.enabled = True
    state.config.threshold = 0.5
    vector_memory_store.save_vector_memory(state, path)

    async def fake_embeddings(texts, config):
        return [[1.0, 0.0] if text == '咖啡' else [0.0, 1.0] for text in texts]

    monkeypatch.setattr(vector_memory_store, 'get_embeddings', fake_embeddings)
    state, report = asyncio.run(vector_memory_store.vectorize_library(library.id, path))
    assert report['completed'] == 2
    found = asyncio.run(vector_memory_store.retrieve_vector_memories('咖啡', state))
    assert [item['content'] for item in found] == ['咖啡']
    state, report = asyncio.run(vector_memory_store.vectorize_library(library.id, path))
    assert report['completed'] == 0


def test_missing_conversation_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv('WRX_DB_PATH', str(tmp_path / 'companion.sqlite3'))
    with TestClient(app) as client:
        assert client.get('/api/conversations/missing').status_code == 404
