from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import companion_store as store
from app.companion_core import core
from test_companion import FakeLlm, events, send


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
        url=f'/api/conversations/{cid}/messages/{before[1].id}/regenerate'
        body={'request_id':rid,'content':'第一问','timezone':'Asia/Shanghai','search_mode':'OFF'}
        result=events(client.post(url,json=body))[-1]
        assert result['type']=='complete'
        after=store.get_conversation(cid).messages
        assert len(after)==4 and after[1].id==before[1].id and after[1].content=='新回复'
        assert after[0]==before[0] and after[2:]==before[2:]
        assert not any('后续问题' in m.content or '旧回复' in m.content for m in fake.calls[-1])
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
