import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.chat import store
from app.chat.core import core
from app.models import Character, ChatMessage, TokenUsage
from app.user import store as profile, service
from app.user.context import context
from app.user.models import Entry, Profile
from app.user.prompt_files import PROMPT, LEGACY_PROMPT
from zoneinfo import ZoneInfo
from app.skills import runtime as skills


def test_global_identity_core_and_keyword_context():
    a = store.save_character(Character(name='甲', user_name='旧称呼', persona='旧介绍'))
    b = store.save_character(Character(name='乙', user_name='旧称呼', persona='旧介绍'))
    value = profile.load()
    assert value.name == '旧称呼' and value.core == '旧介绍'
    value.name = 'LEASE'
    value.core = '始终理解 {{user}} 的交流偏好'
    value.entries = [Entry(tag='打印', keywords=['喷嘴'], content='使用 A1'), Entry(tag='工作', keywords=['上班'], content='工作背景')]
    profile.save(value)
    for character in (a, b):
        conv = store.create_conversation(character_id=character.id)
        compiled, _ = core.context(conv, character, '喷嘴怎么选', 'web')
        text = '\n'.join(m.content for m in compiled.messages)
        assert '称呼：LEASE' in text and '始终理解 LEASE' in text and '使用 A1' in text
        assert '工作背景' not in text and '旧介绍' not in text


def test_tag_activation_only_current_and_previous_user_turn():
    value = Profile(entries=[Entry(tag='打印', keywords=['喷嘴'], content='打印背景')])
    history = [ChatMessage(role='user', content='喷嘴堵了'), ChatMessage(role='assistant', content='喷嘴需要检查')]
    assert '打印背景' in context(value, '怎么检查？', history)
    history += [ChatMessage(role='user', content='今天很累'), ChatMessage(role='assistant', content='先放下喷嘴的事吧')]
    assert '打印背景' not in context(value, '想休息', history)
    assert '打印背景' in context(value, '再聊喷嘴', history)
    assert '打印背景' not in context(value, '你好', [ChatMessage(role='assistant', content='喷嘴')])


def test_old_default_prompt_upgrades_without_overwriting_custom_prompt():
    value = Profile(summary_prompt=LEGACY_PROMPT, revision=4)
    store.save_setting(profile.KEY, value.model_dump())
    upgraded = profile.load()
    assert upgraded.summary_prompt == PROMPT and upgraded.revision == 5
    assert profile.load().revision == 5
    upgraded.summary_prompt = '用户自定义的提示词'
    profile.save(upgraded)
    assert profile.load().summary_prompt == '用户自定义的提示词'


def test_candidates_transaction_replay_regenerate_and_disabled():
    conv = store.create_conversation()
    raw = '知道了<app_call name="append_profile_candidate">{"tag":"偏好","keywords":["建议"],"content":"先理解再建议"}</app_call>'
    actions, error = skills.write_actions(raw)
    assert not error and skills.visible(raw) == '知道了'
    with store.database() as db:
        skills.commit(db, conv, 'candidate', actions, ['source'])
        skills.commit(db, conv, 'candidate', actions, ['source'])
        assert len(profile.candidates(db)) == 1
        skills.commit(db, conv, 'regenerate', actions, [], regenerated=True)
        assert len(profile.candidates(db)) == 1
    from app.skills import configuration
    configuration.save('profile-update', {'enabled': False, 'injection': 'on_demand'})
    assert skills.write_actions(raw)[1]


def test_profile_skill_two_requests():
    class Fake:
        last_usage = TokenUsage()
        def __init__(self, repeat=False):
            self.count = 0
            self.repeat = repeat
        async def stream_complete(self, messages):
            self.count += 1
            yield '<app_call name="read_skill">{"name":"profile-update"}</app_call>' if self.count == 1 or self.repeat else '回应<app_call name="append_profile_candidate">{"tag":"偏好","content":"新偏好","keywords":[]}</app_call>'
    async def run():
        conv = store.create_conversation()
        fake = Fake()
        async for _ in skills.stream(fake, [ChatMessage(role='user', content='记住')], conv.id, [], []):
            pass
        assert fake.count == 2
        fake = Fake(True)
        with pytest.raises(ValueError, match='最多两次'):
            async for _ in skills.stream(fake, [], conv.id, [], []):
                pass
        assert fake.count == 2
    asyncio.run(run())


