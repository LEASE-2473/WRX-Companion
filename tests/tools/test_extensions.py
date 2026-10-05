import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.extensions import manager, runtime
from app.skills import runtime as skills, configuration
from app.chat import store
from app.chat.core import core
from app.main import app
from app.models import TokenUsage, LlmProviderProfile
from app.providers.client import OpenAICompatibleLlm


def install(eid='demo', port=8123, tag='demo_call'):
    directory = manager.DIRECTORY/eid; directory.mkdir(parents=True,exist_ok=True)
    manifest = {'id':eid,'name':eid,'internal_port':port,'entry_cmd':['{python}','main.py'],
        'skill_path':'SKILL.md','invocation':{'tag':tag,'read_only_actions':['state']}}
    (directory/'extension.json').write_text(json.dumps(manifest),encoding='utf-8')
    (directory/'main.py').write_text('',encoding='utf-8')
    (directory/'SKILL.md').write_text('说明：正文后附加 <'+tag+'>{"action":"stop","args":{}}</'+tag+'>',encoding='utf-8')
    if not manager.scan()[eid]['error']: manager.set_enabled(eid,True)
    return directory


def test_scan_conflicts_and_invalid_files_do_not_start():
    install(); install('other',8123,'other_call')
    assert 'other' in manager.scan()['demo']['error']
    assert not manager._instances
    p = manager.DIRECTORY/'other/extension.json'
    data=json.loads(p.read_text());data['internal_port']=2473;p.write_text(json.dumps(data))
    assert '主项目' in manager.scan()['other']['error']
    data['internal_port']=8124;data['skill_path']='../escape.md';p.write_text(json.dumps(data))
    assert manager.scan()['other']['error']


def test_fragmented_xml_hidden_and_invalid_blocks_never_parse():
    install()
    raw='正文<demo_call>{"action":"stop","args":{}}</demo_call>'
    for n in range(len(raw)+1):
        assert '<demo' not in skills.visible(raw[:n])
    assert skills.visible(raw)=='正文'
    assert runtime.parse(raw)==[('demo',{'action':'stop','args':{}})]
    for bad in ['<demo_call>{}</demo_call>','<demo_call>{','<demo_call>{"action":"stop","args":{}}</demo_call>'*2]:
        with pytest.raises(ValueError):runtime.parse(bad)


@pytest.mark.parametrize('guarded', [True,False])
def test_xml_chat_one_request_no_native_tools_and_diary(monkeypatch,guarded):
    install()
    executed=[]
    monkeypatch.setattr(manager,'start',lambda eid:None)
    monkeypatch.setattr(manager,'request',lambda eid,path,data=None,**kw:executed.append(data) or {'accepted':True})
    class Fake:
        last_usage=TokenUsage()
        calls=0
        def set_generation_parameters(self,value):pass
        async def stream_complete(self,messages):
            self.calls+=1
            assert any('[已启用扩展 demo]' in m.content for m in messages)
            yield '我在。<demo_call>{"action":"stop","args":{}}</demo_call><app_call name="append_diary_entry">{"title":"此刻","content":"聊了一会","tags":[]}</app_call>'
    fake=Fake();monkeypatch.setattr(core,'llm_for',lambda *args:fake)
    async def run():
        conv=store.create_conversation()
        if guarded:
            store.begin_turn(conv.id,'original','你好',conv.timezone,'web','OFF')
            store.finish_turn('original','旧回复',TokenUsage(),[],[],{})
            mid=store.get_conversation(conv.id).messages[-1].id
            job=core.submit(conv.id,'new','你好',conv.timezone,search_mode='OFF',regenerate_mid=mid)
        else:job=core.submit(conv.id,'new','你好',conv.timezone,search_mode='OFF')
        await job.task
        assert job.events[-1]['type']=='complete',job.events[-1]
        assert fake.calls==1
        assert len(executed)==(0 if guarded else 1)
        assert store.get_conversation(conv.id).messages[-1].content=='我在。'
        from app.memory import role
        assert len(role.all_records('default'))==(0 if guarded else 1)
    asyncio.run(run())


