import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import companion_store as store, role_memory as memory
from app.history_selection import select_history
from app.models import RuntimeSettings, TokenUsage
from app.runtime_settings_store import save_runtime_settings
from app.companion_core import core
from app.main import app


def test_time_selection_boundary_timezone_missing_and_no_count_cap():
    messages=[SimpleNamespace(id='old',timestamp='2026-10-01T15:59:00+00:00'),
              SimpleNamespace(id='start',timestamp='2026-10-02T00:00:00+08:00'),
              SimpleNamespace(id='later',timestamp='2026-10-01T17:00:00+00:00'),
              SimpleNamespace(id='unknown',timestamp=''),SimpleNamespace(id='broken',timestamp='invalid')]
    cfg=RuntimeSettings(history_mode='since',history_since='2026-10-02T00:00:00+08:00',history_depth=0)
    assert [m.id for m in select_history(messages,cfg)]==['start','later']
    assert not select_history(messages,RuntimeSettings(history_depth=0))


def test_preview_statistics_and_actual_prompt_agree():
    conv=store.create_conversation()
    for i in range(2):
        store.begin_turn(conv.id,f'time-{i}',f'历史{i}',conv.timezone,'web','OFF')
        store.finish_turn(f'time-{i}',f'回复{i}',TokenUsage(),[],[],{})
    with store.database() as db:
        for i,m in enumerate(store.get_conversation(conv.id).messages):
            t=f'2026-10-02T{(0 if i<2 else 6):02}:00:00+08:00'
            m=m.model_copy(update={'timestamp':t,'local_datetime':t})
            db.execute('UPDATE messages SET document=? WHERE id=?',(m.model_dump_json(),m.id))
    with TestClient(app) as client:
        preview=client.post('/api/role-memory/history-preview',json={'conversation_id':conv.id,'history_mode':'since','history_since':'2026-10-02T06:00','history_depth':1})
        assert preview.status_code==200
        data=preview.json();assert data['count']==2 and data['estimated_tokens']>0 and data['history_since'].endswith('+08:00')
        assert client.post('/api/role-memory/history-preview',json={'conversation_id':conv.id,'history_since':'invalid'}).status_code==422
    save_runtime_settings(RuntimeSettings(history_mode='since',history_since=data['history_since'],history_depth=1))
    history=memory.history_context(conv.id)
    assert len(history)==2 and memory.estimate_prompt_tokens(history)==data['estimated_tokens']
    assert memory.hot_context('default',conv.id)[2]['history_count']==2
    compiled,_=core.context(store.get_conversation(conv.id),store.get_character('default'),'新问题','web')
    assert compiled.trace['history']['used_layers']==2
    assert compiled.trace['history']['selection_mode']=='since'
    text='\n'.join(m.content for m in compiled.messages)
    assert '历史1' in text and '历史0' not in text
    assert len(compiled.trace['history']['selected_ids'])==2


def test_runtime_time_validation():
    with TestClient(app) as client:
        assert client.put('/api/runtime-settings',json={'history_mode':'since','history_since':'2026-10-02T00:00'}).status_code==422
        assert client.put('/api/runtime-settings',json={'history_mode':'since','history_since':'2026-10-02T00:00:00+08:00'}).status_code==200
