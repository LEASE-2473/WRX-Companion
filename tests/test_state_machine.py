import asyncio
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app import companion_store as store, heartbeat
from app.main import app
from app.models import HeartbeatSettings
from app.state_machine import calculate


def user_at(cid, when):
    message = store.new_message('user', '还醒着', 'Asia/Shanghai', 'web', None)
    message.timestamp = when.isoformat()
    with store.database() as db:
        store._insert_message(db, cid, message)


def test_curves_night_and_release():
    c = store.create_conversation()
    now = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)  # 本地凌晨两点
    assert calculate(c, now=now, noise=0)['desire_to_act'] == 0
    user_at(c.id, now - timedelta(minutes=5))
    c = store.get_conversation(c.id)
    night = calculate(c, now=now, noise=0)
    assert night['energy'] < 25 and night['worry'] == 90
    assert night['desire_to_act'] >= night['threshold']
    relieved = calculate(c, {'released_at': (now + timedelta(seconds=1)).isoformat()}, now=now + timedelta(seconds=2), noise=0)
    assert relieved['worry'] == 0 and relieved['desire_to_act'] < 75
    day = now + timedelta(hours=12)
    high = calculate(c, now=day, noise=0)
    assert high['longing'] > 90 and high['worry'] == 0
    low = calculate(c, {'released_at': day.isoformat()}, now=day, noise=0)
    assert 9 <= low['longing'] <= 11 and low['desire_to_act'] < 75
    assert calculate(c, now=now-timedelta(days=1), noise=0)['longing'] == 0


def test_state_persistence_isolation_and_delete():
    c = store.create_conversation()
    other = store.create_conversation()
    user_at(c.id, store.utcnow() - timedelta(hours=24))
    first = store.companion_state(c.id)
    second = store.companion_state(c.id)
    assert first['noise'] == second['noise']
    assert first['longing'] > 90
    assert store.companion_state(other.id)['longing'] == 0
    with TestClient(app) as client:
        assert client.get(f'/api/conversations/{c.id}/state').json()['conversation_id'] == c.id
        assert client.get('/api/conversations/missing/state').status_code == 404
    store.delete_conversation(c.id)
    with store.database() as db:
        assert not db.execute('SELECT 1 FROM companion_states WHERE conversation_id=?', (c.id,)).fetchone()


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
