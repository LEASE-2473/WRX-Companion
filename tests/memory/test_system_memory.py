import asyncio
import json
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.memory import system as memory
from app.memory import role as role_memory
from app.chat import store
from app.models import TokenUsage, Character
from app.main import app

START=datetime(2026,10,1,tzinfo=timezone.utc)
END=START+timedelta(hours=1)

@pytest.fixture(autouse=True)
def isolated_cold_scheduler(monkeypatch):
    monkeypatch.setattr(memory, '_cold_tasks', {})
    monkeypatch.setattr(memory, '_cold_last_checks', {})


def test_auto_cold_age_failure_and_independent_scheduler(monkeypatch):
    conv = store.create_conversation()
    apply(conv, {'summary': {'content': '到期总结'}, 'agreements': [{'content': '失败时保留'}]})
    with store.database() as db:
        memory.apply(db, conv.character_id, conv.id, 'character', END.isoformat(),
                     (END + timedelta(hours=1)).isoformat(),
                     memory.Output.model_validate({'summary': {'content': '较新总结'}}))
    config = memory.settings()
    config.auto_cold_enabled = True
    config.auto_cold_hours = 4
    store.save_setting('system_memory', config.model_dump(exclude={'prompt'}))
    vector = role_memory.settings()
    vector.vector.enabled = True
    role_memory.save_settings(vector.model_dump())
    monkeypatch.setattr(store, 'utcnow', lambda: END + timedelta(hours=4))
    calls = []

    async def embed(texts, config):
        calls.extend(texts)
        if '失败时保留' in texts[0]:
            raise ValueError('模拟向量服务失败')
        return [[1.0, 2.0]]

    monkeypatch.setattr(role_memory, 'get_embeddings', embed)

    async def run():
        async def scanning():
            await asyncio.sleep(0)
        memory._tasks[conv.character_id] = asyncio.create_task(scanning())
        await memory.maintenance()
        first = memory._cold_tasks[conv.character_id]
        await memory.maintenance()
        assert memory._cold_tasks[conv.character_id] is first
        await first
        assert memory._tasks[conv.character_id].done()

    asyncio.run(run())
    result = {r['content']: r for r in memory.rows(conv.character_id, conv.id)}
    assert result['到期总结']['mode'] == 'cold'
    assert result['到期总结']['vector'] == [1.0, 2.0]
    assert result['较新总结']['mode'] == 'hot'
    assert result['失败时保留']['mode'] == 'hot'
    assert len(calls) == 2
    vector.vector.enabled = False
    role_memory.save_settings(vector.model_dump())
    asyncio.run(memory.auto_cold(conv.character_id, conv.id))
    assert len(calls) == 2
    vector.vector.enabled = True
    role_memory.save_settings(vector.model_dump())
    config.auto_cold_enabled = False
    store.save_setting('system_memory', config.model_dump(exclude={'prompt'}))
    asyncio.run(memory.auto_cold(conv.character_id, conv.id))
    assert len(calls) == 2


def test_auto_cold_settings_validation_and_persistence():
    client = TestClient(app)
    config = client.get('/api/system-memory/settings').json()
    assert config['auto_cold_enabled'] is False
    assert config['auto_cold_mode'] == 'interval'
    config.update(auto_cold_enabled=True, auto_cold_hours=3.5)
    assert client.put('/api/system-memory/settings', json=config).status_code == 200
    assert client.get('/api/system-memory/settings').json()['auto_cold_hours'] == 3.5
    config['auto_cold_kinds'] = ['summary', 'agreement']
    assert client.put('/api/system-memory/settings', json=config).status_code == 200
    assert client.get('/api/system-memory/settings').json()['auto_cold_kinds'] == ['summary', 'agreement']
    config['auto_cold_mode'] = 'immediate'
    assert client.put('/api/system-memory/settings', json=config).status_code == 200
    assert client.get('/api/system-memory/settings').json()['auto_cold_mode'] == 'immediate'
    config['auto_cold_mode'] = 'invalid'
    assert client.put('/api/system-memory/settings', json=config).status_code == 422
    config['auto_cold_mode'] = 'interval'
    config['auto_cold_kinds'] = ['book']
    assert client.put('/api/system-memory/settings', json=config).status_code == 422
    config['auto_cold_kinds'] = []
    assert client.put('/api/system-memory/settings', json=config).status_code == 200
    for hours in [0, -1, 8761]:
        config['auto_cold_hours'] = hours
        assert client.put('/api/system-memory/settings', json=config).status_code == 422


