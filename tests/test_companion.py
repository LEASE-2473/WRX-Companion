import asyncio
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import companion_store as store, companion_core, heartbeat, search, provider_store, providers
from app.companion_core import core
from app.main import app
from app.models import Character, HeartbeatSettings, SearchSettings, TokenUsage, ChatMessage, LlmProviderProfile, TtsProviderProfile, SttProviderProfile
from app.usage import read_usage


class FakeLlm:
    def __init__(self, reply='你好，**原文**', decision='{"search":false}', delay=0):
        self.reply = reply
        self.decision = decision
        self.delay = delay
        self.last_usage = TokenUsage(input_tokens=100, cached_tokens=80, output_tokens=12)
        self.profile = SimpleNamespace(api_key='fake-secret')
        self.calls = []

    def set_generation_parameters(self, params):
        pass

    async def complete(self, messages):
        self.calls.append(messages)
        return self.decision

    async def stream_complete(self, messages):
        self.calls.append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        yield self.reply


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(core, 'llm_for', lambda *args: fake)
    return fake


def events(response):
    assert response.status_code == 200, response.text
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]


def send(client, cid, content='你好', rid=None, mode='OFF'):
    return client.post(f'/api/conversations/{cid}/messages/stream', json={
        'request_id': rid or str(uuid4()), 'content': content, 'timezone': 'Asia/Shanghai', 'search_mode': mode,
    })


def test_text_usage_persists_without_stt_tts_and_replay(llm):
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        rid = str(uuid4())
        result = events(send(client, cid, rid=rid))[-1]
        assert result['type'] == 'complete'
        assert result['usage'] == {'input_tokens': 100, 'cached_tokens': 80, 'output_tokens': 12}
        records = client.get(f'/api/conversations/{cid}').json()['messages']
        assert len(records) == 2
        assert records[-1]['content'] == '你好，**原文**'
        assert records[-1]['timestamp'].endswith('+00:00')
        assert records[-1]['local_datetime'].endswith('+08:00')
        assert records[-1]['usage']['cached_tokens'] == 80
        replay = events(send(client, cid, rid=rid))[-1]
        assert replay['replayed'] is True
        assert len(llm.calls) == 1
        assert len(store.get_conversation(cid).messages) == 2
        assert send(client, cid, content='另一条', rid=rid).status_code == 409


def test_character_binding_and_history_isolation(llm):
    with TestClient(app) as client:
        char = client.post('/api/characters', json={'name': '小月', 'personality': '温柔', 'persona': '喜欢猫'}).json()
        first = client.post('/api/conversations', json={'character_id': char['id']}).json()['id']
        second = client.post('/api/conversations').json()['id']
        events(send(client, first, content='只有小月知道的秘密'))
        events(send(client, second))
        second_context = '\n'.join(m.content for m in llm.calls[-1])
        assert '只有小月知道的秘密' not in second_context
        assert any('小月' in m.content for m in llm.calls[0] if m.role == 'system')
        assert len(client.get('/api/conversations', params={'character_id': char['id']}).json()) == 1
        assert client.delete('/api/characters/' + char['id']).status_code == 409


@pytest.mark.parametrize('mode,decision,expected_calls', [('OFF', '{"search":true,"query":"天气"}', 0), ('AUTO', '{"search":false}', 0), ('AUTO', '{"search":true,"query":"天气"}', 1), ('ON', '{}', 1)])
def test_search_modes_and_saved_sources(llm, monkeypatch, mode, decision, expected_calls):
    search.save_search_settings(SearchSettings(enabled=True, api_key='fake-search-secret'))
    llm.decision = decision
    calls = []
    async def fake_search(query, config):
        calls.append(query)
        return [{'title': '天气来源', 'url': 'https://example.com/weather', 'content': '晴天'}]
    monkeypatch.setattr(companion_core, 'search_web', fake_search)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        result = events(send(client, cid, mode=mode))[-1]
        assert len(calls) == expected_calls
        assert len(result['assistant_message']['sources']) == expected_calls
        assert len(result['extra_usage']) == (1 if mode == 'AUTO' else 0)
        if expected_calls:
            assert any('天气来源' in m.content for m in llm.calls[-1][:-1])
            assert llm.calls[-1][-1].role == 'user'
            # 搜索来源保存在会话供界面查看，下一轮不注入旧检索资料。
            events(send(client, cid, mode='OFF'))
            assert all('天气来源' not in m.content for m in llm.calls[-1])
            assert store.get_conversation(cid).messages[1].sources


