import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import providers
from app.main import app
from app.models import ChatMessage, LlmProviderProfile


@pytest.mark.parametrize('temperature', [0, 0.85, 2, None])
def test_saved_preset_temperature_reaches_provider(monkeypatch, temperature):
    with TestClient(app) as client:
        state = client.post('/api/prompt-presets/new', json={'name': '温度测试'}).json()
        preset = next(p for p in state['presets'] if p['id'] == state['active_preset_id'])
        preset['generation_parameters'] = {'top_p': 0.9}
        if temperature is not None:
            preset['generation_parameters']['temperature'] = temperature
        response = client.put('/api/prompt-presets/' + preset['id'], json=preset)
        assert response.status_code == 200
        saved = next(p for p in response.json()['presets'] if p['id'] == preset['id'])
        exported = client.get('/api/prompt-presets/' + preset['id'] + '/export').json()
        assert exported['generation_parameters'] == saved['generation_parameters']

    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(providers, '_LLM_HTTP_CLIENT', client)
            llm = providers.OpenAICompatibleLlm(LlmProviderProfile(id='test', name='test', api_key='fake', model='test', base_url='https://test.invalid/v1'))
            llm.set_generation_parameters(saved['generation_parameters'])
            assert await llm.complete([ChatMessage(role='user', content='你好')]) == '你好'

    asyncio.run(run())
    assert seen[0]['top_p'] == 0.9
    if temperature is None:
        assert 'temperature' not in seen[0]
    else:
        assert seen[0]['temperature'] == temperature
