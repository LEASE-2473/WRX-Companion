import base64
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import companion_store as store
from app.companion_core import core
from app.models import ChatMessage, TextTurn
from test_companion import FakeLlm, events

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5S8AAAAASUVORK5CYII='


def test_image_lifecycle(monkeypatch):
    fake = FakeLlm()
    monkeypatch.setattr(core, 'llm_for', lambda *a: fake)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        body = {'request_id': str(uuid4()), 'content': '', 'images': [PNG], 'search_mode': 'OFF'}
        url = f'/api/conversations/{cid}/messages/stream'
        events(client.post(url, json=body))
        before = store.get_conversation(cid).messages
        assert before[0].content == '' and before[0].images == [PNG]
        assert fake.calls[-1][-1].images == [PNG]
        wire = fake.calls[-1][-1].api_message()
        assert wire['content'][-1] == {'type': 'image_url', 'image_url': {'url': PNG}}
        assert events(client.post(url, json=body))[-1]['replayed']
        assert client.post(url, json={**body, 'images': []}).status_code == 422
        other = 'data:image/gif;base64,' + base64.b64encode(b'GIF89a1234').decode()
        assert client.post(url, json={**body, 'images': [other]}).status_code == 409
        regen = f'/api/conversations/{cid}/messages/{before[1].id}/regenerate'
        events(client.post(regen, json={'request_id': str(uuid4()), 'search_mode': 'OFF'}))
        assert fake.calls[-1][-1].images == [PNG]
        branch = store.branch_conversation(cid, before[1].id, 'regenerate')
        assert branch['resend_content'] == '' and branch['resend_images'] == [PNG]
        branch = store.branch_conversation(cid, before[0].id, 'branch')
        assert branch['conversation'].messages[0].images == [PNG]
        edit = store.branch_conversation(cid, before[0].id, 'edit', '看这张图')
        assert edit['resend_images'] == [PNG]
        events(client.post(url, json={'request_id': str(uuid4()), 'content': '接着聊', 'search_mode': 'OFF'}))
        assert all(not m.images for m in fake.calls[-1])
        assert any('仅包含图片' in m.content for m in fake.calls[-1])
        assert PNG not in str([m.api_message() for m in fake.calls[-1]])
        assert client.get(f'/api/conversations/{cid}').json()['messages'][0]['images'] == [PNG]


def test_image_validation_and_text_compatibility():
    assert ChatMessage(role='user', content='hello').api_message() == {'role': 'user', 'content': 'hello'}
    for images in (['https://example.com/a.png'], ['data:image/png;base64,bm90LXBuZw=='], [PNG] * 5, ['data:image/png;base64,%%%']):
        with pytest.raises(ValueError):
            TextTurn(request_id='test', images=images)


def test_compiler_omits_old_images_and_keeps_current_images():
    from app.models import Lorebook
    from app.prompt_store import default_wrx_preset
    from app.prompt_compiler import compile_prompt
    old = ChatMessage(role='user', content='旧图文字', images=[PNG])
    compiled = compile_prompt(default_wrx_preset(), Lorebook(id='test', name='test'), 1, [old], '新图文字', current_images=[PNG])
    assert all(not m.images for m in compiled.messages[:-1])
    assert any(m.content == '旧图文字' for m in compiled.messages)
    assert compiled.messages[-1].images == [PNG]
    assert old.images == [PNG]


def test_provider_sends_actual_multimodal_payload(monkeypatch):
    import asyncio
    import json
    import httpx
    from app import providers
    from app.models import LlmProviderProfile
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"看到了"}}]}\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(providers, '_LLM_HTTP_CLIENT', client)
            llm = providers.OpenAICompatibleLlm(LlmProviderProfile(id='v', name='v', api_key='fake', model='vision', base_url='https://test.invalid/v1'))
            assert await llm.complete([ChatMessage(role='user', content='看这张图', images=[PNG])]) == '看到了'
    asyncio.run(run())
    assert seen[0]['messages'][0]['content'] == [{'type': 'text', 'text': '看这张图'}, {'type': 'image_url', 'image_url': {'url': PNG}}]
