"""仅用于离线界面验收，所有模型/搜索均为模拟。不会使用正式数据库。"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['WRX_DB_PATH'] = str(Path(tempfile.mkdtemp(prefix='wrx-ui-')) / 'preview.sqlite3')

from test_companion import FakeLlm
from app import companion_core, companion_store, companion_routes, search, provider_store
from app.models import SearchSettings, TtsProviderProfile
from app.providers import wav_from_pcm
from app.main import app


class PreviewLlm(FakeLlm):
    async def stream_complete(self, messages):
        self.calls.append(messages)
        if '主动唤醒事件' in messages[-1].content:
            yield '{"action":"SEND_MESSAGE","message":"刚刚想起你，今天过得怎么样？（离线模拟）"}'
        else:
            yield '你好，我在这里。\n'
            yield '**这是一条离线模拟回复**，用于检查保存、角色与用量。'


companion_core.core.llm_for = lambda *args: PreviewLlm(decision='{"search":true,"query":"模拟查询"}')


async def preview_search(query, config):
    return [{'title': '离线模拟来源', 'url': 'https://example.com', 'content': '仅用于界面验收。'}]


companion_core.search_web = preview_search
search.save_search_settings(SearchSettings(enabled=True, api_key='fake-preview-key'))
provider_store.PROVIDER_PROFILES_FILE = Path(os.environ['WRX_DB_PATH']).parent / 'preview-providers.json'
provider_store.upsert_provider_profile('tts', TtsProviderProfile(id='preview', name='离线模拟音色', endpoint='https://example.com/tts').model_dump())

async def preview_tts(self, text, profile):
    return wav_from_pcm(b'\x00\x00' * 24000, 24000)

companion_routes.HttpTts.synthesize = preview_tts

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=2474)
