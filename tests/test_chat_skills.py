import asyncio
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import chat_skills as skills, role_memory as memory, companion_store as store
from app.companion_core import core
from app.main import app
from app.models import TokenUsage

class Fake:
    def __init__(self,outputs):
        self.outputs=iter(outputs);self.last_usage=TokenUsage(input_tokens=10,output_tokens=5);self.profile=SimpleNamespace(api_key='fake');self.inputs=[]
    def set_generation_parameters(self,p):pass
    async def stream_complete(self,messages):
        self.inputs.append([m.model_dump() for m in messages])
        raw=next(self.outputs)
        for c in raw:yield c

def test_prefix_filter_and_malformed_write():
    raw='你好<app_call name="append_diary_entry">{"content":"隐藏","tags":[]}</app_call>'
    shown=''
    for i in range(1,len(raw)+1):
        value=skills.visible(raw[:i]);assert value.startswith(shown);shown=value
        assert '<app' not in value and '隐藏' not in value
    assert shown=='你好'
    assert skills.write_actions('正文<app_call name="append_diary_entry">bad</app_call>')[0]==[]
    assert skills.write_actions('正文<app_call name="save_shared_event">{"content":"x","tags":[" "]}</app_call>')[0]==[]

def test_read_scope_and_catalog():
    a=store.create_conversation();b=store.create_conversation()
    r=memory.put('diary','default',a.id,{'content':'旅行私密记录','tags':['旅行']})
    assert not skills.perform_read(b.id,'search_memory',{'query':'旅行'})['records']
    with pytest.raises(ValueError):skills.perform_read(b.id,'read_memory',{'memory_id':r['id']})
    with pytest.raises(ValueError):skills.read_skill('../../config')
    with TestClient(app) as c:
        assert len(c.get('/api/skills').json()['skills'])==3
        assert '即时日记' in c.get('/api/skills/diary-write').json()['content']

def test_chat_reads_then_writes_atomically_and_replay(monkeypatch):
    fake=Fake(['<app_call name="read_skill">{"name":"diary-write"}</app_call>', '我也想记住。<app_call name="append_diary_entry">{"content":"我们聊了旅行，还没定日子。","tags":["旅行"]}</app_call>'])
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation();job=core.submit(conv.id,'skill-turn','聊旅行',conv.timezone,search_mode='OFF');await job.task
        assert job.events[-1]['type']=='complete',job.events[-1]
        assert ''.join(e['text'] for e in job.events if e['type']=='delta')=='我也想记住。'
        assert store.get_conversation(conv.id).messages[-1].content=='我也想记住。'
        records=memory.all_records('default');assert len(records)==1 and records[0]['entry_type']=='chat_entry'
        assert records[0]['sources'] and records[0]['scope']=='conversation'
        assert job.events[-1]['skill_results'][0]['status']=='saved'
        assert len(job.events[-1]['extra_usage'])==1
        assert 'diary-write' in json.dumps(fake.inputs[-1],ensure_ascii=False)
        core.submit(conv.id,'skill-turn','聊旅行',conv.timezone,search_mode='OFF')
        assert len(memory.all_records('default'))==1
    asyncio.run(scenario())

def test_invalid_write_preserves_chat_and_no_partial_save(monkeypatch):
    fake=Fake(['正常回复<app_call name="append_diary_entry">{"content":"日记","tags":[]}</app_call><app_call name="save_shared_event">{"content":"事件","tags":[]}</app_call>'])
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation();job=core.submit(conv.id,'bad-write','你好',conv.timezone,search_mode='OFF');await job.task
        assert job.events[-1]['type']=='complete'
        assert store.get_conversation(conv.id).messages[-1].content=='正常回复'
        assert not memory.all_records('default')
    asyncio.run(scenario())

def test_regenerate_skips_new_diary(monkeypatch):
    fake=Fake(['第一回复','第二回复<app_call name="append_diary_entry">{"content":"不应写入","tags":[]}</app_call>'])
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation();job=core.submit(conv.id,'original','你好',conv.timezone,search_mode='OFF');await job.task
        mid=store.get_conversation(conv.id).messages[-1].id
        job=core.submit(conv.id,'regen','',conv.timezone,search_mode='OFF',regenerate_mid=mid);await job.task
        assert job.events[-1]['type']=='complete'
        assert not memory.all_records('default') and job.events[-1]['skill_results'][0]['status']=='skipped'
    asyncio.run(scenario())

