import asyncio
import json
import httpx
import pytest
from app import role_memory as memory, companion_store as store
from app.models import TokenUsage
from app.providers import ProviderError


def test_recursive_split_and_merge_preserves_material():
    calls = []
    class Fake:
        last_usage = TokenUsage(input_tokens=10, output_tokens=2)
        async def complete(self, messages):
            data = json.loads(messages[-1].content); calls.append(data)
            if len(calls) == 1: raise ProviderError('context_length_exceeded')
            return json.dumps({'content':'短总结', 'tags':[], 'unresolved_hooks':[]})
    items = [{'time':str(i),'role':'user','content':str(i)} for i in range(4)]
    audit=[]
    result=asyncio.run(memory.summarize_diary(Fake(),'写日记',{'messages':items},audit,lambda:None))
    assert result['content']=='短总结' and len(calls)==4
    assert calls[1]['messages']+calls[2]['messages']==items
    assert [m['role'] for m in calls[3]['messages']]==['summary','summary']
    assert [a['status'] for a in audit]==['context_overflow','done','done','done']


def test_single_long_message_split_and_network_error_not_split():
    class Fake:
        last_usage=TokenUsage()
        calls=0
        async def complete(self,messages):
            self.calls+=1
            if self.calls==1: raise ProviderError('maximum context length exceeded')
            return '{"content":"短","tags":[]}'
    fake=Fake()
    asyncio.run(memory.summarize_diary(fake,'写日记',{'messages':[{'time':'t','role':'user','content':'abcdef'}]},[],lambda:None))
    assert fake.calls==4
    class Offline(Fake):
        async def complete(self,messages):
            self.calls+=1
            raise ProviderError('网络连接失败')
    fake=Offline()
    with pytest.raises(ProviderError): asyncio.run(memory.summarize_diary(fake,'写日记',{'messages':[{'time':'t','role':'user','content':'abcdef'}]},[],lambda:None))
    assert fake.calls==1


def test_nonshrinking_merge_stops_without_infinite_calls():
    class Fake:
        last_usage=TokenUsage()
        calls=0
        async def complete(self,messages):
            self.calls+=1
            if len(json.loads(messages[-1].content)['messages'])>1: raise ProviderError('context_length_exceeded')
            return json.dumps({'content':'x'*500,'tags':[]})
    fake=Fake()
    with pytest.raises(ValueError,match='未缩短'):
        asyncio.run(memory.summarize_diary(fake,'写日记',{'messages':[{'time':'t','role':'user','content':'a'},{'time':'t','role':'user','content':'b'}]},[],lambda:None))
    assert fake.calls==6


def test_time_range_filter_no_daily_cap_and_auto_same_input(monkeypatch):
    conv=store.create_conversation()
    for i in range(3):
        store.begin_turn(conv.id,f'range-{i}',f'对话{i}![图片](data:image/png;base64,abc)',conv.timezone,'web','OFF')
        store.finish_turn(f'range-{i}',f'回复{i}<emotion_update>隐私情绪</emotion_update>',TokenUsage(),[],[],{})
    with store.database() as db:
        for i,m in enumerate(store.get_conversation(conv.id).messages):
            hour=[0,0,5,5,6,6][i]
            timestamp=f'2026-09-23T{hour:02}:00:00+08:00'
            m=m.model_copy(update={'timestamp':timestamp,'local_datetime':timestamp})
            db.execute('UPDATE messages SET document=? WHERE id=?',(m.model_dump_json(),m.id))
    cfg=memory.settings();cfg.presets['diary'].llm.model='fake';cfg.presets['diary'].history_limit=1
    cfg.presets['diary'].include_notes=True;cfg.presets['diary'].include_events=True;memory.save_settings(cfg.model_dump())
    inputs=[]
    class Fake:
        last_usage=TokenUsage(input_tokens=1,output_tokens=1)
        def __init__(self,p):pass
        def set_generation_parameters(self,p):pass
        async def complete(self,messages):
            inputs.append(json.loads(messages[-1].content));return '{"content":"日记","tags":[]}'
    monkeypatch.setattr(memory,'OpenAICompatibleLlm',Fake)
    asyncio.run(memory.generate('diary',conv.id,'2026-09-23',entry_type='chat_entry',start_time='00:00',end_time='06:00'))
    asyncio.run(memory.generate('diary',conv.id,'2026-09-23'))
    asyncio.run(memory.generate('diary',conv.id,'2026-09-23',automatic=True))
    assert [len(d['messages']) for d in inputs]==[4,6,6]
    assert inputs[1]==inputs[2]
    for data in inputs:
        assert 'activity_notes' not in data and 'existing_events' not in data
        assert 'data:image' not in json.dumps(data) and '隐私情绪' not in json.dumps(data,ensure_ascii=False)
        assert all(set(m)=={'time','role','content'} for m in data['messages'])
    assert len(memory.all_records('default'))==2


def test_window_validation_and_provider_error_classification():
    start,end=memory.time_window('2026-09-23','Asia/Shanghai','00:00','24:00')
    assert (end-start).total_seconds()==86400 and end.day==24
    for a,b in [('06:00','00:00'),('00:00','00:00'),('24:00','24:00'),('00:00','25:00')]:
        with pytest.raises(ValueError):memory.time_window('2026-09-23','Asia/Shanghai',a,b)
    response=httpx.Response(400,text='{"error":{"code":"context_length_exceeded"}}',request=httpx.Request('POST','https://example.test'))
    assert memory.context_overflow(httpx.HTTPStatusError('bad',request=response.request,response=response))
    response=httpx.Response(429,text='too many tokens',request=response.request)
    assert not memory.context_overflow(httpx.HTTPStatusError('bad',request=response.request,response=response))


def test_streamed_http_error_body_is_available_for_splitting(monkeypatch):
    from app.providers import OpenAICompatibleLlm
    from app.models import LlmProviderProfile, ChatMessage
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(400,json={'error':{'code':'context_length_exceeded'}}))) as client:
            monkeypatch.setattr(OpenAICompatibleLlm,'client',lambda self:client)
            llm=OpenAICompatibleLlm(LlmProviderProfile(id='test',name='test',api_key='fake',model='fake'))
            with pytest.raises(httpx.HTTPStatusError) as caught:
                await llm.complete([ChatMessage(role='user',content='text')])
            assert memory.context_overflow(caught.value)
    asyncio.run(scenario())