def test_search_on_disabled_is_clear_error_and_auto_can_chat(llm):
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        assert send(client, cid, mode='ON').status_code == 422
        assert store.get_conversation(cid).messages == []
        assert events(send(client, cid, mode='AUTO'))[-1]['type'] == 'complete'


def test_search_failure_does_not_claim_success(llm, monkeypatch):
    search.save_search_settings(SearchSettings(enabled=True, api_key='fake'))
    llm.decision = '{"search":true,"query":"天气"}'
    async def failed_search(*args):
        raise ValueError('搜索连接失败或超时')
    monkeypatch.setattr(companion_core, 'search_web', failed_search)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        result = events(send(client, cid, mode='AUTO'))[-1]
        assert result['search']['status'] == 'failed'
        assert any('不得声称已查证' in m.content for m in llm.calls[-1][:-1])
        assert llm.calls[-1][-1].role == 'user'


def test_duplicate_running_request_and_detached_persistence(llm):
    llm.delay = 0.05
    async def scenario():
        conversation = store.create_conversation()
        job = core.submit(conversation.id, 'request-one', '断开页面后仍保存', 'Asia/Shanghai', search_mode='OFF')
        replay = core.submit(conversation.id, 'request-one', '断开页面后仍保存', 'Asia/Shanghai', search_mode='OFF')
        assert replay is job
        with pytest.raises(store.Conflict):
            core.submit(conversation.id, 'request-two', '抢占', 'Asia/Shanghai', search_mode='OFF')
        # 不订阅 events，模拟页面不在场。后台任务仍会完成落库。
        await job.task
        assert len(store.get_conversation(conversation.id).messages) == 2
        assert len(llm.calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('started', [False, True])
def test_manual_stop_releases_conversation_and_retry(llm, started):
    async def scenario():
        conversation = store.create_conversation()
        other = store.create_conversation()
        llm.delay = 60
        job = core.submit(conversation.id, 'stop-me', '保留用户消息', 'Asia/Shanghai', search_mode='OFF')
        if started:
            await asyncio.sleep(0.02)
        with pytest.raises(KeyError):
            await core.cancel(other.id, 'stop-me')
        assert not job.task.done()
        await core.cancel(conversation.id, 'stop-me')
        assert job.task.done()
        assert store.get_request('stop-me')['error'] == '已手动停止生成'
        saved = store.get_conversation(conversation.id)
        assert saved.pending_request_id is None
        assert len(saved.messages) == 1
        assert job.events[-1]['detail'] == '已手动停止生成'
        llm.delay = 0
        retry = core.submit(conversation.id, 'stop-me', '保留用户消息', 'Asia/Shanghai', search_mode='OFF')
        await retry.task
        assert len(store.get_conversation(conversation.id).messages) == 2
        assert (await core.cancel(conversation.id, 'stop-me'))['status'] == 'complete'
    asyncio.run(scenario())


def test_error_retry_reuses_original_user_message(llm, monkeypatch):
    original_stream = llm.stream_complete
    async def fail_once(messages):
        raise RuntimeError('fake-secret in provider error')
        yield ''
    monkeypatch.setattr(llm, 'stream_complete', fail_once)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        rid = 'retry-id'
        failed = events(send(client, cid, rid=rid))[-1]
        assert failed['type'] == 'error' and 'fake-secret' not in failed['detail']
        monkeypatch.setattr(llm, 'stream_complete', original_stream)
        assert events(send(client, cid, rid=rid))[-1]['type'] == 'complete'
        assert len(store.get_conversation(cid).messages) == 2
        assert sum('你好' in m.content for m in llm.calls[-1] if m.role == 'user') == 1


@pytest.mark.parametrize('action', ['NO_ACTION', 'SEND_MESSAGE'])
def test_heartbeat_uses_core_and_next_chat_remembers_it(llm, action):
    llm.reply = json.dumps({'action': action, 'message': '在想你，今天怎么样？'}, ensure_ascii=False)
    async def scenario():
        conversation = store.create_conversation()
        store.save_heartbeat(conversation.id, HeartbeatSettings(enabled=True, cooldown_minutes=0))
        job, reason = core.heartbeat(conversation.id)
        assert reason is None
        await job.task
        records = store.get_conversation(conversation.id).messages
        assert len(records) == (1 if action == 'SEND_MESSAGE' else 0)
        request = store.get_request(job.request_id)
        assert request['result']['action'] == action
        assert request['usage']['input_tokens'] == 100
        if records:
            assert records[0].source == 'heartbeat'
            llm.reply = '我记得刚刚主动找过你'
            job = core.submit(conversation.id, 'later-chat', '我回来啦', 'Asia/Shanghai', search_mode='OFF')
            await job.task
            assert any('在想你，今天怎么样' in m.content for m in llm.calls[-1])
    asyncio.run(scenario())


def test_heartbeat_limits_and_invalid_decision(llm):
    async def scenario():
        conversation = store.create_conversation()
        assert core.heartbeat(conversation.id)[1] == '未启用'
        store.save_heartbeat(conversation.id, HeartbeatSettings(enabled=True, cooldown_minutes=0, max_messages_per_day=1))
        llm.reply = '{"action":"SEND_MESSAGE","message":"嗨"}'
        job, _ = core.heartbeat(conversation.id); await job.task
        assert core.heartbeat(conversation.id)[1] == '达到今日主动消息上限'
        other = store.create_conversation()
        store.save_heartbeat(other.id, HeartbeatSettings(enabled=True, cooldown_minutes=0))
        llm.reply = '{"action":"TOOL_ACTION"}'
        job, _ = core.heartbeat(other.id); await job.task
        assert store.get_request(job.request_id)['status'] == 'error'
        assert store.get_conversation(other.id).messages == []
    asyncio.run(scenario())


def test_heartbeat_explore_launches_without_private_payload(llm, monkeypatch):
    from app import autonomy
    monkeypatch.setattr(autonomy, 'FEATURE_ARCHIVED', False)
    launched = []
    monkeypatch.setattr(autonomy, 'launch', lambda *args: launched.append(args))
    llm.reply = '{"action":"EXPLORE","reason":"SECRET 工作内容"}'
    async def scenario():
        conv = store.create_conversation()
        store.save_heartbeat(conv.id, HeartbeatSettings(enabled=True, cooldown_minutes=0, quiet_enabled=False))
        autonomy.save_settings(autonomy.Settings(enabled=True, automatic=True, provider='search', conversation_ids=[conv.id]).model_dump())
        job, error = core.heartbeat(conv.id)
        assert not error
        await job.task
        assert store.get_request(job.request_id)['status'] == 'complete'
        assert launched == [(conv.id, job.request_id)]
        assert not store.get_conversation(conv.id).messages
        assert 'EXPLORE' in llm.calls[0][-1].content
    asyncio.run(scenario())


@pytest.mark.parametrize('action',['NO_ACTION','SEND_MESSAGE','EXPLORE'])
def test_archived_heartbeat_only_messages_or_silence(llm,monkeypatch,action):
    from app import autonomy
    monkeypatch.setattr(autonomy,'FEATURE_ARCHIVED',True)
    launched = []
    monkeypatch.setattr(autonomy,'launch',lambda *args: launched.append(args))
    llm.reply = json.dumps({'action':action,'message':'想和你聊聊'})
    async def scenario():
        conv = store.create_conversation()
        store.save_heartbeat(conv.id,HeartbeatSettings(enabled=True,cooldown_minutes=0,quiet_enabled=False))
        store.save_setting('autonomy',{'enabled':True,'automatic':True,'provider':'search','conversation_ids':[conv.id]})
        job,error = core.heartbeat(conv.id)
        assert not error
        await job.task
        request = store.get_request(job.request_id)
        assert request['status'] == ('error' if action == 'EXPLORE' else 'complete')
        assert 'EXPLORE' not in llm.calls[0][-1].content and not launched
        messages = store.get_conversation(conv.id).messages
        assert len(messages) == (1 if action == 'SEND_MESSAGE' else 0)
        if messages: assert messages[0].source == 'heartbeat'
    asyncio.run(scenario())


def test_scheduler_claims_once_without_browser(llm):
    llm.reply = '{"action":"SEND_MESSAGE","message":"后台主动消息"}'
    async def scenario():
        conversation = store.create_conversation()
        message = store.new_message('user', '昨天聊过', 'Asia/Shanghai', 'web', None)
        message.timestamp = (store.utcnow() - timedelta(hours=24)).isoformat()
        with store.database() as db:
            store._insert_message(db, conversation.id, message)
        store.save_heartbeat(conversation.id, HeartbeatSettings(enabled=True, cooldown_minutes=0))
        with store.database() as db:
            db.execute('UPDATE conversations SET next_heartbeat_at=? WHERE id=?', ((store.utcnow() - timedelta(minutes=1)).isoformat(), conversation.id))
        await heartbeat.tick()
        await heartbeat.tick()
        await asyncio.gather(*(job.task for job in list(core.jobs.values())))
        assert len(store.get_conversation(conversation.id).messages) == 2
        assert len(llm.calls) == 1
    asyncio.run(scenario())


def test_timezone_quiet_and_cooldown(llm):
    conversation = store.create_conversation(tz='Asia/Shanghai')
    conversation.heartbeat = HeartbeatSettings(enabled=True, quiet_enabled=True, quiet_start=0, quiet_end=23)
    now = store.utcnow().replace(hour=0)  # 上海 08 点
    assert core.heartbeat_guard(conversation, now) == '静默时段'
    conversation.heartbeat = HeartbeatSettings(enabled=True, cooldown_minutes=30)
    store.begin_turn(conversation.id, 'user', '刚说话', conversation.timezone, 'web', 'OFF')
    store.finish_turn('user', '我在', TokenUsage(), [], [], {})
    conversation = store.get_conversation(conversation.id)
    conversation.heartbeat = HeartbeatSettings(enabled=True, cooldown_minutes=30)
    assert core.heartbeat_guard(conversation) == '互动冷却中'
    with pytest.raises(ValueError):
        store.create_conversation(tz='MadeUp/Timezone')


def test_legacy_migration_is_once_and_retains_unknown_time(tmp_path, monkeypatch):
    legacy = tmp_path / 'legacy.json'
    legacy.write_text(json.dumps([{'id': 'old', 'name': '旧记录', 'messages': [{'role': 'user', 'content': '旧正文'}]}]), encoding='utf-8')
    monkeypatch.setattr(store, 'CONVERSATIONS_FILE', legacy)
    assert len(store.get_conversation('old').messages) == 1
    assert store.get_conversation('old').messages[0].timestamp == ''
    store._initialized.clear()
    assert len(store.get_conversation('old').messages) == 1
    assert json.loads(legacy.read_text(encoding='utf-8'))[0]['messages'][0]['content'] == '旧正文'


def test_usage_values_are_actual_or_unknown():
    assert read_usage({'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 0}}}).cached_tokens == 0
    assert read_usage({'usage': {'input_tokens': 10}}).output_tokens is None
    assert read_usage({'usage': {'prompt_tokens': True, 'completion_tokens': 1.2}}).input_tokens is None
    assert read_usage({'usage': {'prompt_tokens': True, 'completion_tokens': 1.2}}).output_tokens is None
    assert read_usage({'usage': {'prompt_cache_hit_tokens': 8}}).cached_tokens == 8


def test_stream_final_empty_choices_usage_and_nonstream_fallback(monkeypatch):
    requests = []
    def handler(request):
        body = json.loads(request.content); requests.append(body)
        if body['stream']:
            return httpx.Response(200, text='data: {"choices":[]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={'choices': [{'message': {'content': '完整回复'}}], 'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'prompt_tokens_details': {'cached_tokens': 2}}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(providers, '_LLM_HTTP_CLIENT', client)
            provider = providers.OpenAICompatibleLlm(LlmProviderProfile(id='test', name='test', api_key='fake', model='fake'))
            output = ''.join([piece async for piece in provider.stream_complete([ChatMessage(role='user', content='你好')])])
            assert output == '完整回复'
            assert requests[0]['stream_options']['include_usage'] is True
            assert 'stream_options' not in requests[1]
            assert provider.last_usage.cached_tokens == 2
    asyncio.run(scenario())


def test_provider_usage_chunk_with_no_choices(monkeypatch):
    def handler(request):
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"嗨"}}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":1}}\n\ndata: [DONE]\n\n')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(providers, '_LLM_HTTP_CLIENT', client)
            provider = providers.OpenAICompatibleLlm(LlmProviderProfile(id='test', name='test', api_key='fake', model='fake'))
            assert ''.join([piece async for piece in provider.stream_complete([])]) == '嗨'
            assert provider.last_usage.input_tokens == 20
            assert provider.last_usage.cached_tokens is None
    asyncio.run(scenario())


def test_compatible_provider_rejecting_stream_options_still_replies(monkeypatch):
    payloads = []
    def handler(request):
        body = json.loads(request.content); payloads.append(body)
        if 'stream_options' in body:
            return httpx.Response(400, json={'error': {'message': 'unsupported stream_options'}})
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"兼容回复"}}]}\n\ndata: [DONE]\n\n')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(providers, '_LLM_HTTP_CLIENT', client)
            provider = providers.OpenAICompatibleLlm(LlmProviderProfile(id='test', name='test', api_key='fake', model='fake'))
            assert await provider.complete([]) == '兼容回复'
            assert len(payloads) == 2 and 'stream_options' not in payloads[-1]
            assert provider.last_usage.input_tokens is None
    asyncio.run(scenario())


