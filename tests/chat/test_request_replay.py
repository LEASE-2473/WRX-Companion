import asyncio
from datetime import timedelta
import pytest
from app.chat import store
from app.chat.core import core
from app.models import TokenUsage
from tests.chat.test_companion import FakeLlm
from tests.chat.test_images import PNG


def test_debug_clear_reconnect_replay_and_fresh_failed_context(monkeypatch):
    fake=FakeLlm('已完成',delay=.03)
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation()
        first=core.submit(conv.id,'first','第一问',conv.timezone,search_mode='OFF')
        assert core.submit(conv.id,'first','第一问',conv.timezone,search_mode='OFF') is first
        await first.task
        with store.database() as db: db.execute('UPDATE requests SET debug=NULL')
        replay=core.submit(conv.id,'first','第一问',conv.timezone,search_mode='OFF')
        assert [e async for e in core.events(replay)][-1]['reply']=='已完成'
        assert len(fake.calls)==1
        fake.reply=''
        failed=core.submit(conv.id,'failed','第二问',conv.timezone,search_mode='OFF')
        await failed.task
        assert store.get_request('failed')['status']=='error'
        earlier=store.get_conversation(conv.id).messages[0]
        store.edit_user_message(conv.id,earlier.id,'人工更正历史正文')
        with store.database() as db: db.execute('UPDATE requests SET debug=NULL')
        fake.reply='重试成功'
        retry=core.submit(conv.id,'failed','第二问',conv.timezone,search_mode='OFF')
        await retry.task
        assert any('人工更正历史正文' in m.content for m in fake.calls[-1])
        assert store.get_request('failed')['attempt']==2
        assert len(fake.calls)==3
    asyncio.run(scenario())


def test_own_photo_retry_and_resend_do_not_restore_history(monkeypatch):
    now=store.utcnow().replace(microsecond=0)
    monkeypatch.setattr(store,'utcnow',lambda:now)
    fake=FakeLlm('已看到')
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        nonlocal now
        conv=store.create_conversation()
        store.begin_turn(conv.id,'photo','自己的图',conv.timezone,'web','OFF',images=[PNG])
        store.fail_turn('photo','模型失败')
        now+=timedelta(minutes=6)
        retry=core.submit(conv.id,'photo','自己的图',conv.timezone,search_mode='OFF',images=[PNG])
        await retry.task
        assert fake.calls[-1][-1].images==[PNG]
        ordinary=core.submit(conv.id,'followup','普通追问',conv.timezone,search_mode='OFF')
        await ordinary.task
        assert not any(m.images for m in fake.calls[-1])
        latest=store.get_conversation(conv.id).messages[-2]
        resend=core.submit(conv.id,'resend','新追问',conv.timezone,search_mode='OFF',resend_mid=latest.id)
        await resend.task
        assert not any(m.images for m in fake.calls[-1])
        conv2=store.create_conversation()
        store.begin_turn(conv2.id,'own','自身附件',conv2.timezone,'web','OFF',images=[PNG])
        store.finish_turn('own','原回复',TokenUsage(),[],[],{})
        target=store.get_conversation(conv2.id).messages[0]
        now+=timedelta(minutes=6)
        job=core.submit(conv2.id,'own-resend','修改正文',conv2.timezone,search_mode='OFF',resend_mid=target.id)
        await job.task
        assert fake.calls[-1][-1].images==[PNG]
        before=store.get_conversation(conv2.id).messages
        now+=timedelta(hours=3)
        with pytest.raises(ValueError,match='重新上传'):
            core.submit(conv2.id,'expired','修改正文',conv2.timezone,search_mode='OFF',resend_mid=target.id)
        after=store.get_conversation(conv2.id).messages
        assert [m.content for m in before]==[m.content for m in after]
        assert len(fake.calls)==4
    asyncio.run(scenario())


def test_successful_device_marker_survives_failed_attempt():
    conv=store.create_conversation()
    store.begin_turn(conv.id,'device','控制',conv.timezone,'web','OFF')
    attempt=store.get_request('device')['attempt']
    store.claim_device_action('device','toy_stop',attempt)
    store.complete_device_action('device','toy_stop')
    store.fail_turn('device','设备成功后模型失败')
    store.begin_turn(conv.id,'device','控制',conv.timezone,'web','OFF')
    assert store.device_effect('device')['status']=='accepted'
    with pytest.raises(store.Conflict,match='已领取或执行'):
        store.claim_device_action('device','toy_stop',attempt+1)


def test_legacy_failed_request_without_result_cannot_repeat_unknown_device():
    import sqlite3
    from app.chat.storage_format import initialize_requests
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE requests(id TEXT,conversation_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,result TEXT,extra_usage TEXT,fingerprint TEXT)')
    db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?)',('old','conversation','error','2026-10-01T00:00:00Z',None,None,None,'a'*64))
    initialize_requests(db)
    import json
    assert json.loads(db.execute('SELECT execution FROM requests').fetchone()[0])['device_effect']['status']=='legacy_unverified'
    assert 'result' not in {r[1] for r in db.execute('PRAGMA table_info(requests)')}
    db.close()
