import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.chat import store
from app.chat import heartbeat
from app.main import app
from app.models import HeartbeatSettings
from app.chat.core import core
from app.character import state as emotion
from tests.chat.test_companion import FakeLlm


def test_no_legacy_state_when_emotions_disabled(monkeypatch):
    cfg=emotion.config().model_copy(update={'enabled':False})
    monkeypatch.setattr(emotion,'config',lambda:cfg)
    fake=FakeLlm('正常回复')
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation()
        job=core.submit(conv.id,'disabled','你好',conv.timezone,search_mode='OFF')
        await job.task
        assert job.events[-1]['type']=='complete'
        assert not any('本地模拟数值' in m.content or '当前内在状态' in m.content for m in fake.calls[-1])
        trace=store.get_request('disabled',include_debug=True)['debug']['prompt_trace']
        assert trace['role_emotion'] is None and 'companion_state' not in trace
        store.save_heartbeat(conv.id,HeartbeatSettings(enabled=True,cooldown_minutes=0,quiet_enabled=False))
        fake.reply='{"action":"NO_ACTION"}'
        job,error=core.heartbeat(conv.id)
        assert not error
        await job.task
        payload=__import__('json').loads(fake.calls[-1][-1].content.split('\n',1)[1])
        assert payload['state']=={'enabled':False}
        with store.database() as db:
            assert not db.execute("SELECT name FROM sqlite_master WHERE name='companion_states'").fetchone()
    asyncio.run(scenario())


def test_current_state_api_still_works_without_legacy_table():
    conv=store.create_conversation()
    with TestClient(app) as client:
        assert client.get(f'/api/conversations/{conv.id}/state').json()['conversation_id']==conv.id
        assert client.get('/api/conversations/missing/state').status_code==404
    with store.database() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='companion_states'").fetchone()


def test_low_tick_offers_model_a_decision(monkeypatch):
    c = store.create_conversation()
    store.save_heartbeat(c.id, HeartbeatSettings(enabled=True, cooldown_minutes=0))
    with store.database() as db:
        db.execute('UPDATE conversations SET next_heartbeat_at=? WHERE id=?', ((store.utcnow()-timedelta(minutes=1)).isoformat(), c.id))
    calls = []
    monkeypatch.setattr(heartbeat.core, 'heartbeat', lambda cid: calls.append(cid))
    asyncio.run(heartbeat.tick())
    assert calls == [c.id]
    assert store.heartbeat_logs(c.id) == []