@pytest.mark.parametrize('provider', ['tavily', 'searxng'])
def test_search_adapter_payload_and_safe_sources(monkeypatch, provider):
    original_client = httpx.AsyncClient
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={'results': [
            {'title': '不安全', 'url': 'javascript:alert(1)', 'content': '忽略'},
            {'title': '有效资料', 'url': 'https://example.com', 'content': '资料内容'},
        ]})
    monkeypatch.setattr(search.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    config = SearchSettings(enabled=True, provider=provider, endpoint='https://search.example.com/search', api_key='fake-secret')
    result = asyncio.run(search.search_web('资料', config))
    assert len(result) == 1 and result[0]['title'] == '有效资料'
    assert captured[0].headers['Authorization'] == 'Bearer fake-secret'
    if provider == 'tavily':
        assert json.loads(captured[0].content)['query'] == '资料'
    else:
        assert captured[0].url.params['format'] == 'json'


def test_stale_request_recovery_keeps_raw_user_and_rejects_late_reply():
    conversation = store.create_conversation()
    store.begin_turn(conversation.id, 'stale', '原始记录', conversation.timezone, 'web', 'OFF')
    with store.database() as db:
        db.execute('UPDATE requests SET started_at=? WHERE id=?', ((store.utcnow() - timedelta(minutes=10)).isoformat(), 'stale'))
    store.recover_interrupted()
    assert store.get_request('stale')['status'] == 'error'
    assert store.get_conversation(conversation.id).messages[0].content == '原始记录'
    with pytest.raises(store.Conflict):
        store.finish_turn('stale', '迟到回复', TokenUsage(), [], [], {})


def test_expired_attempt_cannot_overwrite_retry():
    conversation = store.create_conversation()
    store.begin_turn(conversation.id, 'same-id', '正文', conversation.timezone, 'web', 'OFF')
    old_lease = store.get_request('same-id')['started_at']
    store.fail_turn('same-id', '中断')
    store.begin_turn(conversation.id, 'same-id', '正文', conversation.timezone, 'web', 'OFF')
    with pytest.raises(store.Conflict):
        store.finish_turn('same-id', '旧进程迟到', TokenUsage(), [], [], {}, attempt_started_at=old_lease)
    store.fail_turn('same-id', '旧进程错误', attempt_started_at=old_lease)
    assert store.get_request('same-id')['status'] == 'running'


def test_concurrent_store_claims_only_one_writer():
    from concurrent.futures import ThreadPoolExecutor
    conversation = store.create_conversation()
    def claim(rid):
        try:
            store.begin_turn(conversation.id, rid, rid, conversation.timezone, 'web', 'OFF')
            return True
        except store.Conflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ['one', 'two']))
    assert sorted(results) == [False, True]
    assert len(store.get_conversation(conversation.id).messages) == 1