def test_auto_cold_only_selected_tables(monkeypatch):
    conv = store.create_conversation()
    apply(conv, {'summary': {'content': '总结'}, 'people': [{'name': '人物'}],
                'items': [{'name': '物品'}], 'agreements': [{'content': '约定'}]})
    config = memory.settings()
    assert set(config.auto_cold_kinds) == set(memory.schema.TABLES)
    config.auto_cold_enabled = True
    config.auto_cold_kinds = ['summary', 'item']
    store.save_setting('system_memory', config.model_dump(exclude={'prompt'}))
    vector = role_memory.settings()
    vector.vector.enabled = True
    role_memory.save_settings(vector.model_dump())
    monkeypatch.setattr(store, 'utcnow', lambda: END + timedelta(hours=4))
    calls = []
    async def embed(texts, config):
        calls.extend(texts)
        return [[1.0, 2.0]]
    monkeypatch.setattr(role_memory, 'get_embeddings', embed)
    asyncio.run(memory.auto_cold(conv.character_id, conv.id))
    assert {r['kind'] for r in memory.rows(conv.character_id, conv.id) if r['mode'] == 'cold'} == {'summary', 'item'}
    assert len(calls) == 2
    config.auto_cold_kinds = []
    store.save_setting('system_memory', config.model_dump(exclude={'prompt'}))
    asyncio.run(memory.auto_cold(conv.character_id, conv.id))
    assert len(calls) == 2


def test_immediate_save_and_new_batch_do_not_wait_for_age(monkeypatch):
    conv = store.create_conversation()
    apply(conv, {'summary': {'content': '已有总结'}})
    config = memory.settings()
    config.auto_cold_enabled = True
    config.auto_cold_mode = 'immediate'
    config.auto_cold_kinds = ['summary']
    config.auto_cold_hours = 8760
    vector = role_memory.settings()
    vector.vector.enabled = True
    role_memory.save_settings(vector.model_dump())
    async def embed(texts, config):
        return [[1.0, 2.0]]
    monkeypatch.setattr(role_memory, 'get_embeddings', embed)
    monkeypatch.setattr(store, 'utcnow', lambda: END)
    from app.memory.system_routes import save_settings
    async def run():
        await save_settings(config)
        await memory._cold_tasks[conv.character_id]
        assert memory.rows(conv.character_id, conv.id)[0]['mode'] == 'cold'
        seed(conv.id)
        fake_llm(monkeypatch, {'summary': {'content': '新总结'}})
        await memory.batch(conv.character_id, conv.id, START, END)
        assert all(r['mode'] == 'cold' for r in memory.rows(conv.character_id, conv.id))
    asyncio.run(run())


def test_cold_periodic_check_every_twenty_minutes(monkeypatch):
    conv = store.create_conversation()
    cfg = memory.settings()
    cfg.auto_cold_enabled = True
    store.save_setting('system_memory', cfg.model_dump(exclude={'prompt'}))
    vector = role_memory.settings()
    vector.vector.enabled = True
    role_memory.save_settings(vector.model_dump())
    tick = [0]
    monkeypatch.setattr(memory, 'monotonic', lambda: tick[0])
    calls = []
    async def cold(character_id, cid):
        calls.append(cid)
    monkeypatch.setattr(memory, 'auto_cold', cold)
    async def run():
        await memory.maintenance()
        await memory._cold_tasks[conv.character_id]
        tick[0] = 300
        await memory.maintenance()
        assert len(calls) == 1
        tick[0] = 1200
        await memory.maintenance()
        await memory._cold_tasks[conv.character_id]
        assert len(calls) == 2
    asyncio.run(run())

def seed(cid,request='seed',when=START):
    conv=store.get_conversation(cid)
    store.begin_turn(cid,request,'奶奶把钥匙放在抽屉',conv.timezone,'web','OFF')
    store.finish_turn(request,'已知事实',TokenUsage(),[],[],{})
    with store.database() as db:
        for m in store.get_conversation(cid).messages:
            m.timestamp=when.isoformat();m.local_datetime=when.astimezone(memory.ZoneInfo(conv.timezone)).isoformat()
            db.execute('UPDATE messages SET document=? WHERE id=?',(m.model_dump_json(),m.id))

def apply(conv,output):
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        memory.apply(db,conv.character_id,conv.id,'character',START.isoformat(),END.isoformat(),memory.Output.model_validate(output))

def fake_llm(monkeypatch,output):
    cfg=role_memory.settings();cfg.presets['diary'].llm.model='fake';role_memory.save_settings(cfg.model_dump())
    inputs=[]
    class Fake:
        last_usage=TokenUsage()
        def __init__(self,p): pass
        def set_generation_parameters(self,p): pass
        async def complete(self,messages):
            inputs.append(json.loads(messages[-1].content))
            return json.dumps(output,ensure_ascii=False)
    monkeypatch.setattr(role_memory,'OpenAICompatibleLlm',Fake)
    return inputs

