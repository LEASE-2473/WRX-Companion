from uuid import uuid4
import asyncio
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.chat import store
from app.chat.core import core
from tests.chat.test_companion import FakeLlm, events, send


def test_regenerate_replaces_only_target_and_replays(monkeypatch):
    fake=FakeLlm('旧回复')
    monkeypatch.setattr(core,'llm_for',lambda *a: fake)
    with TestClient(app) as client:
        cid=client.post('/api/conversations').json()['id']
        events(send(client,cid,'第一问'))
        events(send(client,cid,'后续问题'))
        before=store.get_conversation(cid).messages
        fake.reply='新回复'
        rid=str(uuid4())
        url=f'/api/conversations/{cid}/messages/{before[3].id}/regenerate'
        body={'request_id':rid,'content':'后续问题','timezone':'Asia/Shanghai','search_mode':'OFF'}
        result=events(client.post(url,json=body))[-1]
        assert result['type']=='complete'
        after=store.get_conversation(cid).messages
        assert len(after)==4 and after[3].id==before[3].id and after[3].content=='新回复'
        assert after[:3]==before[:3]
        assert fake.calls[-1][-1].content=='后续问题'
        assert sum('旧回复' in m.content for m in fake.calls[-1])==1
        assert client.post(f'/api/conversations/{cid}/messages/{before[1].id}/regenerate',json={**body,'request_id':str(uuid4())}).status_code==409
        assert events(client.post(url,json=body))[-1]['replayed']
        assert len(fake.calls)==3


def test_regenerate_failure_keeps_old_reply(monkeypatch):
    fake=FakeLlm('旧回复')
    monkeypatch.setattr(core,'llm_for',lambda *a: fake)
    with TestClient(app) as client:
        cid=client.post('/api/conversations').json()['id']
        events(send(client,cid))
        before=store.get_conversation(cid).messages
        fake.reply=''
        result=events(client.post(f'/api/conversations/{cid}/messages/{before[1].id}/regenerate',json={'request_id':str(uuid4()),'content':'你好','search_mode':'OFF'}))[-1]
        assert result['type']=='error'
        assert store.get_conversation(cid).messages==before


def test_resend_edits_in_place_preserves_later_and_replays(monkeypatch):
    fake = FakeLlm('旧回复')
    monkeypatch.setattr(core, 'llm_for', lambda *a: fake)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid, '原问题'))
        events(send(client, cid, '后续问题'))
        before = store.get_conversation(cid).messages
        fake.reply = '修改后回复'
        url = f'/api/conversations/{cid}/messages/{before[2].id}/resend'
        body = {'request_id': str(uuid4()), 'content': '修改后问题', 'search_mode': 'OFF'}
        assert events(client.post(url, json=body))[-1]['type'] == 'complete'
        after = store.get_conversation(cid).messages
        assert [m.id for m in after] == [m.id for m in before]
        assert after[2].content == '修改后问题' and after[3].content == '修改后回复'
        assert after[:2] == before[:2]
        assert fake.calls[-1][-1].content == '修改后问题'
        assert not any('后续问题' in m.content for m in fake.calls[-1])
        assert sum('旧回复' in m.content for m in fake.calls[-1])==1
        assert client.post(f'/api/conversations/{cid}/messages/{before[0].id}/resend',json={**body,'request_id':str(uuid4())}).status_code==409
        assert events(client.post(url, json=body))[-1]['replayed']
        assert len(fake.calls) == 3
        assert client.delete(f'/api/conversations/{cid}').status_code == 200