def test_cannot_delete_role_bound_configuration():
    from app.prompt_store import create_prompt_preset
    from app.lorebook_store import create_lorebook
    _, preset = create_prompt_preset('绑定预设')
    _, book = create_lorebook('绑定世界书')
    provider_store.upsert_provider_profile('llm', {'id': 'bound-llm', 'name': '绑定模型'})
    store.save_character(Character(name='绑定角色', preset_id=preset.id, lorebook_id=book.id, llm_profile_id='bound-llm'))
    with TestClient(app) as client:
        assert client.delete('/api/prompt-presets/' + preset.id).status_code == 409
        assert client.delete('/api/lorebooks/' + book.id).status_code == 409
        assert client.delete('/api/provider-profiles/llm/bound-llm').status_code == 409


def test_streaming_voice_audio_and_text_persist_before_delivery(llm, monkeypatch):
    async def pcm(self, texts, profile):
        async for text in texts:
            assert text.strip()
            yield b'\0\0' * 32
    monkeypatch.setattr(companion_core.HttpTts, 'stream_pcm', pcm)
    async def scenario():
        conversation = store.create_conversation()
        snapshot = provider_store.ProviderSnapshot(stt=SttProviderProfile(id='s', name='s'), llm=LlmProviderProfile(id='l', name='l'),
                                                  tts=TtsProviderProfile(id='t', name='t', endpoint='wss://fake'))
        job = core.submit(conversation.id, 'pcm-voice', '语音', conversation.timezone, 'voice', 'OFF', snapshot)
        await job.task
        assert any(event['type'] == 'audio_chunk' for event in job.events)
        assert job.events[-1]['type'] == 'complete'
        assert job.events[-1]['audio_streamed'] is True
        assert len(store.get_conversation(conversation.id).messages) == 2
    asyncio.run(scenario())