def test_instant_range_and_daily_independent(monkeypatch):
    conv=store.create_conversation()
    for i in range(3):
        store.begin_turn(conv.id,f'source-{i}',f'消息{i}',conv.timezone,'web','OFF');store.finish_turn(f'source-{i}',f'回答{i}',TokenUsage(),[],[],{})
    cfg=memory.settings();cfg.presets['diary'].llm.model='independent';memory.save_settings(cfg.model_dump())
    inputs=[]
    class Diary:
        last_usage=TokenUsage()
        def __init__(self,p):assert p.model=='independent'
        def set_generation_parameters(self,p):pass
        async def complete(self,m):inputs.append(json.loads(m[-1].content));return '{"content":"旅行","tags":["旅行"]}'
    monkeypatch.setattr(memory,'OpenAICompatibleLlm',Diary)
    date=store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    asyncio.run(memory.generate('diary',conv.id,date,entry_type='chat_entry',start_time='00:00',end_time='24:00'))
    asyncio.run(memory.generate('diary',conv.id,date))
    assert len(inputs[0]['messages'])==6 and len(inputs[1]['messages'])==6
    assert {r['entry_type'] for r in memory.all_records('default')}=={'chat_entry','daily_summary'}
    assert len(store.get_conversation(conv.id).messages)==6


def test_no_implicit_main_model_and_custom_prompt_preserved():
    preset=memory.TaskPreset(prompt='custom',requirements='custom',follow_conversation=True)
    assert not memory.task_llm(preset).model
    cfg=memory.settings();cfg.presets['diary'].prompt='我的自定义提示词';memory.save_settings(cfg.model_dump())
    memory.upgrade_prompt_defaults()
    assert memory.settings().presets['diary'].prompt=='我的自定义提示词'

def test_read_loop_limit_and_cancel_do_not_write(monkeypatch):
    fake=Fake(['<app_call name="read_skill">{"name":"diary-write"}</app_call>']*4)
    monkeypatch.setattr(core,'llm_for',lambda *a:fake)
    async def scenario():
        conv=store.create_conversation();job=core.submit(conv.id,'loop','你好',conv.timezone,search_mode='OFF');await job.task
        assert job.events[-1]['type']=='error' and len(fake.inputs)==4
        assert not memory.all_records('default')
        class Slow(Fake):
            async def stream_complete(self,m):
                yield '你好<app_call name="append_diary_entry">{"content":"不能保存","tags":[]}</app_call>'
                await asyncio.sleep(10)
        slow=Slow([]);monkeypatch.setattr(core,'llm_for',lambda *a:slow)
        job=core.submit(conv.id,'cancel','你好',conv.timezone,search_mode='OFF');await asyncio.sleep(.05)
        await core.cancel(conv.id,'cancel')
        assert not memory.all_records('default')
    asyncio.run(scenario())


def test_unknown_event_time_and_daily_refresh(monkeypatch):
    conv=store.create_conversation()
    event=memory.put('event','default',conv.id,{'content':'约好以后出游，时间未知','tags':['出游']})
    assert event['occurred_at'] is None
    asyncio.run(memory.maintenance())
    cfg=memory.settings();cfg.presets['diary'].llm.model='daily';memory.save_settings(cfg.model_dump())
    class Diary:
        last_usage=TokenUsage()
        def __init__(self,p):pass
        def set_generation_parameters(self,p):pass
        async def complete(self,m):return '{"content":"每日总结","tags":[]}'
    monkeypatch.setattr(memory,'OpenAICompatibleLlm',Diary)
    date=store.utcnow().astimezone(memory.ZoneInfo(conv.timezone)).date().isoformat()
    for i in range(2):
        store.begin_turn(conv.id,f'daily-{i}','新聊天',conv.timezone,'web','OFF');store.finish_turn(f'daily-{i}','新回复',TokenUsage(),[],[],{})
        assert asyncio.run(memory.generate('diary',conv.id,date))['status']=='done'
    diaries=[r for r in memory.all_records('default') if r['kind']=='diary']
    assert len(diaries)==1 and len(diaries[0]['sources'])==4
