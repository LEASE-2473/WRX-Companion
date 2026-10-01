import asyncio
import json
from fastapi.testclient import TestClient
from app import companion_store as store, role_memory as memory, chat_skills
from app.main import app
from app.models import TokenUsage


def test_title_generation_and_edit(monkeypatch):
    conv=store.create_conversation()
    store.begin_turn(conv.id,'title-test','造房子',conv.timezone,'web','OFF')
    store.finish_turn('title-test','陪你',TokenUsage(),[],[],{})
    cfg=memory.settings();cfg.presets['diary'].llm.model='fake';memory.save_settings(cfg.model_dump())
    class Fake:
        last_usage=TokenUsage()
        def __init__(self,p):pass
        def set_generation_parameters(self,p):pass
        async def complete(self,messages):
            assert 'title' in messages[0].content and '不逐条复述' in messages[0].content
            return '{"title":"新家的第一夜","content":"今天住进新家。","tags":["新家"]}'
    monkeypatch.setattr(memory,'OpenAICompatibleLlm',Fake)
    date=store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    asyncio.run(memory.generate('diary',conv.id,date))
    r=memory.all_records('default')[0];assert r['title']=='新家的第一夜'
    with TestClient(app) as client:
        result=client.put(f"/api/role-memory/default/diary/{r['id']}",json=r|{'title':'改过的标题','content':'改过正文','tags':['新标签']})
        assert result.status_code==200
    r=memory.all_records('default')[0]
    assert (r['title'],r['content'],r['tags'])==('改过的标题','改过正文',['新标签'])
    assert r['entry_type']=='daily_summary' and r['sources']


def test_delete_cleans_indexes_hooks_and_retains_backup():
    conv=store.create_conversation()
    r=memory.put('diary','default',conv.id,{'title':'标题','content':'正文','tags':['主题'],'date':'2026-10-01'})
    with store.database() as db:
        db.execute('INSERT INTO diary_hooks VALUES (?,?,?,?,?)',(conv.id,'default','2026-10-01','conversation','["未结"]'))
        db.execute('INSERT INTO memory_jobs VALUES (?,?,?,?,?,?)',('job','default',conv.id,'done',store.utcnow().isoformat(),json.dumps({'record_ids':[r['id']]})))
    with TestClient(app) as client:
        assert client.delete(f"/api/role-memory/other/diary/{r['id']}").status_code==404
        assert client.delete(f"/api/role-memory/default/diary/{r['id']}").status_code==200
        assert client.delete(f"/api/role-memory/default/diary/{r['id']}").status_code==404
    assert not memory.all_records('default') and not memory.hooks_context('default',conv.id)
    with store.database() as db:
        for table in ['diary_event_tags','memory_sources','memory_vectors']:
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0
        saved=json.loads(db.execute('SELECT document FROM deleted_memories').fetchone()[0])
        assert saved['title']=='标题' and saved['tags']==['主题']
        assert db.execute('SELECT status FROM memory_jobs').fetchone()[0]=='deleted'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_skill_title_and_prompt_upgrade_preserve_custom():
    actions,error=chat_skills.write_actions('<app_call name="append_diary_entry">{"title":"主题","content":"正文","tags":[]}</app_call>')
    assert not error and actions[0]['title']=='主题'
    cfg=memory.settings();cfg.presets['diary'].prompt='自定义日记风格';memory.save_settings(cfg.model_dump())
    memory.upgrade_prompt_defaults()
    assert memory.settings().presets['diary'].prompt=='自定义日记风格'
