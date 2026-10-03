import asyncio
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.chat import store
from app.main import app
from app.memory import system,system_schema as schema,role
from tests.memory.test_system_memory import apply


def test_four_tables_explicit_fields_sequences_and_role_binding():
    conv=store.create_conversation();other=store.create_conversation()
    apply(conv,{'summary':{'content':'总结','tag':'聊天'},'people':[{'name':'奶奶','history':'吃饭'}],'items':[{'name':'钥匙','location':'抽屉'}],'agreements':[{'content':'周末联系'}]})
    with store.database() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='system_memories'").fetchone()
        for kind,table in schema.TABLES.items():
            info=db.execute(f'PRAGMA table_xinfo({table})').fetchall()
            assert {r[1] for r in info}=={'sequence','character_id','conversation_id','range_start','range_end','mode','vector','vector_signature','vectorized',*schema.FIELDS[kind]}
            assert db.execute(f'SELECT sequence,character_id,conversation_id,vectorized FROM {table}').fetchone()[:]==(1,'default',conv.id,0)
            assert next(r for r in info if r[1]=='vectorized')[6]==2 # VIRTUAL派生列
    assert len(system.rows('default',other.id))==4
    with TestClient(app) as client:
        data=client.get(f'/api/system-memory/default?conversation_id={conv.id}').json()['rows']
        person=next(r for r in data if r['kind']=='person')
        item=next(r for r in data if r['kind']=='item')
        assert person['id']=='person:1' and item['id']=='item:1'
        assert client.put(f"/api/system-memory/default/{person['id']}?conversation_id={conv.id}",json={'history':'用户编辑'}).status_code==200
        assert client.delete(f"/api/system-memory/default/{item['id']}?conversation_id={conv.id}").status_code==200
    assert next(r for r in system.rows('default',conv.id) if r['kind']=='person')['history']=='用户编辑'
    with pytest.raises(ValueError):apply(conv,{'people':[{'name':'奶奶','id':'item:1'}]})
    with pytest.raises(ValueError):system.Settings(scope='conversation')


def test_legacy_migration_preserves_each_kind_vectors_and_is_idempotent():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE system_memories(id TEXT PRIMARY KEY,character_id TEXT,conversation_id TEXT,scope TEXT,kind TEXT,name TEXT,content TEXT,tag TEXT,relationship TEXT,history TEXT,impression TEXT,description TEXT,location TEXT,range_start TEXT,range_end TEXT,mode TEXT,vector TEXT,vector_signature TEXT)")
    for i,kind in enumerate(schema.TABLES):
        db.execute('INSERT INTO system_memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(f'old-{i}','char','conv','conversation',kind,'姓名','正文','标签','亲人','旧历史','喜欢','描述','抽屉','2026-10-01','2026-10-02','cold','[1.25,0.5]' if i!=3 else '[]','model'))
    schema.initialize(db);schema.initialize(db)
    rows=schema.rows(db,'char');assert len(rows)==4
    for r in rows:
        assert r['scope']=='character' and r['conversation_id']=='conv'
        assert all(r[key] for key in schema.FIELDS[r['kind']])
        assert r['range_start']=='2026-10-01' and r['range_end']=='2026-10-02'
        if r['kind']=='agreement':assert r['mode']=='hot' and not r['vectorized']
        else:
            assert r['vector']==[1.25,0.5] and r['vectorized']
            assert db.execute(f"SELECT typeof(vector) FROM {schema.TABLES[r['kind']]}").fetchone()[0]=='blob'
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    db.close()


def test_vector_candidates_no_chunks_stale_fallback_and_edit_invalidates(monkeypatch):
    conv=store.create_conversation();apply(conv,{'summary':{'content':'原总结'}})
    cfg=role.settings();cfg.vector.enabled=True;role.save_settings(cfg.model_dump())
    rid=system.rows('default',conv.id)[0]['id']
    async def embed(*args):return [[1,0]]
    monkeypatch.setattr(role,'get_embeddings',embed)
    asyncio.run(system.change_mode('default',conv.id,rid,'cold'))
    async def retrieve(query,state):return [c.id for lib in state.libraries for c in lib.chunks]
    monkeypatch.setattr(role,'retrieve_vector_memories',retrieve)
    assert asyncio.run(role.recall('default',conv.id,'总结'))==[rid]
    assert not system.hot_context('default',conv.id)
    cfg.vector.model='another-model';role.save_settings(cfg.model_dump())
    assert system.hot_context('default',conv.id)
    assert not asyncio.run(role.recall('default',conv.id,'总结'))
    with TestClient(app) as client:
        data=client.get(f'/api/system-memory/default?conversation_id={conv.id}').json()['rows'][0]
        assert data['mode']=='cold' and not data['vectorized']
        assert client.put(f'/api/system-memory/default/{rid}?conversation_id={conv.id}',json={'content':'新总结'}).status_code==200
    row=system.rows('default',conv.id)[0]
    assert row['mode']=='hot' and row['vector'] is None and not row['vectorized']
    async def invalid(*args):return [[]]
    monkeypatch.setattr(role,'get_embeddings',invalid)
    with pytest.raises(ValueError):asyncio.run(system.change_mode('default',conv.id,rid,'cold'))
    assert system.rows('default',conv.id)[0]['mode']=='hot'


def test_underscore_table_names_rename_preserving_sequences_and_data():
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    schema.initialize(db)
    db.execute("INSERT INTO system_items(sequence,character_id,conversation_id,range_start,range_end,name) VALUES (7,'char','conv','start','end','钥匙')")
    db.execute('ALTER TABLE system_items RENAME TO _system_items')
    db.execute('ALTER TABLE system_agreements RENAME TO _system_agreements')
    schema.initialize(db);schema.initialize(db)
    assert db.execute('SELECT sequence,name FROM system_items').fetchone()[:]==(7,'钥匙')
    db.execute("INSERT INTO system_items(character_id,conversation_id,range_start,range_end,name) VALUES ('char','conv','start','end','书')")
    assert db.execute("SELECT sequence FROM system_items WHERE name='书'").fetchone()[0]==8
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('_system_items','_system_agreements')").fetchone()
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    db.close()
