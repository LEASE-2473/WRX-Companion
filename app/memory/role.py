from app.common.time_format import utc_seconds
"""角色记忆：正文按来源保存，冷热仅决定运行时注入路径。"""
import asyncio
from datetime import datetime, timedelta, time
import hashlib
import json
import logging
import re
import httpx
from typing import Literal
from app.common.identity import new_id
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from app.chat import store
from app.memory import schema as memory_schema
from app.models import ChatMessage, LlmProviderProfile, VectorMemoryConfig, VectorMemoryState, VectorLibrary, VectorChunk
from app.providers.client import OpenAICompatibleLlm
from app.prompting.compiler import estimate_prompt_tokens
from app.memory.vector_store import get_embeddings, retrieve_vector_memories, parse_vector_source

TABLES = {'diary': 'diaries', 'activity': 'ai_notes', 'event': 'shared_records', 'book': 'external_memory_chunks'}
from app.memory import prompt_files

class TaskPreset(BaseModel):
    prompt: str
    history_limit: int = Field(default=200, ge=1, le=2000)
    include_notes: bool = False
    include_events: bool = True
    llm: LlmProviderProfile = Field(default_factory=lambda: LlmProviderProfile(id='memory', name='独立填表 LLM'))
    llm_profile_id: str | None = None
    follow_conversation: bool = False
    instant_prompt: str = Field(default_factory=lambda: prompt_files.read('diary_instant'))
    temperature: float = Field(default=0.3, ge=0, le=2)

class Policy(BaseModel):
    enabled: bool = True
    scope: Literal['character', 'conversation'] = 'character'
    default_mode: Literal['hot', 'cold'] = 'hot'
    auto_cold_days: int = Field(default=0, ge=0, le=36500)

def presets():
    return {kind: TaskPreset(prompt=prompt_files.read(kind)) for kind in ('diary','activity','event')}

class MemorySettings(BaseModel):
    policies: dict[str, Policy] = Field(default_factory=lambda: {'diary': Policy(auto_cold_days=7), 'activity': Policy(), 'event': Policy()})
    presets: dict[str, TaskPreset] = Field(default_factory=presets)
    vector: VectorMemoryConfig = Field(default_factory=VectorMemoryConfig)
    profiles_migrated: bool = False
    embedding_profile_id: str | None = None
    rerank_profile_id: str | None = None
    hot_token_limit: int = Field(default=6000, ge=100, le=1000000)
    diary_enabled: bool = False
    diary_hour: int = Field(default=3, ge=0, le=23)
    timezone: str = 'Asia/Shanghai'

    @model_validator(mode='after')
    def validate_keys(self):
        if set(self.policies) != {'diary', 'activity', 'event'} or set(self.presets) != {'diary', 'activity', 'event'}:
            raise ValueError('必须保留日记、自主活动、重要事件三类配置')
        store.valid_timezone(self.timezone)
        return self

