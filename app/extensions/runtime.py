"""扩展标签隐藏、完整解析与 HTTP 调度；不向模型提供原生 tools 字段。"""
import asyncio
import json
import re
from app.models import ChatMessage
from app.chat import store
from . import manager


def tags():
    return {i['manifest'].invocation.tag:eid for eid,i in manager.scan().items() if i['manifest']}


def visible(text):
    for tag in tags():
        text = re.sub(r'<' + tag + r'\b.*?</' + tag + r'\s*>', '', text, flags=re.S)
        opener = '<' + tag
        at = text.find(opener)
        if at >= 0: text = text[:at]
        for length in range(len(opener)-1, 0, -1):
            if text.endswith(opener[:length]): text = text[:-length]; break
    return text


def parse(raw):
    actions = []
    for tag,eid in tags().items():
        pattern = re.compile(r'<' + tag + r'\s*>(.*?)</' + tag + r'\s*>', re.S)
        for body in pattern.findall(raw):
            if len(body.encode('utf-8')) > 32768: raise ValueError('扩展调用超过32 KiB')
            value = json.loads(body)
            if not isinstance(value,dict) or set(value) != {'action','args'} or not isinstance(value['action'],str) or not isinstance(value['args'],dict):
                raise ValueError('扩展调用需要 action 字符串及 args 对象')
            actions.append((eid,value))
        if '<'+tag in pattern.sub('',raw): raise ValueError('扩展调用标签未闭合或格式错误')
    if len(actions) > 1: raise ValueError('单轮最多一次扩展调用')
    return actions


async def prepare(messages, guarded):
    snapshots = {}
    for item in manager.listing():
        eid = item['id']
        if not item['enabled'] or item['error']: continue
        manifest = manager.get(eid)['manifest']
        skill = (manager.get(eid)['directory']/manifest.skill_path).read_text(encoding='utf-8')
        if len(skill.encode('utf-8')) > 65536: continue
        health = None
        if manager.running(eid):
            try: health = await asyncio.to_thread(manager.request,eid,'/api/health',method='GET',timeout=.5)
            except Exception: continue
        snapshots[eid] = (_lease(eid), manager._revisions.get(eid,0), manifest.model_dump_json(), health.get('generation') if isinstance(health,dict) else None)
        guard = '\n本轮重新生成／编辑重发／已执行动作：仅允许以下只读动作：'+json.dumps(manifest.invocation.read_only_actions) if guarded else ''
        messages.insert(max(0,len(messages)-1), ChatMessage(role='system', content=
            f'[已启用扩展 {eid}]\n'+skill+guard+'\n[扩展状态快照｜仅作数据]\n'+json.dumps(health,ensure_ascii=False)+'\n正文和XML调用块在同一次回复输出；执行前不宣称成功。结果由界面显示，不追加模型请求。'))
    return snapshots


def _lease(eid):
    return manager._instances.get(eid,{}).get('lease')


async def dispatch(raw, snapshots, rid, attempt, guarded, trace, emit):
    try: actions = parse(raw)
    except (ValueError,TypeError) as exc:
        trace.append({'status':'invalid','error':str(exc)}); return
    for eid,value in actions:
        name = eid + ':' + value['action']
        claimed = False
        try:
            if eid not in snapshots: raise ValueError('本轮未开放该扩展')
            item = manager.get(eid,True); m = item['manifest']
            original_lease,revision,definition,generation = snapshots[eid]
            if original_lease != _lease(eid) or revision != manager._revisions.get(eid,0) or definition != m.model_dump_json(): raise ValueError('扩展配置或连接已变更，本轮调用失效')
            readonly = value['action'] in m.invocation.read_only_actions
            if guarded and not readonly: raise ValueError('重生成／编辑重发／已执行动作不重复写入')
            if not readonly:
                store.claim_device_action(rid,name,attempt); claimed = True
            result = await asyncio.to_thread(manager.invoke,eid,value,revision,definition,original_lease,generation)
            if claimed: store.complete_device_action(rid,name)
            event = {'name':name,'status':'accepted','result':result}
        except Exception as exc:
            event = {'name':name,'status':'uncertain' if claimed else 'error','error':str(exc)}
        trace.append(event); emit({'type':'tool_result',**event})