def test_background_full_global_day_and_protected_fields(monkeypatch):
    conv = store.create_conversation()
    conv2 = store.create_conversation(character_id=store.save_character(Character(name='乙')).id)
    date = store.utcnow().astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with store.database() as db:
        for i, c in enumerate((conv, conv2)):
            doc = {'id': f'm{i}', 'role': 'user', 'content': f'完整对话{i}', 'timestamp': store.utcnow().isoformat()}
            db.execute('INSERT INTO messages(id,conversation_id,role,document,origin_id) VALUES (?,?,?,?,?)', (doc['id'], c.id, 'user', store.dumps(doc), doc['id']))
        profile.commit_candidate(db, conv, 'pending', 0, {'tag': '偏好', 'keywords': [], 'content': '候选'}, [])
    value = profile.load(); value.name = 'LEASE'; value.core = '固定核心'; profile.save(value)
    captured = []
    class Fake:
        last_usage = TokenUsage(input_tokens=10)
        def __init__(self, _): pass
        async def complete(self, messages):
            captured.append(json.loads(messages[1].content))
            return '<user_profile>{"entries":[{"tag":"偏好","keywords":["倾诉"],"content":"先听"}]}</user_profile>'
    monkeypatch.setattr(service, 'resolve_llm', lambda **_: None)
    monkeypatch.setattr(service, 'OpenAICompatibleLlm', Fake)
    assert asyncio.run(service.summarize(date))['status'] == 'done'
    assert len(captured[0]['messages']) == 2 and len(captured[0]['candidates']) == 1
    assert captured[0]['profile']['core'] == '固定核心'
    assert profile.load().name == 'LEASE' and profile.load().core == '固定核心'
    assert asyncio.run(service.summarize(date))['status'] == 'already_processed'
    with store.database() as db: assert not profile.candidates(db)


def test_summary_failure_and_concurrent_edit_preserve_profile(monkeypatch):
    conv = store.create_conversation()
    with store.database() as db:
        profile.commit_candidate(db, conv, 'pending', 0, {'tag': '偏好', 'keywords': [], 'content': '候选'}, [])
    profile.load()
    class Fake:
        last_usage = TokenUsage()
        def __init__(self, _): pass
        async def complete(self, messages):
            value = profile.load(); value.core = '用户新编辑'; profile.save(value)
            return '<user_profile>{"entries":[]}</user_profile>'
    monkeypatch.setattr(service, 'resolve_llm', lambda **_: None)
    monkeypatch.setattr(service, 'OpenAICompatibleLlm', Fake)
    assert asyncio.run(service.summarize('2026-10-05'))['status'] == 'stale'
    assert profile.load().core == '用户新编辑'
    async def broken(self, messages): return '格式错误'
    monkeypatch.setattr(Fake, 'complete', broken)
    assert asyncio.run(service.summarize('2026-10-05'))['status'] == 'error'
    with store.database() as db: assert len(profile.candidates(db)) == 1


def test_api_revision_and_conflicting_legacy_data():
    store.save_character(Character(name='甲', user_name='A', persona='甲介绍'))
    store.save_character(Character(name='乙', user_name='B', persona='乙介绍'))
    client = TestClient(app)
    data = client.get('/api/user-profile').json()
    assert data['profile']['name'] == '用户' and not data['profile']['core']
    assert len(data['candidates']) == 2
    value = data['profile']; value['name'] = 'LEASE'
    assert client.put('/api/user-profile', json=value).status_code == 200
    assert client.put('/api/user-profile', json=value).status_code == 409


def test_import_preserves_settings_and_backs_up_and_rejects_invalid_data():
    client = TestClient(app)
    old = client.get('/api/user-profile').json()['profile']
    payload = {'name':'LEASE', 'core':'迁移核心', 'entries':[{'tag':'打印','keywords':['喷嘴'],'content':'打印背景'}], 'revision':old['revision']}
    response = client.post('/api/user-profile/import', json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved['entries'] == payload['entries']
    for key in ('summary_enabled','llm_profile_id','summary_hour','summary_prompt'):
        assert saved[key] == old[key]
    assert store.get_setting('global_user_profile_import_backup', None) == old
    assert client.post('/api/user-profile/import', json=payload).status_code == 409
    payload['revision'] = saved['revision']; payload['entries'][0]['content'] = ''
    assert client.post('/api/user-profile/import', json=payload).status_code == 422
    assert client.get('/api/user-profile').json()['profile'] == saved
