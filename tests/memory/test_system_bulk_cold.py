import asyncio
from fastapi.testclient import TestClient
from app.main import app
from app.chat import store
from app.memory import role,system
from tests.memory.test_system_memory import apply,START,END


def test_bulk_cold_multiselect_incremental_and_time_boundaries(monkeypatch):
    conv=store.create_conversation()
    apply(conv,{'summary':{'content':'聊天总结'},'people':[{'name':'奶奶'}],'items':[{'name':'钥匙'}],'agreements':[{'content':'周末联系'}]})
    cfg=role.settings();cfg.vector.enabled=True;role.save_settings(cfg.model_dump())
    calls=[]
    async def embed(texts,config):calls.extend(texts);return [[1,0] for _ in texts]
    monkeypatch.setattr(role,'get_embeddings',embed)
    person=next(r for r in system.rows('default',conv.id) if r['kind']=='person')
    asyncio.run(system.change_mode('default',conv.id,person['id'],'cold'));calls.clear()
    value={'conversation_id':conv.id,'start':START.isoformat(),'end':END.isoformat(),'kinds':['person','item']}
    with TestClient(app) as client:
        preview=client.post('/api/system-memory/default/vector-selection',json=value)
        assert preview.json()=={'selected':2,'pending':1,'already_cold':1}
        result=client.post('/api/system-memory/default/bulk-cold',json=value).json()
        assert result=={'selected':2,'converted':1,'reindexed':0,'skipped':1,'failed':0,'errors':[]}
        assert len(calls)==1
        assert client.post('/api/system-memory/default/bulk-cold',json=value).json()['skipped']==2
        assert len(calls)==1
        cfg.vector.model='new-model';role.save_settings(cfg.model_dump())
        assert client.post('/api/system-memory/default/bulk-cold',json=value).json()['reindexed']==2
        assert len(calls)==3
        assert client.post('/api/system-memory/default/vector-selection',json=value|{'kinds':[]}).status_code==422
    assert all(r['mode']=='hot' for r in system.rows('default',conv.id) if r['kind'] in ('summary','agreement'))
    assert not system.vector_selection('default',conv.id,END.isoformat(),(END+system.timedelta(hours=1)).isoformat(),['person','item'])
    # 相同时刻的不同显示时区仍选中同一记录。
    assert len(system.vector_selection('default',conv.id,'2026-10-01T08:00:00+08:00','2026-10-01T09:00:00+08:00',['person','item']))==2


def test_bulk_failure_preserves_rows_and_scope(monkeypatch):
    conv=store.create_conversation();apply(conv,{'summary':{'content':'失败测试'},'items':[{'name':'钥匙'}]})
    cfg=role.settings();cfg.vector.enabled=True;role.save_settings(cfg.model_dump())
    async def embed(texts,config):
        if '失败测试' in texts[0]:raise ValueError('服务不可用')
        return [[1,0]]
    monkeypatch.setattr(role,'get_embeddings',embed)
    result=asyncio.run(system.bulk_cold('default',conv.id,START.isoformat(),END.isoformat(),['summary','item']))
    assert result['failed']==1 and result['converted']==1
    rows=system.rows('default',conv.id)
    assert next(r for r in rows if r['kind']=='summary')['mode']=='hot'
    assert next(r for r in rows if r['kind']=='item')['mode']=='cold'
    with TestClient(app) as client:
        assert client.post('/api/system-memory/other/bulk-cold',json={'conversation_id':conv.id,'start':START.isoformat(),'end':END.isoformat(),'kinds':['summary']}).status_code==422