def test_search_settings_key_not_returned():
    with TestClient(app) as client:
        result = client.put('/api/search/settings', json={'api_key': 'fake-key', 'enabled': True}).json()
        assert result['api_key_set'] and 'api_key' not in result
        client.put('/api/search/settings', json={'api_key': '', 'enabled': True})
        assert search.load_search_settings().api_key == 'fake-key'
        assert 'fake-key' not in client.get('/api/search/settings').text


def test_voice_transcript_uses_same_core_preserves_raw_and_saves(llm, monkeypatch):
    from app import main
    snapshot = provider_store.ProviderSnapshot(stt=SttProviderProfile(id='stt', name='stt'), llm=LlmProviderProfile(id='llm', name='llm'), tts=TtsProviderProfile(id='tts', name='tts', endpoint='http://fake'))
    monkeypatch.setattr(main, 'take_provider_snapshot', lambda *_: snapshot)
    async def synthesize(self, text, profile):
        assert '**' not in text
        return b'RIFF-fake-wave'
    monkeypatch.setattr(companion_core.HttpTts, 'synthesize', synthesize)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        result = events(client.post('/api/process/stream', json={'conversation_id': cid, 'request_id': 'voice-one', 'transcript': '语音输入', 'search_mode': 'OFF'}))[-1]
        assert result['type'] == 'complete'
        assert result['audio_base64']
        assert store.get_conversation(cid).messages[-1].content == '你好，**原文**'
        assert store.get_conversation(cid).messages[-1].source == 'voice'