def test_resend_failure_and_unanswered_last_user(monkeypatch):
    fake = FakeLlm('旧回复')
    monkeypatch.setattr(core, 'llm_for', lambda *a: fake)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid, '原问题'))
        before = store.get_conversation(cid).messages
        fake.reply = ''
        body = {'request_id': str(uuid4()), 'content': '新问题', 'search_mode': 'OFF'}
        url = f'/api/conversations/{cid}/messages/{before[0].id}/resend'
        assert events(client.post(url, json=body))[-1]['type'] == 'error'
        assert store.get_conversation(cid).messages == before
        fake.reply = '重发回复'
        store.begin_turn(cid, 'unanswered', '未回答问题', 'Asia/Shanghai', 'web', 'OFF')
        store.fail_turn('unanswered', '失败')
        target = store.get_conversation(cid).messages[-1]
        body['request_id'] = str(uuid4())
        assert events(client.post(f'/api/conversations/{cid}/messages/{target.id}/resend', json=body))[-1]['type'] == 'complete'
        after = store.get_conversation(cid).messages
        assert len(after) == 4 and after[2].id == target.id
        assert after[2].content == '新问题' and after[3].content == '重发回复'


def test_resend_stop_keeps_original_and_preserves_image_only_retry(monkeypatch):
    fake = FakeLlm('新回复', delay=60)
    monkeypatch.setattr(core, 'llm_for', lambda *a: fake)
    async def scenario():
        conv = store.create_conversation()
        images = ['data:image/png;base64,iVBORw0KGgo=']
        store.begin_turn(conv.id, 'image', '', 'Asia/Shanghai', 'web', 'OFF', images=images)
        store.fail_turn('image', '测试失败')
        before = store.get_conversation(conv.id).messages
        job = core.submit(conv.id, 'resend-image', '', 'Asia/Shanghai', search_mode='OFF', resend_mid=before[0].id)
        await asyncio.sleep(0.02)
        await core.cancel(conv.id, job.request_id)
        assert store.get_conversation(conv.id).messages == before
        assert store.get_conversation(conv.id).pending_request_id is None
        fake.delay = 0
        retry = core.submit(conv.id, 'resend-image', '', 'Asia/Shanghai', search_mode='OFF', resend_mid=before[0].id)
        await retry.task
        after = store.get_conversation(conv.id).messages
        assert len(after) == 2 and after[0].id == before[0].id
        assert after[0].images == fake.calls[-1][-1].images == images
    asyncio.run(scenario())


def test_delete_keeps_branches_and_rejects_busy():
    with TestClient(app) as client:
        cid=client.post('/api/conversations').json()['id']
        store.begin_turn(cid,'busy','你好','Asia/Shanghai','web','OFF')
        assert client.delete(f'/api/conversations/{cid}').status_code==409
        store.fail_turn('busy','测试结束')
        mid=store.get_conversation(cid).messages[0].id
        branch=store.branch_conversation(cid,mid)['conversation']
        assert client.delete(f'/api/conversations/{cid}').json()['ok']
        assert client.get(f'/api/conversations/{cid}').status_code==404
        kept=store.get_conversation(branch.id)
        assert kept.messages and not kept.parent_conversation_id


def test_edit_user_only_preserves_reply_metadata_and_rejects_invalid(monkeypatch):
    fake = FakeLlm('保留回复')
    monkeypatch.setattr(core, 'llm_for', lambda *a: fake)
    with TestClient(app) as client:
        cid = client.post('/api/conversations').json()['id']
        events(send(client, cid, '原正文'))
        before = store.get_conversation(cid).messages
        url = f'/api/conversations/{cid}/messages/{before[0].id}'
        response = client.patch(url, json={'content': '修改正文'})
        assert response.status_code == 200
        after = store.get_conversation(cid).messages
        assert after[0] == before[0].model_copy(update={'content': '修改正文'})
        assert after[1:] == before[1:] and len(fake.calls) == 1
        assert client.patch(url, json={'content': '  '}).status_code == 422
        assert client.patch(f'/api/conversations/{cid}/messages/{before[1].id}', json={'content': 'AI'}).status_code == 422
        assert client.patch(f'/api/conversations/{cid}/messages/missing', json={'content': '无'}).status_code == 404
        with store.database() as db:
            db.execute("UPDATE requests SET status='running' WHERE id=?", (before[0].request_id,))
        assert client.patch(url, json={'content': '忙碌编辑'}).status_code == 409
        assert store.get_conversation(cid).messages == after