def test_append_history_refresh_impression_item_and_transaction():
    conv=store.create_conversation()
    apply(conv,{'people':[{'name':'奶奶','relationship':'亲人','history':'赠送钥匙','impression':'用户非常喜欢她'}],'items':[{'name':'钥匙','description':'铜钥匙','location':'抽屉'}]})
    apply(conv,{'people':[{'name':'奶奶','history':'一起吃饭','impression':'用户觉得她特别好'}],'items':[{'name':'钥匙','location':'书包'}]})
    rows=memory.rows('default',conv.id)
    person=next(r for r in rows if r['kind']=='person');item=next(r for r in rows if r['kind']=='item')
    assert person['history']=='赠送钥匙\n一起吃饭' and person['impression']=='用户觉得她特别好'
    assert item['description']=='铜钥匙' and item['location']=='书包'
    with pytest.raises(ValueError):
        apply(conv,{'summary':{'content':'不应部分保存'},'people':[{'name':'陌生人','id':'invalid'}]})
    assert len(memory.rows('default',conv.id))==2
    with pytest.raises(ValueError):apply(conv,{'items':[{'name':'钥匙','history':'串表字段'}]})

def test_raw_role_history_display_time_boundaries_and_branch_dedup():
    a=store.create_conversation();b=store.create_conversation()
    seed(a.id,'a');seed(b.id,'b',END)
    branch=store.branch_conversation(a.id,store.get_conversation(a.id).messages[-1].id)['conversation']
    assert len(memory.raw_messages('default',a.id,START,END))==2
    assert len(memory.raw_messages('default',branch.id,START,END,'conversation'))==2
    with store.database() as db:
        m=store.get_conversation(b.id).messages[0]
        m.timestamp=(START+timedelta(minutes=30)).isoformat()
        db.execute('UPDATE messages SET document=? WHERE id=?',(m.model_dump_json(),m.id))
    assert len(memory.raw_messages('default',a.id,START,END))==3

def test_role_default_and_other_character_isolation():
    a=store.create_conversation();b=store.create_conversation()
    store.save_character(Character(id='other',name='其他角色'))
    c=store.create_conversation('other')
    assert role_memory.RecordInput(content='x').scope=='character'
    apply(a,{'summary':{'content':'用户讨论钥匙','tag':'钥匙'}})
    assert len(memory.rows('default',b.id))==1 and not memory.rows('other',c.id)
    assert memory.hot_context('default',b.id)
    with pytest.raises(ValueError):memory.rows('other',a.id)

def test_batch_repeat_and_invalid_output_rollback(monkeypatch):
    conv=store.create_conversation();seed(conv.id)
    inputs=fake_llm(monkeypatch,{'summary':{'content':'用户与角色讨论奶奶和钥匙','tag':'亲人'}})
    assert asyncio.run(memory.batch('default',conv.id,START,END))=='done'
    assert asyncio.run(memory.batch('default',conv.id,START,END))=='already_processed'
    assert len(inputs)==1 and len(memory.rows('default',conv.id))==1
    assert len(inputs[0]['messages'])==2
    fake_llm(monkeypatch,{'summary':{'content':'禁止部分保存'},'people':[{'id':'wrong','name':'奶奶'}]})
    with pytest.raises(ValueError):asyncio.run(memory.batch('default',conv.id,START,END+timedelta(minutes=1)))
    assert len(memory.rows('default',conv.id))==1
    with store.database() as db: assert db.execute("SELECT COUNT(*) FROM system_memory_batches WHERE status='error'").fetchone()[0]==1

def test_scan_serial_delay_cancel_and_failure(monkeypatch):
    conv=store.create_conversation();calls=[]
    async def batch(*args): calls.append((args[2],args[3]));return 'done'
    monkeypatch.setattr(memory,'batch',batch)
    async def run():
        memory.start_scan('default',conv.id,START,START+timedelta(minutes=125),memory.Settings(delay_seconds=0))
        await memory._tasks['default']
        assert memory._progress['default']['completed']==3
        assert calls[0][1]==calls[1][0] and calls[-1][1]==START+timedelta(minutes=125)
        event=asyncio.Event()
        async def blocked(*args): await event.wait()
        monkeypatch.setattr(memory,'batch',blocked)
        memory.start_scan('default',conv.id,START,END,memory.Settings())
        await asyncio.sleep(0)
        with pytest.raises(ValueError):memory.start_scan('default',conv.id,START,END,memory.Settings())
        await memory.shutdown()
        assert memory._progress['default']['status']=='cancelled'
    asyncio.run(run())

