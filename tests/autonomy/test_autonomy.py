import asyncio
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from app.autonomy import service as a
from app.chat import store
from app.memory import role as memory
from app.main import app
from app.models import TokenUsage


@pytest.fixture(autouse=True)
def unarchive_for_preserved_executor_tests(monkeypatch):
    # 归档实现的离线回归仍保留；生产始终封存，封存测试单独恢复门禁。
    monkeypatch.setattr(a, 'FEATURE_ARCHIVED', False)


def configure():
    conv = store.create_conversation()
    cfg = a.Settings(enabled=True, endpoint='https://community.example', quiet_start=0, quiet_end=0)
    a.save_settings(cfg.model_dump())
    return conv, cfg


def test_archive_closes_existing_settings_api_and_executor(monkeypatch):
    conv,cfg = configure()
    cfg.automatic = True; cfg.allow_replies = True; cfg.api_key = 'test-secret'
    cfg.conversation_ids = [conv.id]
    store.save_setting('autonomy',cfg.model_dump())
    monkeypatch.setattr(a,'FEATURE_ARCHIVED',True)
    assert not a.heartbeat_enabled(conv.id)
    for call in (lambda:a.prepare(conv.id),lambda:a.launch(conv.id,'old'),lambda:a.depart(conv.id)):
        with pytest.raises(store.Conflict): call()
    with TestClient(app) as client:
        public = client.get('/api/autonomy/settings').json()
        assert public['archived'] and not any(public[k] for k in ('enabled','automatic','allow_replies'))
        for path in ('/connection',f'/{conv.id}/run',f'/{conv.id}/depart'):
            assert client.post('/api/autonomy'+path).status_code == 409
        assert client.put('/api/autonomy/settings',json=cfg.model_dump()).status_code == 409
        assert client.get(f'/api/autonomy/{conv.id}/runs').status_code == 200
    saved = store.get_setting('autonomy',{})
    assert not saved['enabled'] and not saved['automatic'] and not saved['allow_replies']
    assert saved['api_key'] == 'test-secret' and saved['endpoint'] == cfg.endpoint


def test_archive_closes_stale_run_without_blocking_heartbeat(monkeypatch):
    conv,cfg = configure(); run = a.claim(conv.id,cfg)
    monkeypatch.setattr(a,'FEATURE_ARCHIVED',True)
    a.archive_settings()
    assert a.runs(conv.id)[0]['status'] == 'interrupted'
    assert not a.is_running(conv.id)


@pytest.mark.parametrize('raw', [
    '<ai_action type="shell"><content>run</content></ai_action>',
    '<!DOCTYPE x [<!ENTITY a "xx">]><ai_note>&a;</ai_note>',
    '<ai_action type="browse"><thought>x</thought><thought>y</thought></ai_action>',
    '<ai_action type="read_post"><post_id><url>x</url></post_id></ai_action>',
    '<ai_action type="read_post"/>',
    'hello <ai_note>x</ai_note>',
])
def test_reject_invalid_protocol(raw):
    with pytest.raises(ValueError): a.parse_action(raw)


def test_loop_notes_before_continue_privacy_and_budget(monkeypatch):
    conv, cfg = configure()
    store.begin_turn(conv.id, 'private', 'SECRET工作客户资料', conv.timezone, 'web', 'OFF')
    store.finish_turn('private', '保密', TokenUsage(), [], [], {})
    responses = iter(['<ai_action type="browse"/>', '<ai_note>读到绘画活动，想尝试水彩。</ai_note>',
                      '<ai_action type="read_post"><post_id>12</post_id></ai_action>', '<ai_note>帖子介绍了水彩工具。</ai_note>',
                      '<ai_action type="rest"/>'])
    calls, caps = [], []
    class Fake:
        last_usage = TokenUsage(input_tokens=5, output_tokens=4)
        def __init__(self, profile): pass
        def set_generation_parameters(self, value): caps.append(value['max_tokens'])
        async def complete(self, messages):
            calls.append(messages)
            if len(calls) == 3:
                notes = memory.all_records('default')
                assert len(notes) == 1 and notes[0]['note_status'] == 'done'
            return next(responses)
    async def browse(*args): return [{'id':'12','content':'绘画公开帖子'}]
    monkeypatch.setattr(a, 'OpenAICompatibleLlm', Fake)
    monkeypatch.setattr(a, 'resolve_llm', lambda *args: memory.LlmProviderProfile(id='fake', name='fake', model='fake'))
    monkeypatch.setattr(a, 'browse', browse)
    result = asyncio.run(a.run_activity(conv.id))
    assert result['status'] == 'done' and len(result['notes']) == 2
    assert len(result['evidence']) == 2 and sum(caps) <= cfg.output_budget
    assert 'SECRET' not in json.dumps([[m.model_dump() for m in c] for c in calls], ensure_ascii=False)
    assert len(store.get_conversation(conv.id).messages) == 2
    with pytest.raises(store.Conflict): asyncio.run(a.run_activity(conv.id))


