import asyncio
import json
from datetime import timedelta
import pytest
from app.chat import store
from app.character import state as emotion
from app.providers import profiles as provider_store
from app.memory import role as role_memory
from app.models import TokenUsage
from app.chat.core import core
from fastapi.testclient import TestClient
from app.main import app


def conversation(monkeypatch):
    now=store.utcnow();monkeypatch.setattr(store,'utcnow',lambda:now)
    conv=store.create_conversation()
    store.begin_turn(conv.id,'initial','你好',conv.timezone,'web','OFF')
    store.finish_turn('initial','你好',TokenUsage(),[],[],{})
    emotion.state(conv.id)
    return conv,now


def manual(cid,n,v):
    with store.database() as db:
        db.execute('BEGIN IMMEDIATE')
        return emotion.apply(db,store._conversation(db,cid),[{'emotion':n,'operation':'set','value':v}],'user')


def test_sparse_protocol_stream_and_validation():
    raw='正文'+emotion.OPEN+'{"updates":[{"emotion":"生气","operation":"add","value":20}]}' + emotion.CLOSE
    visible=''
    for index in range(1,len(raw)+1):
        safe=emotion.visible_stream(raw[:index]);assert safe.startswith(visible);visible=safe
    assert visible=='正文'
    text,updates,silent,error=emotion.split_reply(raw)
    assert text=='正文' and updates[0]['value']==20 and not silent and error is None
    assert emotion.split_reply('正文'+emotion.OPEN+'invalid')[0:2]==('正文',[])
    for items in [[None],[{'emotion':'精力','value':40}],[{'emotion':'生气','value':float('nan')}],[{'emotion':'生气','value':True}]]:
        with pytest.raises(ValueError):emotion.validate_updates(items)


def test_active_cooling_direction_expiry_and_manual_revision(monkeypatch):
    conv,now=conversation(monkeypatch);manual(conv.id,'生气',80)
    assert emotion.state(conv.id,now+timedelta(minutes=9))['values']['生气']==80
    s=emotion.state(conv.id,now+timedelta(minutes=10));assert s['phase']=='冷却中'
    with store.database() as db:
        s['directions']['生气']={'direction':'up','degree':2,'until':(now+timedelta(minutes=70)).isoformat()};emotion.write(db,conv,s)
    assert emotion.state(conv.id,now+timedelta(minutes=25))['values']['生气']==82
    assert emotion.state(conv.id,now+timedelta(minutes=130))['values']['生气']==83
    # 手动覆盖阻止已启动模型的旧结果回写。
    current=manual(conv.id,'生气',40)
    with store.database() as db:
        emotion.apply(db,store._conversation(db,conv.id),[{'emotion':'生气','value':90,'operation':'set'}],'web',expected_revision=current['revision']-1)
    assert emotion.state(conv.id)['values']['生气']==40


@pytest.mark.parametrize('intervene',[False,True])
def test_manager_once_per_cooling_epoch_and_stale_guard(monkeypatch,intervene):
    conv,now=conversation(monkeypatch);monkeypatch.setattr(store,'utcnow',lambda:now+timedelta(minutes=11))
    store.save_setting('role_emotion_settings',{'summary_enabled':True})
    calls=[]
    class Fake:
        last_usage=TokenUsage()
        def __init__(self,p):pass
        async def complete(self,messages):
            calls.append(messages)
            if intervene:manual(conv.id,'生气',70)
            return '{"states":[{"emotion":"生气","direction":"down","degree":2}]}'
    monkeypatch.setattr(emotion,'resolve_llm',lambda *a:None);monkeypatch.setattr(emotion,'OpenAICompatibleLlm',Fake)
    assert asyncio.run(emotion.summarize(conv.id))['status']==('stale' if intervene else 'done')
    assert asyncio.run(emotion.summarize(conv.id))['status']=='already_processed'
    assert len(calls)==1
    store.begin_turn(conv.id,'next','继续聊',conv.timezone,'web','OFF');store.finish_turn('next','好',TokenUsage(),[],[],{})
    assert emotion.state(conv.id)['phase']=='会话中'
    monkeypatch.setattr(store,'utcnow',lambda:now+timedelta(minutes=22))
    assert asyncio.run(emotion.summarize(conv.id))['status']==('stale' if intervene else 'done')
    assert len(calls)==2