class RecordInput(BaseModel):
    content: str = Field(min_length=1, max_length=100000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    occurred_at: str | None = None
    date: str | None = None
    scope: Literal['character', 'conversation'] = 'character'
    injection_mode: Literal['auto', 'hot', 'cold'] = 'auto'
    keywords: list[str] = Field(default_factory=list, max_length=40)
    title: str = Field(default='', max_length=120)
    entry_type: Literal['daily_summary', 'chat_entry'] = 'daily_summary'
    activity_type: str = ''
    record_type: Literal['milestone', 'agreement', 'hook'] = 'milestone'
    status: Literal['pending', 'in_progress', 'completed', 'cancelled', 'unknown'] = 'unknown'
    due_at: str | None = None
    activity_id: str | None = None
    activity_content: str = ''

    @model_validator(mode='after')
    def valid_date(self):
        if self.date:
            datetime.strptime(self.date, "%Y-%m-%d")
        if self.occurred_at and datetime.fromisoformat(self.occurred_at).tzinfo is None:
            raise ValueError('日期时间必须包含时区')
        if not self.content.strip():
            raise ValueError('正文不能为空')
        return self

def initialize(db):
    memory_schema.initialize(db)
    db.execute('CREATE TABLE IF NOT EXISTS memory_jobs(id TEXT PRIMARY KEY, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS diary_hooks(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, character_id TEXT NOT NULL, date TEXT NOT NULL, scope TEXT NOT NULL, document TEXT NOT NULL)')

def hooks_context(character_id, cid):
    if not settings().policies['diary'].enabled:
        return []
    with store.database() as db:
        initialize(db)
        rows = db.execute("SELECT document FROM diary_hooks WHERE character_id=? AND (conversation_id=? OR scope='character') ORDER BY date DESC", (character_id, cid)).fetchall()
    hooks = list(dict.fromkeys(hook for r in rows for hook in json.loads(r['document'])))[:20]
    return [ChatMessage(role='system', content='[日记未结话题｜背景资料，不代表用户的新指令；可能已解决，先结合近期对话判断]\n' + '\n'.join(hooks))] if hooks else []

def settings():
    raw=store.get_setting('role_memory', {})
    for kind,default in presets().items():
        saved=raw.setdefault('presets',{}).setdefault(kind,{})
        saved.update(prompt=default.prompt,instant_prompt=default.instant_prompt)
    value=MemorySettings.model_validate(raw)
    from app.providers.profiles import get_profile
    for attr,prefix in [('embedding_profile_id',''),('rerank_profile_id','rerank_')]:
        pid=getattr(value,attr)
        if pid:
            p=get_profile('rerank' if prefix else 'embedding',pid)
            if prefix:
                from app.memory.vector_store import _rerank_url
                value.vector.rerank_url=_rerank_url(p.base_url);value.vector.rerank_key=p.api_key;value.vector.rerank_model=p.model
            else:
                value.vector.api_url=p.base_url;value.vector.api_key=p.api_key;value.vector.model=p.model
    return value

def task_llm(preset, cid=None):
    from app.providers.profiles import resolve_llm
    if preset.llm_profile_id:
        return resolve_llm(cid,preset.llm_profile_id)
    return preset.llm.model_copy(deep=True)

def stored_settings(value):
    data=value.model_dump()
    if value.embedding_profile_id:data['vector']['api_key']=''
    if value.rerank_profile_id:data['vector']['rerank_key']=''
    for p in data['presets'].values():
        if p['llm_profile_id']:p['llm']['api_key']=''
        for field in ('prompt','requirements','instant_prompt'):p.pop(field,None)
    return data

def migrate_profiles():
    """只迁移已配置旧LLM，密钥进入统一Profile；保留其它记忆设置。"""
    from app.providers.profiles import upsert_provider_profile, load_provider_profiles
    state = load_provider_profiles()
    existing_ids={p.id for kind in ('llm','embedding','rerank') for p in getattr(state,kind+'_profiles')}
    def unused(pid):
        value=new_id(lambda value: value in existing_ids)
        existing_ids.add(value)
        return value
    value=settings()
    if value.profiles_migrated:return
    for kind,p in value.presets.items():
        if not p.llm_profile_id and p.llm.api_key and p.llm.model:
            doc=p.llm.model_dump();doc.update(id=unused('memory-'+kind),name='角色记忆 · '+kind)
            upsert_provider_profile('llm',doc)
            p.llm_profile_id=doc['id'];p.follow_conversation=False
            p.llm=LlmProviderProfile(id='memory',name='已迁移至统一Profile')
    for attr,purpose,url,key,model in [('embedding_profile_id','embedding','api_url','api_key','model'),('rerank_profile_id','rerank','rerank_url','rerank_key','rerank_model')]:
        if not getattr(value,attr) and getattr(value.vector,url) and (purpose=='embedding' or value.vector.rerank_key):
            pid=unused('memory-'+purpose)
            upsert_provider_profile(purpose,{'id':pid,'name':'角色记忆 · '+purpose,'base_url':getattr(value.vector,url),'api_key':getattr(value.vector,key),'model':getattr(value.vector,model)})
            setattr(value,attr,pid);setattr(value.vector,key,'')
    value.profiles_migrated=True
    store.save_setting('role_memory',stored_settings(value))

def upgrade_prompt_defaults():
    """兼容旧入口；Markdown为唯一文本来源，不自动覆盖用户文件。"""
    return None

def public_settings():
    value = settings().model_dump()
    for preset in value['presets'].values():
        preset['llm']['api_key_set'] = bool(preset['llm']['api_key'])
        preset['llm']['api_key'] = ''
    for key in ('api_key', 'rerank_key'):
        value['vector'][key + '_set'] = bool(value['vector'][key])
        value['vector'][key] = ''
    return value

def save_settings(value):
    old = settings()
    new = MemorySettings.model_validate(value)
    new.profiles_migrated = old.profiles_migrated
    from app.providers.profiles import get_profile
    for preset in new.presets.values():
        if preset.llm_profile_id: get_profile('llm',preset.llm_profile_id)
    for key in ['embedding_profile_id','rerank_profile_id']:
        if getattr(new,key): get_profile('embedding' if key=='embedding_profile_id' else 'rerank',getattr(new,key))
    if old.embedding_profile_id and not new.embedding_profile_id:
        new.vector.api_url='';new.vector.api_key='';new.vector.model='';new.vector.enabled=False
    if old.rerank_profile_id and not new.rerank_profile_id:
        new.vector.rerank_url='';new.vector.rerank_key='';new.vector.rerank_model='';new.vector.rerank_enabled=False
    for kind, preset in new.presets.items():
        if not preset.llm.api_key:
            preset.llm.api_key = old.presets[kind].llm.api_key
    for key in ('api_key', 'rerank_key'):
        if not getattr(new.vector, key) and not (key=='api_key' and old.embedding_profile_id and not new.embedding_profile_id) and not (key=='rerank_key' and old.rerank_profile_id and not new.rerank_profile_id):
            setattr(new.vector, key, getattr(old.vector, key))
    prompt_files.save_role(new)
    store.save_setting('role_memory', stored_settings(new))
    return public_settings()

def all_records(character_id):
    store.get_character(character_id)
    result = []
    with store.database() as db:
        initialize(db)
        for kind, table in TABLES.items():
            result += [memory_schema.read(db, kind, r) for r in db.execute(f'SELECT * FROM {table} WHERE character_id=?', (character_id,))]
    return sorted(result, key=lambda r: r.get('date') or r.get('occurred_at') or r['created_at'], reverse=True)

def visible(character_id, cid, config=None):
    config = config or settings()
    return [r for r in all_records(character_id) if r['kind'] != 'event' and (r['scope'] == 'character' or r['conversation_id'] == cid) and
            (r['kind'] == 'book' or config.policies[r['kind']].enabled)]

def put(kind, character_id, cid, value, record_id=None, internal=False, sources=None):
    if kind not in TABLES:
        raise ValueError('未知记忆类型')
    conversation = store.get_conversation(cid)
    if conversation.character_id != character_id:
        raise ValueError('角色与会话不匹配')
    item = RecordInput.model_validate(value)
    if kind == 'event' and len(item.tags) != 1:
        raise ValueError('重要事件必须有且仅有一个事件标签')
    if kind == 'activity' and not record_id and not internal:
        raise ValueError('自主活动记录只能由实际活动执行器创建')
    config = settings()
    previous = next((r for r in all_records(character_id) if r['id'] == record_id and r['kind'] == kind), None) if record_id else None
    if record_id and previous is None:
        raise KeyError(record_id)
    if previous and previous['conversation_id'] != cid:
        raise ValueError('编辑不能改变记录的来源会话')
    now = utc_seconds(store.utcnow())
    data = dict(previous or {}, **item.model_dump(), id=record_id or new_id(lambda value: any(r["id"] == value for r in all_records(character_id))), kind=kind,
                character_id=character_id, conversation_id=cid, updated_at=now)
    data.setdefault('created_at', now)
    data.setdefault('mode', 'hot')
    data.setdefault('sources', sources or [])
    data['occurred_at'] = item.occurred_at or (previous or {}).get('occurred_at') or (None if kind == 'event' else now)
    if kind == 'diary':
        data['timezone'] = conversation.timezone
        data['date'] = item.date or datetime.fromisoformat(data['occurred_at']).astimezone(ZoneInfo(conversation.timezone)).date().isoformat()
        data.pop('occurred_at', None)
    if not previous or previous['content'] != data['content']:
        data['vector'] = None
        data['vector_signature'] = ''
        if kind != 'book':
            data['mode'] = 'hot'
    if kind == 'book':
        data['mode'] = 'cold'
    with store.database() as db:
        initialize(db)
        memory_schema.write(db, data)
    return data

def save_record(record):
    with store.database() as db:
        initialize(db)
        memory_schema.write(db, record)

def delete_diary(character_id, rid):
    """永久删除日记，关联、索引与未结话题同步清理，不保存恢复快照。"""
    with store.database() as db:
        initialize(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM diaries WHERE memory_id=? AND character_id=?', (rid,character_id)).fetchone()
        if not row: raise KeyError(rid)
        record = memory_schema.read(db,'diary',row)
        db.execute('DELETE FROM diaries WHERE memory_id=?',(rid,))
        db.execute('DELETE FROM memory_sources WHERE memory_id=?',(rid,))
        db.execute('DELETE FROM memory_vectors WHERE memory_id=?',(rid,))
        cid=record['conversation_id']
        latest=db.execute("SELECT diary_date,scope,unresolved_hooks FROM diaries WHERE conversation_id=? AND entry_type='daily_summary' ORDER BY diary_date DESC,updated_at DESC LIMIT 1",(cid,)).fetchone()
        db.execute('DELETE FROM diary_hooks WHERE conversation_id=?',(cid,))
        if latest:
            db.execute('INSERT INTO diary_hooks VALUES (?,?,?,?,?)',(cid,character_id,latest[0],latest[1],latest[2]))
        for job in db.execute('SELECT id,document FROM memory_jobs WHERE conversation_id=?',(cid,)).fetchall():
            if rid in json.loads(job['document']).get('record_ids',[]):
                db.execute('UPDATE memory_jobs SET status=?,updated_at=? WHERE id=?',('deleted',utc_seconds(store.utcnow()),job['id']))
    return {'status':'deleted','memory_id':rid}

def signature(config):
    return hashlib.sha256((config.api_url + '\n' + config.model).encode()).hexdigest()

async def switch(character_id, rid, mode):
    if mode not in ('auto', 'hot', 'cold'):
        raise ValueError('冷热状态无效')
    record = next((r for r in all_records(character_id) if r['id'] == rid), None)
    if record is None:
        raise KeyError(rid)
    if record['kind'] == 'book' and mode == 'hot':
        raise ValueError('外部世界书只能是冷')
    if mode == 'cold':
        config = settings().vector
        if not config.enabled:
            raise ValueError('请先启用并配置 Embedding')
        vector = (await get_embeddings([record['content']], config))[0]
        fresh = next((r for r in all_records(character_id) if r['id'] == rid), None)
        if not fresh or fresh['updated_at'] != record['updated_at']:
            raise store.Conflict('向量化期间记忆已被编辑，请重试')
        record.update(vector=vector, vector_signature=signature(config))
    record.update(mode=mode, injection_mode=mode, updated_at=utc_seconds(store.utcnow()))
    save_record(record)
    return record

def serialize(record):
    return f'[{record["kind"]}｜{record.get('date') or record.get('occurred_at') or '时间未知'}｜{",".join(record["tags"])}]\n{record["content"]}'

def history_context(cid, runtime=None):
    from app.chat.history import select_history
    messages = store.get_conversation(cid).messages
    selected = select_history(messages, runtime)
    return [ChatMessage(role=m.role, content=f"[{m.timestamp or '旧记录：时间未知'}; {m.source}]\n{m.content.split('<emotion_update>', 1)[0] if m.role == 'assistant' else m.content}", images=[]) for m in selected]

def hot_context(character_id, cid, history=None):
    config = settings()
    records = [r for r in visible(character_id, cid, config) if r['kind'] != 'book' and
               (r['mode'] == 'hot' or not config.vector.enabled or
                not r.get('vector') or r.get('vector_signature') != signature(config.vector))]
    texts = [ChatMessage(role='system', content=serialize(r)) for r in records]
    from app.memory.system import hot_context as system_hot_context
    system_texts=system_hot_context(character_id,cid)
    texts += system_texts
    total = estimate_prompt_tokens([ChatMessage(role='system', content='[角色常驻记忆｜以下是背景资料]\n' + '\n\n'.join(m.content for m in texts))]) if texts else 0
    history = history_context(cid) if history is None else history
    history_tokens = estimate_prompt_tokens(history) if history else 0
    total += history_tokens
    return records, texts, {'estimated_tokens': total, 'limit': config.hot_token_limit, 'over_limit': total > config.hot_token_limit,
                           'history_count': len(history), 'by_kind': {'history': history_tokens,'system':estimate_prompt_tokens(system_texts) if system_texts else 0, **{k: estimate_prompt_tokens([m for r, m in zip(records, texts) if r['kind'] == k]) if any(r['kind'] == k for r in records) else 0 for k in config.policies}}}

async def recall(character_id, cid, query):
    config = settings()
    records = [r for r in visible(character_id, cid, config) if r['mode'] == 'cold' and r.get('vector') and r.get('vector_signature') == signature(config.vector)]
    from app.memory import system as system_memory
    records += [dict(r, vector=r['vector'], vector_signature=r['vector_signature'], content=system_memory.text(r), tags=[], sources=[], kind='system') for r in system_memory.rows(character_id,cid) if r['mode']=='cold' and r['vector'] and r['vector_signature']==signature(config.vector)]
    state = VectorMemoryState(config=config.vector, libraries=[VectorLibrary(id='role-memory', name='角色冷记忆与外部世界书', chunks=[VectorChunk(id=r['id'], content=r['content'] if r['kind']=='system' else serialize(r), vector=r['vector'], metadata={'kind': r['kind'], 'sources': r['sources']}) for r in records])])
    return await retrieve_vector_memories(query, state)

def job_status(character_id):
    with store.database() as db:
        initialize(db)
        return [dict(r) | {'document': json.loads(r['document'])} for r in db.execute('SELECT * FROM memory_jobs WHERE character_id=? ORDER BY updated_at DESC LIMIT 30', (character_id,))]

def claim(jid, character_id, cid):
    with store.database() as db:
        initialize(db)
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM memory_jobs WHERE id=?', (jid,)).fetchone()
        if old and (old['status'] in ('done', 'empty') or (old['status'] == 'running' and datetime.fromisoformat(old['updated_at']) > store.utcnow() - timedelta(minutes=10))):
            return False
        db.execute('INSERT OR REPLACE INTO memory_jobs VALUES (?,?,?,?,?,?)', (jid, character_id, cid, 'running', utc_seconds(store.utcnow()), '{}'))
        return True

def plain_dialogue(text):
    text = re.sub(r'<(?:emotion_update|app_call)\b[^>]*>.*?</(?:emotion_update|app_call)>', '', text, flags=re.S)
    text = re.sub(r'<(?:emotion_update|app_call)\b.*$', '', text, flags=re.S)
    return re.sub(r'!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>', '', text, flags=re.I).strip()


def time_window(date, timezone, start_time='00:00', end_time='24:00'):
    day = datetime.strptime(date, '%Y-%m-%d').date(); tz = ZoneInfo(timezone)
    def boundary(value, end=False):
        if end and value == '24:00': return datetime.combine(day+timedelta(days=1), time.min, tz)
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value): raise ValueError('时间必须为HH:MM，结束时间可用24:00')
        return datetime.combine(day, time.fromisoformat(value), tz)
    start, end = boundary(start_time), boundary(end_time, True)
    if end <= start: raise ValueError('结束时间必须晚于开始时间')
    return start, end


def context_overflow(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code not in (400,413,422): return False
        detail = exc.response.text
    elif isinstance(exc, RuntimeError): detail = str(exc)
    else: return False
    return bool(re.search(r'context_length_exceeded|context window.{0,40}(exceed|limit|too)|maximum context length|too many tokens|input.{0,30}tokens.{0,30}(exceed|limit)|上下文.{0,15}(超限|超过)', detail, re.I))


async def summarize_diary(llm, prompt, input_data, audit, progress):
    async def run(items, merge=False):
        data = dict(input_data, messages=items)
        instruction = prompt_files.read('diary_merge') if merge else prompt
        progress()
        try:
            async with asyncio.timeout(180):
                raw = await llm.complete([ChatMessage(role='system', content=instruction),ChatMessage(role='user',content=json.dumps(data,ensure_ascii=False))])
            clean = raw.strip()
            if clean.startswith('```'): clean = clean.split('\n',1)[1].rsplit('```',1)[0]
            output = json.loads(clean)
            if not isinstance(output,dict) or not isinstance(output.get('content'),str) or not output['content'].strip(): raise ValueError('日记模型必须返回含非空content的JSON对象')
            audit.append({'stage':'merge' if merge else 'summary','status':'done','usage':llm.last_usage.model_dump(),'output':output});progress()
            return output
        except Exception as exc:
            if not context_overflow(exc): raise
            audit.append({'stage':'merge' if merge else 'summary','status':'context_overflow'});progress()
        if len(items)>1:
            middle=len(items)//2; halves=(items[:middle],items[middle:])
        elif items and len(items[0]['content'])>1:
            item=items[0];middle=len(item['content'])//2
            halves=([dict(item,content=item['content'][:middle])],[dict(item,content=item['content'][middle:])])
        else: raise ValueError('模型连最小对话与固定提示词也无法容纳，请检查日记模型或提示词')
        outputs=[await run(half,merge) for half in halves]
        combined=[{'time':half[0]['time']+' — '+half[-1]['time'],'role':'summary','content':json.dumps(output,ensure_ascii=False)} for half,output in zip(halves,outputs)]
        if merge and sum(len(x['content']) for x in combined)>=sum(len(x['content']) for x in items): raise ValueError('分段总结未缩短超限材料，请换更大上下文模型或精简提示词；未写入半成品')
        return await run(combined,True)
    return await run(input_data['messages'])


async def generate(kind, cid, date, automatic=False, entry_type='daily_summary', start_time='00:00', end_time='24:00'):
    if kind != 'diary': raise ValueError('AI角色记忆只生成日记，事件与约定请使用系统记忆')
    if entry_type not in ('daily_summary','chat_entry'): raise ValueError('生成类型无效')
    config = settings()
    conv = store.get_conversation(cid)
    target = datetime.strptime(date, '%Y-%m-%d').date()
    preset = config.presets[kind]
    profile = task_llm(preset, cid)
    if not profile.model or not profile.base_url:
        raise ValueError('请配置独立填表 LLM')
    start,end=time_window(date,conv.timezone,start_time if entry_type=='chat_entry' else '00:00',end_time if entry_type=='chat_entry' else '24:00')
    from app.memory.system import raw_messages
    messages=[m for _,m,_ in raw_messages(conv.character_id,cid,start,end,config.policies['diary'].scope)]
    selected_ids=[m.id for m in messages]
    selection=hashlib.sha256(store.dumps([start.isoformat(),end.isoformat(),[(m.id,plain_dialogue(m.content)) for m in messages]]).encode()).hexdigest()[:20]
    binding=conv.character_id if config.policies[kind].scope=='character' else cid
    jid=f'{kind}:{binding}:{date}' if automatic else f'{kind}:{cid}:{date}:{entry_type}:{selection}'
    audit=[]
    def progress(): finish_job(jid,'running',{'entry_type':entry_type,'start':start.isoformat(),'end':end.isoformat(),'calls':audit})
    if automatic:
        with store.database() as db:
            initialize(db)
            old = db.execute('SELECT status,updated_at FROM memory_jobs WHERE id=?', (jid,)).fetchone()
            if old and old['status'] == 'error' and datetime.fromisoformat(old['updated_at']) > store.utcnow() - timedelta(hours=1):
                return {'status': 'retry_later'}
    if not claim(jid, conv.character_id, cid):
        return {'status': 'already_processed'}
    try:
        tz = ZoneInfo(conv.timezone)
        if not messages:
            finish_job(jid, 'empty', {'reason': '所选时间范围没有聊天'})
            return {'status': 'empty'}
        character = store.get_character(conv.character_id)
        input_data={'range':start.isoformat()+' 至 '+end.isoformat()+'（含开始，不含结束）','date':date,'timezone':conv.timezone,'character':{'name':character.name},
                    'messages':[{'time':datetime.fromisoformat(m.timestamp).astimezone(tz).isoformat(),'role':m.role,'content':plain_dialogue(m.content)} for m in messages]}
        llm = OpenAICompatibleLlm(profile)
        llm.set_generation_parameters({'temperature': preset.temperature})
        prompt=preset.instant_prompt if entry_type=='chat_entry' else preset.prompt
        output=await summarize_diary(llm,prompt,input_data,audit,progress)
        raw=json.dumps(output,ensure_ascii=False)
        hooks = output.get('unresolved_hooks', [])
        if not isinstance(hooks, list) or len(hooks) > 10 or any(not isinstance(h, str) or not h.strip() or len(h) > 300 for h in hooks):
            raise ValueError('未结话题必须是最多10条、每条最多300字的非空字符串数组')
        proposals = [output]
        # 先验证全部输出，任何非法字段都不部分写入。
        values = [RecordInput(content=r['content'], title=r.get('title', ''), tags=r.get('tags', []), scope=config.policies[kind].scope) for r in proposals]
        created = []
        usages = [call['usage'] for call in audit if call['status'] == 'done']
        usage = {key: sum(u[key] for u in usages) if usages and all(u.get(key) is not None for u in usages) else None for key in llm.last_usage.model_dump()}
        with store.database() as db:
            initialize(db)
            for value in values:
                rid = new_id(lambda value: any(db.execute(f'SELECT 1 FROM {table} WHERE memory_id=?',(value,)).fetchone() for table in TABLES.values()))
                if entry_type == 'daily_summary':
                    existing = db.execute("SELECT memory_id FROM diaries WHERE character_id=? AND scope=? AND (?='character' OR conversation_id=?) AND diary_date=? AND entry_type='daily_summary' ORDER BY created_at LIMIT 1", (conv.character_id,config.policies[kind].scope,config.policies[kind].scope,cid,date)).fetchone()
                    if existing: rid=existing[0]
                # 批次事务与任务去重防止崩溃重试重复创建，实体使用随机身份。
                now = utc_seconds(store.utcnow())
                record = dict(value.model_dump(), id=rid, kind=kind, character_id=conv.character_id, conversation_id=cid,
                              mode='hot', vector=None, vector_signature='', created_at=now, updated_at=now,
                              sources=[m.id for m in messages])
                record['entry_type'] = entry_type
                record['timezone'] = conv.timezone
                record['date'] = date
                record.pop('occurred_at', None)
                record['unresolved_hooks'] = hooks
                previous = db.execute(f'SELECT created_at FROM {TABLES[kind]} WHERE memory_id=?', (rid,)).fetchone()
                if previous: record['created_at'] = previous[0]
                memory_schema.write(db, record)
                created.append(rid)
            if entry_type == 'daily_summary':
                if config.policies[kind].scope=='character':
                    db.execute("DELETE FROM diary_hooks WHERE character_id=? AND scope='character' AND date<=?",(conv.character_id,date))
                db.execute('INSERT INTO diary_hooks VALUES (?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET date=excluded.date,scope=excluded.scope,document=excluded.document WHERE excluded.date>=diary_hooks.date', (cid, conv.character_id, date, config.policies[kind].scope, store.dumps(hooks)))
            db.execute('UPDATE memory_jobs SET status=?,updated_at=?,document=? WHERE id=?', ('done', utc_seconds(store.utcnow()), store.dumps({'record_ids': created, 'usage': usage, 'raw': raw, 'entry_type': entry_type, 'source_ids': selected_ids, 'start':start.isoformat(), 'end':end.isoformat(), 'calls':audit}), jid))
        return {'status': 'done', 'record_ids': created}
    except asyncio.CancelledError:
        finish_job(jid, 'error', {'error': '任务已取消，未保存半成品', 'calls':audit})
        raise
    except Exception as exc:
        finish_job(jid, 'error', {'error': str(exc), 'calls':audit})
        raise

def finish_job(jid, status, document):
    with store.database() as db:
        initialize(db)
        db.execute('UPDATE memory_jobs SET status=?,updated_at=?,document=? WHERE id=?', (status, utc_seconds(store.utcnow()), store.dumps(document), jid))

async def record_activity(cid, activity_id, activity_content, execution_result):
    """由 Phase 4 实际活动执行器调用；先保存执行事实，再尝试独立笔记生成。"""
    if not activity_id or not activity_content or not isinstance(execution_result, dict):
        raise ValueError('必须提供实际活动 ID、内容和执行结果')
    conv = store.get_conversation(cid)
    existing = next((r for r in all_records(conv.character_id) if r['kind'] == 'activity' and r.get('activity_id') == activity_id and r['conversation_id'] == cid), None)
    if existing:
        return existing
    config = settings(); preset = config.presets['activity']
    record = put('activity', conv.character_id, cid, {
        'content': '实际活动：' + activity_content + '\n执行结果：' + json.dumps(execution_result, ensure_ascii=False),
        'tags': [], 'occurred_at': utc_seconds(store.utcnow()), 'scope': config.policies['activity'].scope,
        'activity_id': activity_id, 'activity_content': activity_content}, internal=True)
    record['execution_result'] = execution_result
    record['note_status'] = 'pending'
    save_record(record)
    try:
        profile = task_llm(preset, cid)
        if not profile.model:
            raise ValueError('未配置自主活动笔记 LLM，执行事实已保存')
        llm = OpenAICompatibleLlm(profile)
        llm.set_generation_parameters({'temperature': preset.temperature})
        async with asyncio.timeout(180):
            raw = await llm.complete([ChatMessage(role='system', content=preset.prompt),
                                      ChatMessage(role='user', content=record['content'])])
        output = json.loads(raw)
        checked = RecordInput.model_validate(record | {'content': output['content'], 'tags': output.get('tags', [])})
        record.update(content=checked.content, tags=checked.tags, note_status='done')
    except Exception as exc:
        record.update(note_status='error', note_error=str(exc))
    save_record(record)
    return record

async def import_book(character_id, cid, name, text, separator='---', scope='character'):
    if not text.strip() or len(text) > 2_000_000:
        raise ValueError('文本不能为空且最多 200 万字符')
    _, chunks = parse_vector_source(text, name, separator)
    # 长纯文本切成完整段落窗口；显式预切片保留原单元。
    if len(chunks) == 1 and len(chunks[0].content) > 2000:
        content = chunks[0].content
        chunks = [VectorChunk(id=str(i), content=content[i:i + 2000]) for i in range(0, len(content), 2000)]
    return [put('book', character_id, cid, {'content': c.content, 'tags': [name], 'occurred_at': utc_seconds(store.utcnow()), 'scope': scope}) for c in chunks]

async def maintenance():
    from app.memory.system import maintenance as system_maintenance
    await system_maintenance()
    config = settings()
    now = store.utcnow()
    for character in store.list_characters():
        char_id = character.id if hasattr(character, 'id') else character['id']
        for r in all_records(char_id):
            if r['kind'] == 'book' or r['mode'] != 'hot' or r['injection_mode'] != 'auto':
                continue
            policy = config.policies[r['kind']]
            age = 0
            if policy.auto_cold_days and (r.get('date') or r.get('occurred_at')):
                age = (now.astimezone(ZoneInfo(r.get('timezone', 'Asia/Shanghai'))).date() - datetime.strptime(r['date'], '%Y-%m-%d').date()).days if r['kind'] == 'diary' else (now - datetime.fromisoformat(r['occurred_at'])).days
            due = policy.default_mode == 'cold' or (policy.auto_cold_days and age >= policy.auto_cold_days)
            if due and config.vector.enabled:
                try:
                    changed = await switch(char_id, r['id'], 'cold')
                    changed['injection_mode'] = 'auto'
                    save_record(changed)
                except Exception as exc:
                    logging.warning('记忆转冷失败，保留热区：%s', type(exc).__name__)
    if config.diary_enabled:
        diary_bindings=set()
        for conv in store.list_conversations():
            cid = conv.id if hasattr(conv, 'id') else conv['id']
            conversation = store.get_conversation(cid)
            binding=conversation.character_id if config.policies['diary'].scope=='character' else cid
            if binding in diary_bindings: continue
            diary_bindings.add(binding)
            local = now.astimezone(ZoneInfo(conversation.timezone))
            if local.hour >= config.diary_hour:
                try:
                    await generate('diary', cid, (local.date() - timedelta(days=1)).isoformat(), automatic=True)
                except Exception as exc:
                    logging.warning('独立日记任务失败：%s', type(exc).__name__)

async def scheduler():
    while True:
        try:
            await maintenance()
        except Exception:
            logging.exception('记忆调度失败')
        await asyncio.sleep(300)
