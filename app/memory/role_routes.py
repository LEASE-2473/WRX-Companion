from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.memory import role as memory
from app.common.errors import api_error

router = APIRouter(prefix='/api/role-memory')
class GenerateInput(BaseModel):
    conversation_id: str
    date: str
    entry_type: str = 'daily_summary'
    start_time: str = '00:00'
    end_time: str = '24:00'
class HistoryPreviewInput(BaseModel):
    conversation_id: str
    history_mode: str = 'since'
    history_since: str | None = None
    history_depth: int = Field(default=20, ge=0)

@router.post('/history-preview')
def history_preview(value: HistoryPreviewInput):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.models import RuntimeSettings
    try:
        conv = memory.store.get_conversation(value.conversation_id)
        since = value.history_since
        if value.history_mode == 'since' and since:
            date = datetime.fromisoformat(since)
            if date.tzinfo is None:
                date = date.replace(tzinfo=ZoneInfo(conv.timezone))
            since = date.isoformat()
        runtime = RuntimeSettings(history_mode=value.history_mode, history_since=since, history_depth=value.history_depth)
        messages = memory.history_context(conv.id, runtime)
        return {'count':len(messages), 'estimated_tokens':memory.estimate_prompt_tokens(messages) if messages else 0,
                'history_since':runtime.history_since, 'timezone':conv.timezone}
    except (ValueError,KeyError) as exc:
        raise api_error(exc)
class EditInput(memory.RecordInput):
    conversation_id: str
class ModeInput(BaseModel):
    mode: str
class BookInput(BaseModel):
    conversation_id: str
    name: str = Field(min_length=1, max_length=100)
    text: str
    separator: str = '---'
    scope: str = 'character'

@router.get('/settings')
def settings():
    memory.migrate_profiles()
    memory.upgrade_prompt_defaults()
    return memory.public_settings()
@router.put('/settings')
def save_settings(value: memory.MemorySettings):
    return memory.save_settings(value.model_dump())
@router.get('/prompt-defaults')
def prompt_defaults():
    return {k: {'prompt':p.prompt,'instant_prompt':p.instant_prompt} for k,p in memory.presets().items()}
@router.get('/{character_id}')
def records(character_id: str, conversation_id: str):
    try:
        if memory.store.get_conversation(conversation_id).character_id != character_id:
            raise ValueError('角色与会话不匹配')
        _, _, hot = memory.hot_context(character_id, conversation_id)
        result = memory.all_records(character_id)
        for record in result:
            record['vectorized'] = bool(record.pop('vector', None)) and record.get('vector_signature') == memory.signature(memory.settings().vector)
        return {'records': result, 'hot': hot, 'jobs': memory.job_status(character_id)}
    except (ValueError, KeyError) as exc:
        raise api_error(exc)
@router.post('/{character_id}/{kind}')
def create(character_id: str, kind: str, value: EditInput):
    try:
        if kind=='event': raise ValueError('事件与约定已改为系统记忆填表')
        return memory.put(kind, character_id, value.conversation_id, value.model_dump())
    except (ValueError, KeyError) as exc:
        raise api_error(exc)
@router.put('/{character_id}/{kind}/{rid}')
def edit(character_id: str, kind: str, rid: str, value: EditInput):
    try:
        if kind=='event': raise ValueError('事件与约定已改为系统记忆填表')
        return memory.put(kind, character_id, value.conversation_id, value.model_dump(), rid)
    except (ValueError, KeyError) as exc:
        raise api_error(exc)
@router.post('/{character_id}/records/{rid}/mode')
async def mode(character_id: str, rid: str, value: ModeInput):
    try:
        record = await memory.switch(character_id, rid, value.mode)
        record.pop('vector', None)
        return record
    except Exception as exc:
        raise api_error(ValueError(str(exc)))
@router.delete('/{character_id}/diary/{rid}')
def delete_diary(character_id: str, rid: str):
    try:
        return memory.delete_diary(character_id,rid)
    except (ValueError,KeyError) as exc:
        raise api_error(exc)
@router.post('/{character_id}/generate/{kind}')
async def generate(character_id: str, kind: str, value: GenerateInput):
    try:
        if kind!='diary': raise ValueError('AI角色记忆只生成日记，客观事实请使用系统记忆')
        if memory.store.get_conversation(value.conversation_id).character_id != character_id:
            raise ValueError('角色与会话不匹配')
        return await memory.generate(kind, value.conversation_id, value.date, entry_type=value.entry_type, start_time=value.start_time, end_time=value.end_time)
    except Exception as exc:
        raise api_error(ValueError(str(exc)))
@router.post('/{character_id}/import/book')
async def import_book(character_id: str, value: BookInput):
    try:
        result = await memory.import_book(character_id, value.conversation_id, value.name, value.text, value.separator, value.scope)
        return {'count': len(result)}
    except (ValueError, KeyError) as exc:
        raise api_error(exc)
@router.post('/connections/test/{kind}')
async def test_api(kind: str, value: dict | None = None):
    try:
        config = memory.settings()
        if kind == 'embed':
            result = await memory.get_embeddings(['连接测试'], config.vector)
            return {'dimensions': len(result[0])}
        if kind == 'rank':
            from app.memory.vector_store import get_rerank_scores
            return {'scores': await get_rerank_scores('测试', ['连接测试'], config.vector)}
        if kind not in config.presets:
            raise ValueError('未知 API')
        llm = memory.OpenAICompatibleLlm(memory.task_llm(config.presets[kind], (value or {}).get('conversation_id')))
        return {'reply': await llm.complete([memory.ChatMessage(role='user', content='请回复 OK')])}
    except Exception as exc:
        raise api_error(ValueError(str(exc)))