def test_chat_protocol_not_in_history_or_stream_and_replay(monkeypatch):
    class Fake:
        last_usage=TokenUsage()
        def set_generation_parameters(self,value):pass
        async def stream_complete(self,messages):
            for piece in ['你好<emo','tion_update>{"updates":[{"emotion":"生气","operation":"add","value":20}]}','</emotion_update>']:yield piece
    monkeypatch.setattr(core,'llm_for',lambda *a:Fake())
    with TestClient(app) as client:
        conv=client.post('/api/conversations').json();payload={'request_id':'protocol','content':'你好','timezone':'Asia/Shanghai','search_mode':'OFF'}
        r=client.post('/api/conversations/'+conv['id']+'/messages/stream',json=payload)
        events=[json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['type']=='complete'
        assert ''.join(e['text'] for e in events if e['type']=='delta')=='你好'
        assert store.get_conversation(conv['id']).messages[-1].content=='你好'
        assert emotion.state(conv['id'])['values']['生气']==20
        client.post('/api/conversations/'+conv['id']+'/messages/stream',json=payload)
        assert emotion.state(conv['id'])['values']['生气']==20


def test_profiles_migrate_without_collision_and_mask_keys():
    provider_store.upsert_provider_profile('llm',{'id':'memory-diary','name':'existing','model':'existing','api_key':'original'})
    cfg=role_memory.settings();cfg.presets['diary'].llm.model='old';cfg.presets['diary'].llm.api_key='legacy';role_memory.save_settings(cfg.model_dump())
    role_memory.migrate_profiles();updated=role_memory.settings()
    assert updated.presets['diary'].llm_profile_id!='memory-diary'
    assert provider_store.get_profile('llm','memory-diary').api_key=='original'
    assert role_memory.task_llm(updated.presets['diary']).api_key=='legacy'
    assert 'legacy' not in json.dumps(role_memory.public_settings())
    provider_store.upsert_provider_profile('embedding',{'id':'embed','name':'embed'})
    with pytest.raises(KeyError):provider_store.set_active_provider_profile('llm','embed')


def test_manager_failure_is_logged_without_retry(monkeypatch):
    conv,now=conversation(monkeypatch);monkeypatch.setattr(store,'utcnow',lambda:now+timedelta(minutes=11))
    store.save_setting('role_emotion_settings',{'summary_enabled':True})
    class Fake:
        last_usage=TokenUsage()
        def __init__(self,p):pass
        async def complete(self,messages):return '{"states":[{"emotion":"生气","direction":"up","degree":99}]}'
    monkeypatch.setattr(emotion,'resolve_llm',lambda *a:None);monkeypatch.setattr(emotion,'OpenAICompatibleLlm',Fake)
    assert asyncio.run(emotion.summarize(conv.id))['status']=='error'
    assert asyncio.run(emotion.summarize(conv.id))['status']=='already_processed'
    assert emotion.state(conv.id)['directions']=={}


def test_silence_is_explicit_opt_in_and_no_assistant_message(monkeypatch):
    raw=emotion.OPEN+'{"updates":[{"emotion":"生气","operation":"set","value":90}],"action":"SILENT"}'+emotion.CLOSE
    assert not emotion.split_reply(raw,emotion.EmotionSettings())[2]
    store.save_setting('role_emotion_settings',{'allow_silence':True})
    class Fake:
        last_usage=TokenUsage()
        def set_generation_parameters(self,p):pass
        async def stream_complete(self,messages):yield raw
    monkeypatch.setattr(core,'llm_for',lambda *a:Fake())
    with TestClient(app) as client:
        cid=client.post('/api/conversations').json()['id']
        reply=client.post(f'/api/conversations/{cid}/messages/stream',json={'request_id':'silent','content':'你好','timezone':'Asia/Shanghai','search_mode':'OFF'})
        events=[json.loads(line[6:]) for line in reply.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['action']=='SILENT'
        assert len(store.get_conversation(cid).messages)==1
        assert emotion.state(cid)['values']['生气']==90


def assessment_model(monkeypatch, response=None, intervene=None):
    calls=[]
    class Fake:
        last_usage=TokenUsage(input_tokens=20,output_tokens=50)
        def __init__(self,p):pass
        async def complete(self,messages):
            calls.append(messages)
            if intervene:intervene()
            return response if response is not None else json.dumps({'updates':[{'emotion':n,'operation':'set','value':60+i} for i,n in enumerate(emotion.LABELS[:-1])]})
    monkeypatch.setattr(emotion,'resolve_llm',lambda *a:None);monkeypatch.setattr(emotion,'OpenAICompatibleLlm',Fake)
    return calls


def test_assessment_full_values_without_cooling_or_old_value_anchor(monkeypatch):
    conv,now=conversation(monkeypatch)
    calls=assessment_model(monkeypatch)
    result=asyncio.run(emotion.assess(conv.id))
    assert result['status']=='done'
    assert all(result['state']['values'][n]==60+i for i,n in enumerate(emotion.LABELS[:-1]))
    assert 'current' not in json.loads(calls[0][1].content)
    assert 'messages' in json.loads(calls[0][1].content)
    with store.database() as db:
        assert db.execute('SELECT count(*) FROM emotion_summaries').fetchone()[0]==0
        assert 'assessment' in db.execute('SELECT document FROM emotion_logs ORDER BY id DESC').fetchone()[0]
    assert len(emotion.validate_updates([{'emotion':n,'operation':'add','value':20} for n in emotion.LABELS[:-1]]))==11
    assert '没有1–2项的限制' in emotion.PROTOCOL


@pytest.mark.parametrize('response',['{"updates":[{"emotion":"生气","value":90}]}','{"updates":null}','not json'])
def test_assessment_invalid_batch_leaves_values(monkeypatch,response):
    conv,now=conversation(monkeypatch);before=emotion.state(conv.id)['values']
    assessment_model(monkeypatch,response)
    with pytest.raises(ValueError,match='原值未被覆盖'):asyncio.run(emotion.assess(conv.id))
    assert emotion.state(conv.id)['values']==before
    assert conv.id not in emotion._assessing


def test_assessment_manual_override_discards_full_batch(monkeypatch):
    conv,now=conversation(monkeypatch)
    assessment_model(monkeypatch,intervene=lambda:manual(conv.id,'生气',90))
    assert asyncio.run(emotion.assess(conv.id))['status']=='stale'
    current=emotion.state(conv.id)['values']
    assert current['生气']==90 and current['爱意']==10


def test_assessment_rejects_concurrent_requests_and_chat(monkeypatch):
    conv,now=conversation(monkeypatch);calls=assessment_model(monkeypatch)
    emotion._assessing.add(conv.id)
    try:
        with pytest.raises(store.Conflict):asyncio.run(emotion.assess(conv.id))
    finally:emotion._assessing.discard(conv.id)
    store.begin_turn(conv.id,'busy','正在聊',conv.timezone,'web','OFF')
    with pytest.raises(store.Conflict):asyncio.run(emotion.assess(conv.id))
    assert not calls and conv.id not in emotion._assessing


def test_latest_round_changes_persist_and_ignore_manual_clock(monkeypatch):
    conv,now=conversation(monkeypatch)
    store.begin_turn(conv.id,'multi','你吃醋了吗',conv.timezone,'web','OFF')
    result=store.finish_turn('multi','嗯',TokenUsage(),[],[],{'emotion_updates':[{'emotion':'吃醋','operation':'set','value':80},{'emotion':'委屈','operation':'add','value':40}]})
    assert result['emotion_change']['changes']==[{'emotion':'吃醋','before':0,'after':80},{'emotion':'委屈','before':0,'after':40}]
    manual(conv.id,'吃醋',20)
    emotion.state(conv.id,now+timedelta(hours=1))
    with TestClient(app) as client:
        change=client.get(f'/api/role-state/{conv.id}/latest-change').json()['change']
        assert change['request_id']=='multi'
        assert change['changes']==result['emotion_change']['changes']


def test_latest_round_no_changes_does_not_reuse_previous_updates(monkeypatch):
    conv,now=conversation(monkeypatch)
    store.begin_turn(conv.id,'changed','你好',conv.timezone,'web','OFF')
    store.finish_turn('changed','好',TokenUsage(),[],[],{'emotion_updates':[{'emotion':'生气','operation':'set','value':90}]})
    store.begin_turn(conv.id,'unchanged','继续',conv.timezone,'web','OFF')
    store.finish_turn('unchanged','好',TokenUsage(),[],[],{})
    with TestClient(app) as client:
        change=client.get(f'/api/role-state/{conv.id}/latest-change').json()['change']
        assert change['request_id']=='unchanged' and change['status']=='unchanged' and change['changes']==[]


def test_legacy_round_change_is_not_invented(monkeypatch):
    conv,now=conversation(monkeypatch)
    with store.database() as db:
        db.execute("UPDATE requests SET execution=? WHERE id='initial'",(store.dumps({}),))
    with TestClient(app) as client:
        assert client.get(f'/api/role-state/{conv.id}/latest-change').json()=={'change':None}
