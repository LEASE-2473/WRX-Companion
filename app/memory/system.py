from app.common.time_format import utc_seconds
"""按显示时间分批填表；模型只提交数据，整个批次验证后事务写入。"""
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from app.common.identity import new_id
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ConfigDict
from app.chat import store
from app.models import ChatMessage, StoredMessage

from app.memory import prompt_files
from app.memory import system_schema as schema

class Settings(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(default=60, ge=1, le=10080)
    delay_seconds: float = Field(default=2, ge=0, le=60)
    scope: Literal['character'] = 'character'
    llm_profile_id: str | None = None
    prompt: str = Field(default_factory=lambda: prompt_files.read('system'),min_length=20,max_length=30000)

class Data(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = None
    name: str = Field(default='', max_length=200)
    content: str = Field(default='', max_length=50000)
    tag: str = Field(default='', max_length=500)
    relationship: str | None = Field(default=None, max_length=1000)
    history: str | None = Field(default=None, max_length=50000)
    impression: str | None = Field(default=None, max_length=10000)
    description: str | None = Field(default=None, max_length=10000)
    location: str | None = Field(default=None, max_length=1000)

class Output(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary: Data | None = None
    people: list[Data] = Field(default_factory=list, max_length=100)
    items: list[Data] = Field(default_factory=list, max_length=100)
    agreements: list[Data] = Field(default_factory=list, max_length=100)

def initialize(db):
    schema.initialize(db)
    db.execute("CREATE TABLE IF NOT EXISTS system_memory_batches(id TEXT PRIMARY KEY,character_id TEXT NOT NULL,conversation_id TEXT NOT NULL,range_start TEXT NOT NULL,range_end TEXT NOT NULL,status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '',scope TEXT NOT NULL DEFAULT 'character')")
    if 'scope' not in [r[1] for r in db.execute('PRAGMA table_info(system_memory_batches)')]:
        db.execute("ALTER TABLE system_memory_batches ADD COLUMN scope TEXT NOT NULL DEFAULT 'character'")

def settings():
    return Settings.model_validate(store.get_setting('system_memory', {}) | {'prompt':prompt_files.read('system'),'scope':'character'})

def rows(character_id, cid):
    conv = store.get_conversation(cid)
    if conv.character_id != character_id:
        raise ValueError('角色与会话不匹配')
    with store.database() as db:
        initialize(db)
        return schema.rows(db,character_id)

def parse_time(value, tz):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(timezone.utc).replace(microsecond=0)

def raw_messages(character_id, cid, start, end, scope='character'):
    """直接读取messages表，不经过history_selection。分支副本按请求和内容去重。"""
    from app.memory.role import plain_dialogue
    found = []
    seen = set()
    with store.database() as db:
        query = 'SELECT m.id,m.origin_id,m.request_id,m.role,m.document,m.conversation_id,c.timezone FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.character_id=?'
        args = [character_id]
        if scope == 'conversation':
            query += ' AND c.id=?'; args.append(cid)
        for row in db.execute(query+' ORDER BY m.sequence', args):
            m = StoredMessage.model_validate(dict(json.loads(row['document']),id=row['id'],request_id=row['request_id'],role=row['role'],timezone=row['timezone'],local_datetime=''))
            if m.role not in ('user','assistant') or not m.timestamp:
                continue
            dt = parse_time(m.timestamp, m.timezone)
            content = plain_dialogue(m.content)
            key = (row['origin_id'] or m.id,m.role,content)
            if start <= dt < end and content and key not in seen:
                seen.add(key); found.append((dt,m,row['conversation_id']))
    return sorted(found,key=lambda x:x[0])

def apply(db, character_id, cid, scope, start, end, output):
    if scope!='character':raise ValueError('系统记忆仅按角色绑定')
    start,end=utc_seconds(start),utc_seconds(end)
    initialize(db)
    proposals=[('summary',output.summary)] if output.summary else []
    proposals += [('person',x) for x in output.people]+[('item',x) for x in output.items]+[('agreement',x) for x in output.agreements]
    for kind,value in proposals:
        table=schema.TABLES[kind]
        allowed=set(schema.FIELDS[kind]) | ({'id'} if kind in ('person','item') else set())
        if value.model_fields_set-allowed:raise ValueError('模型返回了不属于该表的字段')
        old=None
        if kind in ('person','item'):
            if not value.name.strip():raise ValueError('人物／物品名称不能为空')
            if value.id:
                target,sequence=schema.locate(value.id)
                if target!=table:raise ValueError('不能串表更新')
                old=db.execute(f'SELECT * FROM {table} WHERE sequence=? AND character_id=?',(sequence,character_id)).fetchone()
                if not old or old['mode']=='cold':raise ValueError('不能更新不存在、冷区或其他角色记录')
            else:
                old=db.execute(f'SELECT * FROM {table} WHERE character_id=? AND name=? ORDER BY sequence LIMIT 1',(character_id,value.name.strip())).fetchone()
                if old and old['mode']=='cold':raise ValueError('同名冷记录请先转热后更新')
        elif not value.content.strip() or value.id:raise ValueError('总结与约定仅允许追加非空正文')
        fields={key:getattr(value,key) for key in schema.FIELDS[kind] if getattr(value,key) is not None}
        if 'name' in fields:fields['name']=fields['name'].strip()
        if old:
            fields['name']=old['name']
            if fields.get('history'):
                fields['history']=old['history'] if fields['history'] in old['history'] else '\n'.join(filter(None,[old['history'],fields['history']]))
            fields.update(vector=None,vector_signature='')
            db.execute(f"UPDATE {table} SET "+','.join(k+'=?' for k in fields)+' WHERE sequence=? AND character_id=?',[*fields.values(),old['sequence'],character_id])
        else:
            if kind=='agreement' and db.execute(f'SELECT 1 FROM {table} WHERE character_id=? AND content=?',(character_id,value.content)).fetchone():continue
            fields.update(character_id=character_id,conversation_id=cid,range_start=start,range_end=end)
            cols=list(fields)
            db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",list(fields.values()))

_locks = {}
_tasks = {}
_progress = {}

async def batch(character_id, cid, start, end, config=None):
    from app.memory import role as memory
    config = config or settings()
    conv = store.get_conversation(cid)
    if conv.character_id != character_id or config.scope not in ('character','conversation'): raise ValueError('角色或绑定无效')
    key = character_id if config.scope=='character' else cid
    lock = _locks.setdefault(key,asyncio.Lock())
    async with lock:
        messages = raw_messages(character_id,cid,start,end,config.scope)
        digest = hashlib.sha256(store.dumps([(m.id,m.content,m.timestamp) for _,m,_ in messages]).encode()).hexdigest()
        jid = hashlib.sha256(f'{key}:{utc_seconds(start)}:{utc_seconds(end)}:{digest}'.encode()).hexdigest()
        with store.database() as db:
            initialize(db)
            if db.execute("SELECT 1 FROM system_memory_batches WHERE id=? AND status IN ('done','empty')",(jid,)).fetchone(): return 'already_processed'
            db.execute('INSERT OR REPLACE INTO system_memory_batches VALUES (?,?,?,?,?,?,?,?)',(jid,character_id,cid,utc_seconds(start),utc_seconds(end),'running','',config.scope))
        try:
            if messages:
                preset = memory.settings().presets['diary'].model_copy(deep=True)
                if config.llm_profile_id: preset.llm_profile_id=config.llm_profile_id; preset.follow_conversation=False
                profile = memory.task_llm(preset,cid)
                if not profile.model or not profile.base_url: raise ValueError('请在系统记忆设置选择填表模型')
                llm = memory.OpenAICompatibleLlm(profile)
                llm.set_generation_parameters({'temperature':0.2})
                existing = [{k:v for k,v in r.items() if k not in ('vector','vector_signature')} for r in rows(character_id,cid) if r['mode']=='hot' and r['scope']==config.scope]
                payload = {'character':store.get_character(character_id).name,'timezone':conv.timezone,'existing':[{k:v for k,v in r.items() if k not in ('character_id','conversation_id','scope','mode','sequence','vectorized') and v not in ('',None)} for r in existing],'messages':[{'time':dt.astimezone(ZoneInfo(conv.timezone)).isoformat(),'role':m.role,'content':memory.plain_dialogue(m.content)} for dt,m,source in messages]}
                async with asyncio.timeout(180):
                    raw = await llm.complete([ChatMessage(role='system',content=config.prompt),ChatMessage(role='user',content=store.dumps(payload))])
                raw = raw.strip()
                if raw.startswith('```'): raw=raw.split('\n',1)[1].rsplit('```',1)[0]
                output = Output.model_validate_json(raw)
                with store.database() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if not db.execute('SELECT 1 FROM conversations WHERE id=? AND character_id=?',(cid,character_id)).fetchone(): raise ValueError('来源会话已删除')
                    current=[{k:v for k,v in r.items() if k not in ('vector','vector_signature')} for r in schema.rows(db,character_id) if r['mode']=='hot']
                    if current!=existing: raise ValueError('填表期间记忆已被编辑，请重试该批次')
                    apply(db,character_id,cid,config.scope,start.astimezone(ZoneInfo(conv.timezone)).isoformat(),end.astimezone(ZoneInfo(conv.timezone)).isoformat(),output)
                    db.execute("UPDATE system_memory_batches SET status='done' WHERE id=?",(jid,))
                return 'done'
            with store.database() as db: db.execute("UPDATE system_memory_batches SET status='empty' WHERE id=?",(jid,))
            return 'empty'
        except BaseException as exc:
            with store.database() as db: db.execute("UPDATE system_memory_batches SET status='error',error=? WHERE id=?",(str(exc)[:1000],jid))
            raise

async def scan(character_id,cid,start,end,config):
    state=_progress[character_id]
    try:
        cursor=start
        while cursor<end:
            stop=min(end,cursor+timedelta(minutes=config.interval_minutes))
            state['range']=cursor.isoformat()+' → '+stop.isoformat()
            state['result']=await batch(character_id,cid,cursor,stop,config)
            state['completed']+=1
            cursor=stop
            if cursor<end: await asyncio.sleep(config.delay_seconds)
        state['status']='done'
    except asyncio.CancelledError:
        state['status']='cancelled'; raise
    except Exception as exc:
        state.update(status='error',error=str(exc))

def start_scan(character_id,cid,start,end,config):
    if character_id in _tasks and not _tasks[character_id].done(): raise ValueError('该角色已有追溯任务')
    if end<=start: raise ValueError('结束时间必须晚于开始时间')
    count=int((end-start).total_seconds()//(config.interval_minutes*60))+1
    if count>10000: raise ValueError('分批数量过多，请缩小范围')
    _progress[character_id]={'status':'running','completed':0,'total':int(((end-start).total_seconds()+config.interval_minutes*60-1)//(config.interval_minutes*60))}
    _tasks[character_id]=asyncio.create_task(scan(character_id,cid,start,end,config))
    return _progress[character_id]

def text(row):
    fields = {'name':'名称','content':'概述','tag':'标签','relationship':'关系','history':'历史事件','impression':'用户印象','description':'描述','location':'位置'}
    return '[系统记忆 '+row['kind']+'｜'+row['range_start']+' 至 '+row['range_end']+']\n'+'\n'.join(label+'：'+row[k] for k,label in fields.items() if row.get(k))

def hot_context(character_id,cid):
    from app.memory.role import settings as role_settings
    config=role_settings().vector
    return [ChatMessage(role='system',content=text(r)) for r in rows(character_id,cid) if r['mode']=='hot' or not config.enabled or not vector_ready(r,config)]

async def change_mode(character_id,cid,rid,mode):
    from app.memory import role as memory
    if mode not in ('hot','cold'): raise ValueError('无效冷热状态')
    row=next((r for r in rows(character_id,cid) if r['id']==rid),None)
    if not row: raise KeyError(rid)
    vector=None; signature=''
    if mode=='cold':
        config=memory.settings().vector
        if not config.enabled: raise ValueError('请先启用并配置向量记忆')
        vector=row['vector'] if vector_ready(row,config) else (await memory.get_embeddings([text(row)],config))[0]
        signature=memory.signature(config)
    with store.database() as db:
        table,sequence=schema.locate(rid)
        current=db.execute(f'SELECT * FROM {table} WHERE sequence=? AND character_id=?',(sequence,character_id)).fetchone()
        if not current or text(schema.decode(row['kind'],current))!=text(row):raise ValueError('记录已变更，请重试')
        db.execute(f'UPDATE {table} SET mode=?,vector=?,vector_signature=? WHERE sequence=? AND character_id=?',(mode,schema.pack(vector) if vector is not None else None,signature,sequence,character_id))

def vector_ready(row,config):
    from app.memory.role import signature
    return bool(row.get('vector')) and row['vector_signature']==signature(config)


def vector_selection(character_id,cid,start,end,kinds):
    conv=store.get_conversation(cid)
    if conv.character_id!=character_id:raise ValueError('角色与会话不匹配')
    start,end=parse_time(start,conv.timezone),parse_time(end,conv.timezone)
    if end<=start:raise ValueError('结束时间必须晚于开始时间')
    if not kinds or set(kinds)-set(schema.TABLES):raise ValueError('请选择有效的系统表')
    selected=[]
    with store.database() as db:
        initialize(db)
        for kind in dict.fromkeys(kinds):
            table=schema.TABLES[kind]
            selected.extend(schema.decode(kind,r) for r in db.execute(f'SELECT * FROM {table} WHERE character_id=? AND julianday(range_start)<julianday(?) AND julianday(range_end)>julianday(?) ORDER BY range_start,sequence',(character_id,utc_seconds(end),utc_seconds(start))))
    return selected

async def bulk_cold(character_id,cid,start,end,kinds):
    from app.memory import role as memory
    selected=vector_selection(character_id,cid,start,end,kinds)
    cfg=memory.settings().vector
    if selected and not cfg.enabled:raise ValueError('请先启用并配置向量记忆')
    result={'selected':len(selected),'converted':0,'reindexed':0,'skipped':0,'failed':0,'errors':[]}
    for row in selected:
        if row['mode']=='cold' and vector_ready(row,cfg):
            result['skipped']+=1;continue
        try:
            await change_mode(character_id,cid,row['id'],'cold')
            result['reindexed' if row['mode']=='cold' else 'converted']+=1
        except Exception as exc:
            result['failed']+=1;result['errors'].append({'id':row['id'],'error':str(exc)[:300]})
    return result

async def maintenance():
    config=settings()
    if not config.enabled: return
    now=store.utcnow()
    seen=set()
    for conv in store.list_conversations():
        key=conv.character_id if config.scope=='character' else conv.id
        if key in seen or (_tasks.get(conv.character_id) and not _tasks[conv.character_id].done()): continue
        seen.add(key)
        with store.database() as db:
            initialize(db)
            latest=db.execute("SELECT MAX(range_end) FROM system_memory_batches WHERE character_id=? AND scope=? AND status IN ('done','empty') AND (?='character' OR conversation_id=?)",(conv.character_id,config.scope,config.scope,conv.id)).fetchone()[0]
        # 首次自动处理最近一个完整周期；更早记录由显式追溯处理。
        cursors=store.get_setting('system_memory_auto_starts',{})
        cursor_key=config.scope+':'+key
        if latest:
            start=parse_time(latest,conv.timezone)
        else:
            if cursor_key not in cursors:
                cursors[cursor_key]=(now-timedelta(minutes=config.interval_minutes)).isoformat()
                store.save_setting('system_memory_auto_starts',cursors)
            start=parse_time(cursors[cursor_key],conv.timezone)
        end=start+timedelta(minutes=config.interval_minutes)
        if end<=now:
            start_scan(conv.character_id,conv.id,start,end,config)

async def shutdown():
    tasks=[t for t in _tasks.values() if not t.done()]
    for t in tasks: t.cancel()
    if tasks: await asyncio.gather(*tasks,return_exceptions=True)

def recover():
    with store.database() as db:
        initialize(db)
        db.execute("UPDATE system_memory_batches SET status='error',error='应用重启中断；重新选择原范围追溯即可跳过已完成批次' WHERE status='running'")
