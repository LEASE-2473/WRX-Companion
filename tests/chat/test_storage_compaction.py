import json
from datetime import timedelta
import pytest
from app.chat import store, images
from app.chat.maintenance import clean_database
from app.common import identity
from app.models import TokenUsage
from tests.chat.test_images import PNG


def test_base62_collision_retry(monkeypatch):
    sequence=iter('A'*16+'B'*16)
    monkeypatch.setattr(identity.secrets,'choice',lambda _:next(sequence))
    value=identity.new_id(lambda value:value=='AAAA-AAAA-AAAA-AAAA')
    assert value=='BBBB-BBBB-BBBB-BBBB' and identity.valid_id(value)


def test_message_and_debug_storage_are_separate():
    conv=store.create_conversation()
    rid=identity.new_id()
    store.begin_turn(conv.id,rid,'图',conv.timezone,'web','OFF',images=[PNG])
    store.finish_turn(rid,'正文',TokenUsage(input_tokens=12),[],[],{'debug':{'nested':[{'image':PNG}]}})
    with store.database() as db:
        docs=[json.loads(r[0]) for r in db.execute('SELECT document FROM messages')]
        assert all(not (set(d)&{'id','role','request_id','usage','timezone','local_datetime','images'}) for d in docs)
        row=db.execute('SELECT fingerprint,execution,debug FROM requests WHERE id=?',(rid,)).fetchone()
        assert isinstance(row[0],bytes) and len(row[0])==32
        assert 'debug' not in json.loads(row[1]) and PNG not in row[2]
        assert 'result' not in {r[1] for r in db.execute('PRAGMA table_info(requests)')}
        assert db.execute('SELECT typeof(content) FROM images').fetchone()[0]=='blob'
    from app.chat.routes import request_status
    wire=request_status(conv.id,rid)
    assert 'fingerprint' not in wire and 'debug' not in wire
    json.dumps(wire)
    assert 'debug' not in store.get_request(rid)
    assert store.get_request(rid,include_debug=True)['debug'] is not None


def test_image_window_count_branch_and_cleanup(monkeypatch):
    now=store.utcnow().replace(microsecond=0)
    monkeypatch.setattr(store,'utcnow',lambda:now)
    conv=store.create_conversation()
    store.begin_turn(conv.id,'image','',conv.timezone,'web','OFF',images=[PNG])
    store.finish_turn('image','已收到',TokenUsage(),[],[],{})
    mid=store.get_conversation(conv.id).messages[0].id
    assert store.model_images(mid)==[PNG]
    with store.database() as db:
        assert images.urls(db,mid,model=True,now=now+timedelta(minutes=5))==[PNG]
        assert images.urls(db,mid,model=True,now=now+timedelta(minutes=5,seconds=1))==[]
    for n in range(4):
        rid=f'user-{n}';store.begin_turn(conv.id,rid,'追问',conv.timezone,'web','OFF')
        store.finish_turn(rid,'答',TokenUsage(),[],[],{})
    assert store.model_images(mid)==[PNG]
    other=store.create_conversation()
    store.begin_turn(other.id,'other','不计入',other.timezone,'web','OFF')
    store.finish_turn('other','答',TokenUsage(),[],[],{})
    assert store.model_images(mid)==[PNG]
    store.begin_turn(conv.id,'fifth','第五条',conv.timezone,'web','OFF')
    assert store.model_images(mid)==[]
    # 运行中的会话暂缓物理删除。
    with store.database() as db:
        assert clean_database(db,now+timedelta(hours=3))['expired_images']==0
        assert db.execute('SELECT content FROM images WHERE message_id=?',(mid,)).fetchone()[0] is not None
    store.finish_turn('fifth','答',TokenUsage(),[],[],{})
    with store.database() as db:
        assert clean_database(db,now+timedelta(hours=3))['expired_images']==1
        assert db.execute('SELECT content FROM images WHERE message_id=?',(mid,)).fetchone()[0] is None
    historical=store.get_conversation(conv.id).messages[0]
    assert historical.image_count==1 and historical.images==[]


def test_same_second_retry_uses_version_and_dedup(monkeypatch):
    now=store.utcnow().replace(microsecond=0)
    monkeypatch.setattr(store,'utcnow',lambda:now)
    conv=store.create_conversation();rid=identity.new_id()
    store.begin_turn(conv.id,rid,'原文',conv.timezone,'web','OFF')
    old=store.get_request(rid)['attempt']
    store.fail_turn(rid,'中断',attempt_started_at=old)
    store.begin_turn(conv.id,rid,'原文',conv.timezone,'web','OFF')
    assert store.get_request(rid)['attempt']==old+1
    with pytest.raises(store.Conflict): store.finish_turn(rid,'迟到',TokenUsage(),[],[],{},attempt_started_at=old)
    store.finish_turn(rid,'完成',TokenUsage(),[],[],{},attempt_started_at=old+1)
    assert store.begin_turn(conv.id,rid,'原文',conv.timezone,'web','OFF') is False
    with pytest.raises(store.Conflict): store.begin_turn(conv.id,rid,'不同正文',conv.timezone,'web','OFF')