def test_note_failure_keeps_facts(monkeypatch):
    conv, cfg = configure()
    cfg.max_steps = 2; a.save_settings(cfg.model_dump())
    responses = iter(['<ai_action type="browse"/>', 'invalid', '<ai_action type="rest"/>'])
    class Fake:
        last_usage = TokenUsage()
        def __init__(self, profile): pass
        def set_generation_parameters(self, value): pass
        async def complete(self, messages): return next(responses)
    async def browse(*args): return [{'id':'7', 'content':'真实结果'}]
    monkeypatch.setattr(a, 'OpenAICompatibleLlm', Fake)
    monkeypatch.setattr(a, 'resolve_llm', lambda *args: memory.LlmProviderProfile(id='fake', name='fake', model='fake'))
    monkeypatch.setattr(a, 'browse', browse)
    run = asyncio.run(a.run_activity(conv.id))
    assert run['status'] == 'done'
    note = memory.all_records('default')[0]
    assert note['note_status'] == 'facts_only' and '真实结果' in note['content']
    assert note['execution_result']['action'] == 'browse'


def test_host_and_endpoint_guards(monkeypatch):
    with pytest.raises(ValueError): a.Settings(endpoint='https://example.org/path')
    monkeypatch.setattr(a.socket, 'getaddrinfo', lambda *args, **kwargs: [(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError): asyncio.run(a.validate_public_host('https://localhost'))
    monkeypatch.setattr(a.socket, 'getaddrinfo', lambda *args, **kwargs: [(2,1,6,'',('198.18.0.10',443))])
    with pytest.raises(ValueError): asyncio.run(a.validate_public_host('https://community.example'))
    asyncio.run(a.validate_public_host('https://community.example', True))


def test_mastodon_actual_http_normalization(monkeypatch):
    cfg = a.Settings(endpoint='https://community.example')
    requests = []
    async def public(*args): pass
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=[{'id':'12','visibility':'public','content':'<p>Hello <b>world</b></p>'},
            {'id':'13','visibility':'private','content':'secret'}])
    real_client = httpx.AsyncClient
    monkeypatch.setattr(a, 'validate_public_host', public)
    monkeypatch.setattr(a.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(a.browse(cfg))
    assert len(result) == 1 and result[0]['content'] == 'Hello  world'
    assert requests[0].method == 'GET' and requests[0].url.path == '/api/v1/timelines/public'


def test_reply_authorization_privacy_and_idempotency(monkeypatch):
    cfg = a.Settings(endpoint='https://community.example', allow_replies=True, api_key='test-only')
    with pytest.raises(ValueError): asyncio.run(a.reply_to_post(cfg, '12', '我用户的公司在这里', 'key'))
    requests = []
    async def public(*args): pass
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'id':'99','content':'<p>水彩很好看</p>'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(a, 'validate_public_host', public)
    monkeypatch.setattr(a.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(a.reply_to_post(cfg, '12', '水彩很好看', 'stable-key'))
    assert result[0]['id'] == '99'
    assert requests[0].headers['Idempotency-Key'] == 'stable-key'
    assert b'in_reply_to_id=12' in requests[0].content


def test_settings_secrets_and_character_limit():
    conv, cfg = configure()
    cfg.api_key = 'secret'; a.save_settings(cfg.model_dump())
    assert a.public_settings()['api_key'] == ''
    changed = cfg.model_dump() | {'endpoint':'https://another.example', 'api_key':''}
    a.save_settings(changed); assert not a.settings().api_key
    cfg = a.settings(); cfg.quiet_start = cfg.quiet_end = 0
    run = a.claim(conv.id, cfg)
    with pytest.raises(store.Conflict): store.delete_conversation(conv.id)
    other = store.create_conversation()
    with pytest.raises(store.Conflict): a.claim(other.id, cfg)
    run['status'] = 'done'; a.save_run(run)
    with pytest.raises(store.Conflict): a.claim(other.id, cfg)


def test_api_defaults_skills_and_disabled_run():
    conv = store.create_conversation()
    with TestClient(app) as client:
        assert not client.get('/api/autonomy/settings').json()['enabled']
        assert len(client.get('/api/autonomy/skills').json()['skills']) == 2
        assert client.post(f'/api/autonomy/{conv.id}/run').status_code == 422


def test_manual_is_additional_entry_keeps_automatic_limits(monkeypatch):
    conv, cfg = configure()
    cfg.automatic = True; cfg.conversation_ids = [conv.id]
    cfg.quiet_start = 0; cfg.quiet_end = 23; cfg.daily_limit = 2
    a.save_settings(cfg.model_dump())
    first = a.claim(conv.id, cfg, manual=True)
    with pytest.raises(store.Conflict): a.claim(conv.id,cfg,manual=True)
    first['status'] = 'done'; a.save_run(first)
    with pytest.raises(store.Conflict): a.claim(conv.id,cfg)
    second = a.claim(conv.id,cfg,manual=True)
    assert second['trigger'] == 'manual' and a.heartbeat_enabled(conv.id)
    second['status'] = 'done'; a.save_run(second)
    with pytest.raises(store.Conflict): a.claim(conv.id,cfg,manual=True)


def test_mcp_credentials_mask_preserve_and_api_errors():
    conv, cfg = configure()
    value = cfg.model_dump() | {'destinations':[{'id':'luto','name':'Lutopia','provider':'lutopia','mcp_url':'https://lutopia.app/mcp/SECRET123/sse'}]}
    public = a.save_settings(value)
    assert 'SECRET123' not in json.dumps(public)
    a.save_settings(public)
    assert a.settings().destinations[0].mcp_url.endswith('SECRET123/sse')
    with TestClient(app) as client:
        bad = cfg.model_dump() | {'destinations':[{'id':'luto','name':'Lutopia','provider':'lutopia','mcp_url':'https://evil.example/mcp/SECRET123'}]}
        result = client.put('/api/autonomy/settings',json=bad)
        assert result.status_code == 422 and 'SECRET123' not in result.text


def test_destination_selection_and_cross_site_ids(monkeypatch):
    conv,cfg = configure()
    cfg.destinations = [a.Destination(id='other',name='另一个社区',provider='mastodon',endpoint='https://another.example')]
    a.save_settings(cfg.model_dump())
    replies = iter(['<ai_action type="browse"><destination>other</destination></ai_action>', '<ai_note>读到新社区的帖子。</ai_note>',
                    '<ai_action type="read_post"><destination>primary</destination><post_id>12</post_id></ai_action>', '<ai_note>跨站阅读被拒绝。</ai_note>', '<ai_action type="rest"/>'])
    calls = []
    class Fake:
        last_usage = TokenUsage()
        def __init__(self,profile): pass
        def set_generation_parameters(self,value): pass
        async def complete(self,messages): return next(replies)
    async def browse(target,post_id=''):
        calls.append(target.endpoint); return [{'id':'12','content':'实际公开资料'}]
    monkeypatch.setattr(a,'OpenAICompatibleLlm',Fake)
    monkeypatch.setattr(a,'resolve_llm',lambda *args: memory.LlmProviderProfile(id='fake',name='fake',model='fake'))
    monkeypatch.setattr(a,'browse',browse)
    result = asyncio.run(a.run_activity(conv.id,manual=True))
    assert calls == ['https://another.example']
    assert result['evidence'][0]['destination'] == 'other'
    assert result['evidence'][1]['status'] == 'error' and len(result['notes']) == 2


@pytest.mark.parametrize('sse',[False,True])
def test_lutopia_fixed_readonly_cli_transport(monkeypatch,sse):
    from app.autonomy import lutopia
    cfg = a.Settings().model_copy(update={'provider':'lutopia','mcp_url':'https://lutopia.app/mcp/secret/sse'})
    requests = []
    async def public(*args): pass
    def respond(request):
        body = json.loads(request.content); requests.append((request,body))
        if body['method'] == 'notifications/initialized': return httpx.Response(202)
        if body['method'] == 'initialize': result = {'protocolVersion':'2025-03-26','capabilities':{},'serverInfo':{'name':'Lutopia','version':'1'}}
        else: result = {'content':[{'type':'text','text':json.dumps({'posts':[{'id':'42','title':'绘画','content':'水彩讨论'}]})}]}
        payload = {'jsonrpc':'2.0','id':body['id'],'result':result}
        headers = {'Mcp-Session-Id':'session'}
        if sse:
            headers['content-type'] = 'text/event-stream'
            return httpx.Response(200,headers=headers,content=('data: '+json.dumps(payload)+'\n\n').encode())
        return httpx.Response(200,headers=headers,json=payload)
    client = httpx.AsyncClient
    monkeypatch.setattr(a,'validate_public_host',public)
    monkeypatch.setattr(lutopia.httpx,'AsyncClient',lambda **kwargs: client(transport=httpx.MockTransport(respond),**kwargs))
    result = asyncio.run(lutopia.browse(cfg))
    assert result[0]['id'] == '42' and result[0]['content'] == '水彩讨论'
    assert requests[-1][1]['params'] == {'name':'lutopia_cli','arguments':{'command':'discover --limit 5'}}
    assert requests[-1][0].headers['Mcp-Session-Id'] == 'session'
    assert all(r.url.path == '/mcp/secret' for r,_ in requests)


def test_depart_claims_before_background_and_does_not_require_automatic(monkeypatch):
    conv,cfg = configure()
    monkeypatch.setattr(a,'resolve_llm',lambda *args: memory.LlmProviderProfile(id='fake',name='fake',model='fake'))
    class Fake:
        last_usage = TokenUsage()
        def __init__(self,profile): pass
        def set_generation_parameters(self,value): pass
        async def complete(self,messages): await asyncio.sleep(30)
    monkeypatch.setattr(a,'OpenAICompatibleLlm',Fake)
    async def scenario():
        result = a.depart(conv.id)
        assert result['trigger'] == 'manual' and result['status'] == 'running'
        with pytest.raises(store.Conflict): a.depart(conv.id)
        await asyncio.sleep(0)
        await a.shutdown()
    asyncio.run(scenario())
    assert a.runs(conv.id)[0]['status'] == 'interrupted'
    assert not a.settings().automatic


def test_diary_hooks_scope_and_transaction(monkeypatch):
    conv = store.create_conversation(); other = store.create_conversation()
    date = store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    store.begin_turn(conv.id, 'source-hooks', '明天的旅行还没订票', conv.timezone, 'web', 'OFF')
    store.finish_turn('source-hooks', '记下了', TokenUsage(), [], [], {})
    cfg = memory.settings(); cfg.presets['diary'].llm.model = 'fake'; memory.save_settings(cfg.model_dump())
    class Fake:
        last_usage = TokenUsage()
        def __init__(self, profile): pass
        def set_generation_parameters(self, value): pass
        async def complete(self, messages): return '{"content":"约好旅行","tags":[],"unresolved_hooks":["旅行尚未订票"]}'
    monkeypatch.setattr(memory, 'OpenAICompatibleLlm', Fake)
    asyncio.run(memory.generate('diary', conv.id, date))
    assert '旅行尚未订票' in memory.hooks_context('default', conv.id)[0].content
    assert '旅行尚未订票' in memory.hooks_context('default', other.id)[0].content
    assert not memory.settings().presets['diary'].include_notes