def test_provider_only_text_fields_even_if_native_attributes_set():
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"正文<demo_call>{}</demo_call>"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async def run():
        llm=OpenAICompatibleLlm(LlmProviderProfile(id='x',name='x',model='fake',api_key='fake'))
        llm.function_tools=[{'type':'function'}]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            llm.client=lambda:client
            assert '正文' in ''.join([p async for p in llm.stream_complete([])])
        assert len(requests)==1
        assert not {'tools','tool_choice','parallel_tool_calls'} & set(requests[0])
    asyncio.run(run())


def test_stopped_and_disabled_extension_invalidates_pending_call(monkeypatch):
    install()
    calls=[];monkeypatch.setattr(manager,'start',lambda eid:None)
    monkeypatch.setattr(manager,'request',lambda *args,**kw:calls.append(args))
    async def run():
        snapshots=await runtime.prepare([],False)
        manager.stop('demo')
        trace=[]
        await runtime.dispatch('<demo_call>{"action":"stop","args":{}}</demo_call>',snapshots,'missing',0,False,trace,lambda e:None)
        assert trace[0]['status']=='error' and not calls
    asyncio.run(run())


def test_timeout_is_uncertain_and_not_replayed(monkeypatch):
    install();monkeypatch.setattr(manager,'start',lambda eid:None)
    def fail(*args,**kw):raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(manager,'request',fail)
    async def run():
        conv=store.create_conversation();store.begin_turn(conv.id,'req','你好',conv.timezone,'web','OFF')
        attempt=store.get_request('req')['attempt'];snapshots=await runtime.prepare([],False);trace=[]
        raw='<demo_call>{"action":"stop","args":{}}</demo_call>'
        await runtime.dispatch(raw,snapshots,'req',attempt,False,trace,lambda e:None)
        assert trace[-1]['status']=='uncertain'
        await runtime.dispatch(raw,snapshots,'req',attempt,False,trace,lambda e:None)
        assert trace[-1]['status']=='error'
    asyncio.run(run())


def test_skill_disable_rejects_write_and_read():
    configuration.save('diary-write',{'enabled':False,'injection':'always'})
    assert 'diary-write' not in {i['name'] for i in skills.catalog()}
    with pytest.raises(ValueError):skills.read_skill('diary-write')
    assert skills.write_actions('<app_call name="append_diary_entry">{"content":"hello","tags":[]}</app_call>')[1]


def test_management_headers_and_private_proxy(monkeypatch):
    install()
    with TestClient(app) as client:
        assert client.post('/api/extensions/demo/start').status_code==403
        assert client.get('/apps/demo/api/shutdown').status_code==503
        assert client.get('/apps/demo/api/invoke').status_code==503
        assert client.post('/apps/demo/api/state',json={}).status_code==503
        assert client.get('/api/extensions').json()['extensions'][0]['id']=='demo'


def test_toy_real_process_http_no_bluetooth(tmp_path,monkeypatch):
    import shutil,socket
    directory=manager.DIRECTORY/'toy'
    source=Path(__file__).resolve().parents[2]/'extensions/toy'
    if not source.is_dir():pytest.skip('未安装独立toy扩展')
    shutil.copytree(source,directory,ignore=shutil.ignore_patterns('__pycache__','data','.git'))
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    p=directory/'extension.json';manifest=json.loads(p.read_text(encoding='utf-8'));manifest['internal_port']=port;p.write_text(json.dumps(manifest),encoding='utf-8')
    monkeypatch.setattr(manager,'DATA_DIR',tmp_path/'data')
    manager.set_enabled('toy',True)
    try:
        manager.start('toy')
        assert manager.running('toy')
        state=manager.request('toy','/api/health',method='GET')
        assert not state['device']['connected'] and not state['device']['scanning']
        with TestClient(app) as client:
            panel=client.get('/apps/toy/')
            assert panel.status_code==200 and "fetch('./api/'" in panel.text
            assert client.post('/apps/toy/api/state',json={},headers={'X-Extension-Panel':'1'}).status_code==200
        # TestClient lifespan closes only this test-owned extension.
        assert not manager.running('toy')
    finally:manager.stop('toy')
