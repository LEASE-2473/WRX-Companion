from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import companion_store as store, companion_routes, provider_store
from app.companion_core import core
from app.models import Character, TtsProviderProfile
from app.models import PromptPreset, PromptEntry, PromptOrderEntry, Lorebook
from app.prompt_compiler import compile_prompt
from test_companion import FakeLlm, events, send

@pytest.fixture
def llm(monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(core, 'llm_for', lambda *args: fake)
    return fake

def test_branch_keeps_original_and_unique_message_ids(llm):
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid, '第一轮'))
        events(send(client, cid, '第二轮'))
        original = client.get(f'/api/conversations/{cid}').json()
        mid = original['messages'][1]['id']
        result = client.post(f'/api/conversations/{cid}/messages/{mid}/branch', json={}).json()
        branch = result['conversation']
        assert branch['parent_conversation_id'] == cid
        assert branch['branch_message_id'] == mid
        assert not branch['heartbeat']['enabled']
        assert [m['content'] for m in branch['messages']] == [m['content'] for m in original['messages'][:2]]
        assert all(m['request_id'] is None for m in branch['messages'])
        assert not ({m['id'] for m in original['messages']} & {m['id'] for m in branch['messages']})
        assert branch['messages'][1]['usage'] == original['messages'][1]['usage']
        assert client.get(f'/api/conversations/{cid}').json() == original
        other = client.post(f'/api/conversations/{cid}/messages/{mid}/branch', json={}).json()['conversation']
        assert other['name'] != branch['name']

@pytest.mark.parametrize('action,role,newtext', [('edit', 'user', '改过的消息'), ('regenerate', 'assistant', None), ('edit', 'assistant', '手动回复')])
def test_edits_and_regeneration_use_prefix_without_duplicate_input(llm, action, role, newtext):
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid, '旧问题'))
        events(send(client, cid, '后续不要进入新分支'))
        original = store.get_conversation(cid)
        target = original.messages[0 if role == 'user' else 1]
        response = client.post(f'/api/conversations/{cid}/messages/{target.id}/branch', json={'action': action, 'content': newtext})
        assert response.status_code == 200, response.text
        result = response.json(); branch = result['conversation']
        if result['resend_content']:
            assert branch['messages'] == []
            events(send(client, branch['id'], result['resend_content']))
            assert len(store.get_conversation(branch['id']).messages) == 2
            context = '\n'.join(m.content for m in llm.calls[-1])
            assert '后续不要进入新分支' not in context
            assert context.count(result['resend_content']) == 1
        else:
            assert len(branch['messages']) == 2
            assert branch['messages'][-1]['content'] == '手动回复'
            assert branch['messages'][-1]['source'] == 'edit'
            assert branch['messages'][-1]['usage'] is None
        assert store.get_conversation(cid) == original

def test_branch_rejects_busy_or_wrong_message(llm):
    conversation = store.create_conversation()
    rid = str(uuid4()); store.begin_turn(conversation.id, rid, '正在生成', 'Asia/Shanghai', 'web', 'OFF')
    mid = store.get_conversation(conversation.id).messages[0].id
    with TestClient(app) as client:
        assert client.post(f'/api/conversations/{conversation.id}/messages/{mid}/branch', json={}).status_code == 409
        store.fail_turn(rid, '模拟失败')
        assert client.post(f'/api/conversations/{conversation.id}/messages/{mid}/branch', json={'action':'regenerate'}).status_code == 422
        assert client.post(f'/api/conversations/{conversation.id}/messages/unknown/branch', json={}).status_code == 404

def test_message_tts_uses_character_voice_and_leaves_text_usage_unchanged(llm, monkeypatch):
    profile = TtsProviderProfile(id='clone', name='复刻音色', endpoint='https://example.com/tts', voice_type='my-voice')
    provider_store.upsert_provider_profile('tts', profile.model_dump())
    captured = []
    async def synthesize(self, text, preset):
        captured.append((text, preset.voice_type))
        return b'RIFF' + b'0' * 40
    monkeypatch.setattr(companion_routes.HttpTts, 'synthesize', synthesize)
    with TestClient(app) as client:
        char = client.post('/api/characters', json={'name':'小月','tts_profile_id':'clone'}).json()
        cid = client.post('/api/conversations', json={'character_id':char['id']}).json()['id']
        events(send(client, cid))
        original = store.get_conversation(cid)
        mid = original.messages[-1].id
        response = client.post(f'/api/conversations/{cid}/messages/{mid}/tts', json={})
        assert response.status_code == 200
        assert response.headers['content-type'] == 'audio/wav'
        assert captured == [('你好，原文', 'my-voice')]
        assert store.get_conversation(cid) == original
        assert len(llm.calls) == 1
        assert client.delete('/api/provider-profiles/tts/clone').status_code == 409
        assert client.post(f'/api/conversations/{cid}/messages/{original.messages[0].id}/tts', json={}).status_code == 422

def test_character_persona_respect_preset_markers(llm):
    char = store.save_character(Character(name='小月', personality='专属角色性格', persona='专属用户身份'))
    conversation = store.create_conversation(char.id)
    compiled, _ = core.context(conversation, char, '你好', 'web')
    assert compiled.trace['markers']['charDefinitions']['native_content_included']
    assert compiled.trace['markers']['userDefinitions']['native_content_included']
    assert '专属角色性格' not in compiled.messages[0].content
    assert any('专属角色性格' in m.content for m in compiled.messages[1:])
    assert any('专属用户身份' in m.content for m in compiled.messages[1:])


def test_native_marker_order_and_disabled_content_are_respected():
    preset = PromptPreset(id='custom', name='自定义',
        prompts=[PromptEntry(identifier=name, name=name, marker=True) for name in ['userDefinitions','charDefinitions','chatHistory']],
        prompt_order=[PromptOrderEntry(identifier=name) for name in ['userDefinitions','charDefinitions','chatHistory']])
    args = dict(marker_contents={'charDefinitions':'角色内容','userDefinitions':'Persona 内容'})
    result = compile_prompt(preset, Lorebook(id='empty',name='空'), 0, [], '本轮输入', **args)
    assert [m.content for m in result.messages] == ['Persona 内容','角色内容','本轮输入']
    preset.prompt_order[1].enabled = False
    result = compile_prompt(preset, Lorebook(id='empty',name='空'), 0, [], '本轮输入', **args)
    assert [m.content for m in result.messages] == ['Persona 内容','本轮输入']


def test_tts_failure_returns_readable_error_without_changing_history(llm, monkeypatch):
    import httpx
    provider_store.upsert_provider_profile('tts', TtsProviderProfile(id='broken', name='失败测试', endpoint='https://example.com/tts').model_dump())
    async def fail(self, text, profile):
        raise httpx.ConnectError('模拟连接失败')
    monkeypatch.setattr(companion_routes.HttpTts, 'synthesize', fail)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid))
        original = store.get_conversation(cid)
        response = client.post(f'/api/conversations/{cid}/messages/{original.messages[-1].id}/tts', json={})
        assert response.status_code == 502
        assert 'TTS 服务调用失败' in response.json()['detail']
        assert store.get_conversation(cid) == original
