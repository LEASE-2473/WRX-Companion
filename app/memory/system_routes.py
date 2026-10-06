from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal
from app.memory import system as memory
from app.common.errors import api_error

router=APIRouter(prefix='/api/system-memory')

class ScanInput(BaseModel):
    conversation_id: str
    start: str
    end: str

class ModeInput(BaseModel):
    conversation_id: str
    mode: str

@router.get('/settings')
def settings():
    return memory.settings().model_dump()

@router.put('/settings')
async def save_settings(value: memory.Settings):
    try:
        if value.scope not in ('character','conversation'): raise ValueError('无效绑定')
        if value.llm_profile_id:
            from app.providers.profiles import get_profile
            get_profile('llm',value.llm_profile_id)
        memory.prompt_files.write('system',value.prompt)
        memory.store.save_setting('system_memory',value.model_dump(exclude={'prompt'}))
        if value.auto_cold_mode == 'immediate':
            memory.schedule_all_cold(force=True)
        return value.model_dump()
    except (ValueError,KeyError) as exc: raise api_error(exc)

@router.get('/{character_id}')
def records(character_id: str, conversation_id: str):
    try:
        rows=memory.rows(character_id,conversation_id)
        from app.memory.role import settings as role_settings
        vector_config=role_settings().vector
        for r in rows:
            r['vectorized']=memory.vector_ready(r,vector_config)
            r.pop('vector')
        with memory.store.database() as db:
            jobs=[dict(r) for r in db.execute('SELECT * FROM system_memory_batches WHERE character_id=? ORDER BY range_start DESC LIMIT 30',(character_id,))]
        return {'rows':rows,'progress':memory._progress.get(character_id),'batches':jobs}
    except (ValueError,KeyError) as exc: raise api_error(exc)

class VectorRangeInput(ScanInput):
    kinds: list[Literal['summary','person','item','agreement']] = Field(min_length=1,max_length=4)

@router.post('/{character_id}/vector-selection')
def vector_selection(character_id:str,value:VectorRangeInput):
    try:
        from app.memory.role import settings as role_settings
        config=role_settings().vector
        rows=memory.vector_selection(character_id,value.conversation_id,value.start,value.end,value.kinds)
        return {'selected':len(rows),'pending':sum(not memory.vector_ready(r,config) for r in rows),'already_cold':sum(r['mode']=='cold' for r in rows)}
    except (ValueError,KeyError) as exc:raise api_error(exc)

@router.post('/{character_id}/bulk-cold')
async def bulk_cold(character_id:str,value:VectorRangeInput):
    try:return await memory.bulk_cold(character_id,value.conversation_id,value.start,value.end,value.kinds)
    except (ValueError,KeyError) as exc:raise api_error(exc)

@router.post('/{character_id}/scan')
async def scan(character_id: str,value: ScanInput):
    try:
        conv=memory.store.get_conversation(value.conversation_id)
        if conv.character_id!=character_id: raise ValueError('角色与会话不匹配')
        return memory.start_scan(character_id,conv.id,memory.parse_time(value.start,conv.timezone),memory.parse_time(value.end,conv.timezone),memory.settings())
    except (ValueError,KeyError) as exc: raise api_error(exc)

@router.post('/{character_id}/cancel')
async def cancel(character_id: str):
    task=memory._tasks.get(character_id)
    if task and not task.done():
        task.cancel()
        memory._progress[character_id]['status']='cancelled'
        await memory.asyncio.gather(task,return_exceptions=True)
    return {'status':'cancelling'}

@router.post('/{character_id}/{rid}/mode')
async def mode(character_id: str,rid: str,value: ModeInput):
    try:
        await memory.change_mode(character_id,value.conversation_id,rid,value.mode)
        return {'status':'done'}
    except Exception as exc: raise api_error(ValueError(str(exc)))

@router.put('/{character_id}/{rid}')
async def edit(character_id: str,rid: str,conversation_id: str,value: memory.Data):
    try:
        row=next((r for r in memory.rows(character_id,conversation_id) if r['id']==rid),None)
        if not row: raise KeyError(rid)
        fields=value.model_dump(exclude_unset=True,exclude={'id'})
        allowed={'summary':{'content','tag'},'person':{'name','relationship','history','impression'},'item':{'name','description','location'},'agreement':{'content'}}[row['kind']]
        if set(fields)-allowed or any(v is None for v in fields.values()): raise ValueError('字段无效')
        if not fields: return {'status':'unchanged'}
        if any(k in fields and not fields[k].strip() for k in ('name','content')): raise ValueError('名称／正文不能为空')
        with memory.store.database() as db:
            table,sequence=memory.schema.locate(rid)
            db.execute(f'UPDATE {table} SET '+','.join(k+'=?' for k in fields)+",mode='hot',vector=NULL,vector_signature='' WHERE sequence=? AND character_id=?",[*fields.values(),sequence,character_id])
        if memory.settings().auto_cold_mode == 'immediate':
            memory.schedule_cold(character_id, conversation_id, force=True)
        return {'status':'done'}
    except (ValueError,KeyError) as exc: raise api_error(exc)

@router.delete('/{character_id}/{rid}')
def delete(character_id: str,rid: str,conversation_id: str):
    try:
        if not any(r['id']==rid for r in memory.rows(character_id,conversation_id)): raise KeyError(rid)
        with memory.store.database() as db:
            table,sequence=memory.schema.locate(rid)
            db.execute(f'DELETE FROM {table} WHERE sequence=? AND character_id=?',(sequence,character_id))
        return {'status':'done'}
    except (ValueError,KeyError) as exc: raise api_error(exc)