def test_cold_embedding_failure_and_disabled_vector_fallback(monkeypatch):
    conv=store.create_conversation();apply(conv,{'summary':{'content':'用户讨论钥匙'}})
    row=memory.rows('default',conv.id)[0]
    cfg=role_memory.settings();cfg.vector.enabled=True;role_memory.save_settings(cfg.model_dump())
    async def fail(*args):raise ValueError('offline')
    monkeypatch.setattr(role_memory,'get_embeddings',fail)
    with pytest.raises(ValueError):asyncio.run(memory.change_mode('default',conv.id,row['id'],'cold'))
    assert memory.rows('default',conv.id)[0]['mode']=='hot'
    async def embed(*args):return [[1,0]]
    monkeypatch.setattr(role_memory,'get_embeddings',embed)
    asyncio.run(memory.change_mode('default',conv.id,row['id'],'cold'))
    assert not memory.hot_context('default',conv.id)
    async def retrieve(q,state):return [{'chunk_id':c.id} for lib in state.libraries for c in lib.chunks]
    monkeypatch.setattr(role_memory,'retrieve_vector_memories',retrieve)
    assert asyncio.run(role_memory.recall('default',conv.id,'钥匙'))[0]['chunk_id']==row['id']
    cfg.vector.enabled=False;role_memory.save_settings(cfg.model_dump())
    assert memory.hot_context('default',conv.id)

def test_one_time_migration_deletes_only_old_agreements_no_backup():
    conv=store.create_conversation()
    with store.database() as db:
        role_memory.initialize(db)
        db.execute("DELETE FROM settings WHERE key='role_memory_character_v2'")
        for kind,rid in [('agreement','old-agreement'),('milestone','old-event')]:
            role_memory.memory_schema.write(db,dict(id=rid,kind='event',character_id='default',conversation_id=conv.id,scope='conversation',content='旧记录',tags=['旧'],record_type=kind,created_at='',updated_at='',sources=['source']))
        role_memory.initialize(db)
        assert not db.execute("SELECT 1 FROM shared_records WHERE record_type='agreement'").fetchone()
        assert db.execute("SELECT scope FROM shared_records WHERE memory_id='old-event'").fetchone()[0]=='character'
        assert not db.execute("SELECT 1 FROM memory_sources WHERE memory_id='old-agreement'").fetchone()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='deleted_memories'").fetchone()
        role_memory.memory_schema.write(db,dict(id='new',kind='event',character_id='default',conversation_id=conv.id,content='新约定',tags=['新'],record_type='agreement',created_at='',updated_at=''))
        role_memory.initialize(db)
        assert db.execute("SELECT 1 FROM shared_records WHERE memory_id='new'").fetchone()

def test_api_old_event_disabled_edit_and_scope_validation():
    conv=store.create_conversation()
    with TestClient(app) as client:
        assert client.post('/api/role-memory/default/event',json={'conversation_id':conv.id,'content':'旧写入','tags':['x']}).status_code==422
        assert client.put('/api/system-memory/settings',json={'scope':'invalid'}).status_code==422
        assert client.post('/api/system-memory/default/scan',json={'conversation_id':conv.id,'start':'2026-10-02','end':'2026-10-01'}).status_code==422
        apply(conv,{'items':[{'name':'钥匙','location':'抽屉'}]})
        row=memory.rows('default',conv.id)[0]
        assert client.put(f'/api/system-memory/default/{row["id"]}',params={'conversation_id':conv.id},json={'location':'书包'}).status_code==200
        assert memory.rows('default',conv.id)[0]['location']=='书包'
        assert client.get('/api/system-memory/default',params={'conversation_id':conv.id}).status_code==200

def test_diary_role_range_ignores_runtime_filter_and_one_daily_record(monkeypatch):
    a=store.create_conversation();b=store.create_conversation()
    seed(a.id,'diary-a');seed(b.id,'diary-b',START+timedelta(minutes=10))
    from app.settings.store import save_runtime_settings
    from app.models import RuntimeSettings
    save_runtime_settings(RuntimeSettings(history_mode='count',history_depth=0))
    inputs=fake_llm(monkeypatch,{'title':'亲人的关心','content':'今天我陪他聊了奶奶。','tags':[]})
    result=asyncio.run(role_memory.generate('diary',a.id,'2026-10-01'))
    assert result['status']=='done' and len(inputs[0]['messages'])==4
    asyncio.run(role_memory.generate('diary',b.id,'2026-10-01'))
    assert len([r for r in role_memory.all_records('default') if r['kind']=='diary'])==1

def test_auto_failure_keeps_initial_time_cursor_and_empty_windows_no_llm(monkeypatch):
    conv=store.create_conversation()
    config=memory.Settings(enabled=True)
    store.save_setting('system_memory',config.model_dump())
    async def run():
        await memory.maintenance()
        await memory._tasks['default']
        first=store.get_setting('system_memory_auto_starts',{})
        with store.database() as db:
            assert db.execute("SELECT status FROM system_memory_batches").fetchone()[0]=='empty'
        await memory.maintenance()
        assert first==store.get_setting('system_memory_auto_starts',{})
    asyncio.run(run())