@pytest.mark.parametrize('source', ['web', 'voice', 'heartbeat'])
def test_dynamic_time_and_status_only_change_d1_system(monkeypatch, source):
    from datetime import datetime, timezone
    from app.prompt_store import default_wrx_preset
    from app.models import Lorebook
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        conversation = store.get_conversation(cid)
        character = store.get_character(conversation.character_id)
        store.begin_turn(cid, 'history', '历史正文', 'Asia/Shanghai', 'web', 'OFF')
        store.finish_turn('history', '历史回复', TokenUsage(), [], [], {})
        conversation = store.get_conversation(cid)
        clock = datetime(2026, 10, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(store, 'utcnow', lambda: clock)
        first, _ = core.context(conversation, character, '本轮正文', source, default_wrx_preset(), Lorebook(id='empty', name='空'))
        clock += timedelta(minutes=1)
        second, _ = core.context(conversation, character, '本轮正文', source, default_wrx_preset(), Lorebook(id='empty', name='空'))
        changes = [i for i, (a, b) in enumerate(zip(first.messages, second.messages)) if a != b]
        assert len(first.messages) == len(second.messages)
        assert changes == [len(first.messages)-2]
        index = changes[0]
        assert first.messages[index].role == 'system'
        assert '[服务器提供的本轮时间：' in first.messages[index].content
        assert first.messages[-1].role == 'user'
        assert first.messages[-1].content == second.messages[-1].content == '本轮正文'
        assert first.messages[:index] == second.messages[:index]
        assert all('服务器提供的本轮时间' not in m.content for m in first.messages[:index])
        assert any('历史正文' in m.content for m in first.messages[:index])
        assert conversation.messages[0].content == '历史正文'
        assert first.trace['final_messages'] == [m.model_dump() for m in first.messages]

def test_context_preview_and_persisted_last_are_separate(llm):
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        assert client.get(f'/api/conversations/{cid}/context-last').json()['debug'] is None
        preview = client.post(f'/api/conversations/{cid}/context-preview', json={'content': '仅用于预填充'})
        assert preview.status_code == 200, preview.text
        assert any('仅用于预填充' in m['content'] for m in preview.json()['llm_messages'])
        assert not llm.calls and not store.get_conversation(cid).messages
        with store.database() as db:
            assert db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] == 0
        result = events(send(client, cid, '正式消息'))[-1]
        last = client.get(f'/api/conversations/{cid}/context-last').json()
        assert last['debug']['llm_messages'] == result['debug']['llm_messages']
        assert last['debug']['llm_raw'] == llm.reply
        other = client.post('/api/conversations').json()['id']
        assert client.get(f'/api/conversations/{other}/context-last').json()['debug'] is None
        client.post(f'/api/conversations/{cid}/context-preview', json={'content': '另一个模拟'})
        assert client.get(f'/api/conversations/{cid}/context-last').json()['request_id'] == last['request_id']
        assert len(store.get_conversation(cid).messages) == 2

@pytest.mark.parametrize('allow_silence', [False, True])
def test_heartbeat_current_emotions_and_silence_prompt(llm, monkeypatch, allow_silence):
    from app import role_state
    monkeypatch.setattr(role_state, 'config', lambda: role_state.EmotionSettings(allow_silence=allow_silence))
    llm.reply = '{"action":"SEND_MESSAGE","message":"来一起玩吧"}'
    async def scenario():
        conv = store.create_conversation()
        store.save_heartbeat(conv.id, HeartbeatSettings(enabled=True, cooldown_minutes=0, quiet_enabled=False))
        expected = role_state.state(conv.id)
        job, error = core.heartbeat(conv.id)
        assert error is None
        await job.task
        content = llm.calls[-1][-1].content
        payload = json.loads(content.split('\n', 1)[1])
        assert payload['state']['values'] == expected['values']
        assert 'threshold' not in payload['state']
        assert '未达到' not in content and '无需为了' not in content
        assert 'NO_ACTION' in content and 'SEND_MESSAGE' in content
        assert '本次唤醒请主动联系' not in content
        assert 'motives' not in payload['state']
        assert '不能仅凭时间' in content
        trace = json.loads(store.heartbeat_logs(conv.id, 1)[0]['result'])['debug']['prompt_trace']
        assert trace['companion_state']['threshold'] == 60
    asyncio.run(scenario())


def test_scheduler_below_current_threshold_still_calls_model(llm, monkeypatch):
    from app import role_state
    monkeypatch.setattr(role_state, 'state', lambda cid: {'desire_to_act': 59, 'threshold': 60, 'phase': '冷却中'})
    calls = []
    monkeypatch.setattr(core, 'heartbeat', lambda cid: calls.append(cid))
    async def scenario():
        conv = store.create_conversation()
        store.save_heartbeat(conv.id, HeartbeatSettings(enabled=True, cooldown_minutes=0, quiet_enabled=False))
        with store.database() as db:
            db.execute('UPDATE conversations SET next_heartbeat_at=? WHERE id=?', ((store.utcnow() - timedelta(minutes=1)).isoformat(), conv.id))
        await heartbeat.tick()
        assert calls == [conv.id]
        assert not store.heartbeat_logs(conv.id, 1)
    asyncio.run(scenario())
