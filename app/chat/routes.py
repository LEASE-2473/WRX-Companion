from app.common.errors import api_error
import json
import asyncio
import httpx
from app.common.identity import new_id
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, Response

from app.chat import store
from app.chat.core import core
from app.models import Character, ConversationCreate, HeartbeatSettings, SearchSettings, TextTurn, MessageBranch, MessageSpeech
from app.search.service import public_search_settings, save_search_settings, search_web
from app.prompting.preset_store import get_prompt_preset
from app.prompting.lorebook_store import get_lorebook
from app.providers.profiles import get_profile, load_provider_profiles
from app.providers.client import HttpTts, ProviderError
from app.voice.pipeline import normalize_voice_reply

router = APIRouter()

class ContextPreviewInput(BaseModel):
    content: str = ''

@router.post('/api/conversations/{cid}/context-preview')
def context_preview(cid: str, value: ContextPreviewInput):
    try:
        conversation = store.get_conversation(cid)
        character = store.get_character(conversation.character_id)
        compiled, _ = core.context(conversation, character, value.content, 'web')
        return {'llm_messages': [m.model_dump() for m in compiled.messages], 'prompt_trace': compiled.trace,
                'preview_note': '使用已保存配置、现有历史和当前时间；未发送模型请求，未保存输入。冷召回及联网结果在真实执行时产生，此处不调用外部 API。'}
    except (KeyError, ValueError) as exc:
        raise api_error(exc)

@router.get('/api/conversations/{cid}/context-last')
def context_last(cid: str):
    try:
        store.get_conversation(cid)
        with store.database() as db:
            row = db.execute("SELECT id FROM requests WHERE conversation_id=? AND status!='running' ORDER BY debug_order DESC,rowid DESC LIMIT 1", (cid,)).fetchone()
        if not row:
            return {'debug': None}
        request = store.get_request(row['id'], include_debug=True)
        return {'request_id': row['id'], 'status': request['status'], 'usage': request['usage'],
                'debug': request.get('debug'),
                'debug_expired': request.get('debug') is None,
                'debug_retention_count': 20}
    except (KeyError, ValueError) as exc:
        raise api_error(exc)


@router.get('/api/conversations/{cid}/state')
def current_emotion_state(cid: str):
    try:
        from app.character import state as role_state
        return role_state.state(cid)
    except (KeyError, ValueError) as exc:
        raise api_error(exc)




def stream_job(job):
    async def events():
        async for event in core.events(job):
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post('/api/conversations/{cid}/requests/{rid}/cancel')
async def cancel_request(cid: str, rid: str):
    try:
        return await core.cancel(cid, rid)
    except (KeyError, ValueError) as exc:
        raise api_error(exc)


@router.get("/api/characters")
def characters():
    return store.list_characters()


def validate_character(value):
    if value.preset_id:
        get_prompt_preset(value.preset_id)
    if value.lorebook_id:
        get_lorebook(value.lorebook_id)
    if value.llm_profile_id:
        if get_profile("llm", value.llm_profile_id).purpose != "chat":
            raise ValueError("角色必须绑定对话用途 Profile")
    if value.tts_profile_id:
        get_profile("tts", value.tts_profile_id)


@router.post("/api/characters")
def new_character(value: Character):
    try:
        value.id = ""
        validate_character(value)
        return store.save_character(value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.put("/api/characters/{cid}")
def update_character(cid: str, value: Character):
    try:
        store.get_character(cid)
        value.id = cid
        validate_character(value)
        return store.save_character(value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.delete("/api/characters/{cid}")
def remove_character(cid: str):
    try:
        store.delete_character(cid)
        return {"ok": True}
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.get("/api/conversations")
def conversations(character_id: str | None = None):
    return store.list_conversations(character_id)


@router.post("/api/conversations")
def new_conversation(value: ConversationCreate | None = None):
    value = value or ConversationCreate()
    try:
        return store.create_conversation(value.character_id, value.name, value.timezone)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.get("/api/conversations/{cid}")
def conversation(cid: str):
    try:
        return store.get_conversation(cid)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post("/api/conversations/{cid}/messages/stream")
async def send_text(cid: str, value: TextTurn):
    try:
        job = core.submit(cid, value.request_id, value.content, value.timezone, "web", value.search_mode, images=value.images)
        return stream_job(job)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.get("/api/conversations/{cid}/requests/{rid}")
def request_status(cid: str, rid: str):
    try:
        request = store.get_request(rid)
        if request["conversation_id"] != cid:
            raise KeyError("请求不存在")
        request.update(store.replay_request(rid))
        return {key:value for key,value in request.items() if key not in ("fingerprint","fingerprint_version")}
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


class MessageEditInput(BaseModel):
    content: str


@router.patch("/api/conversations/{cid}/messages/{mid}")
def edit_message(cid: str, mid: str, value: MessageEditInput):
    try:
        return store.edit_user_message(cid, mid, value.content)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post("/api/conversations/{cid}/messages/{mid}/branch")
def branch_message(cid: str, mid: str, value: MessageBranch):
    try:
        return store.branch_conversation(cid, mid, value.action, value.content)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post("/api/conversations/{cid}/messages/{mid}/tts")
async def speak_message(cid: str, mid: str, value: MessageSpeech | None = None):
    try:
        conversation = store.get_conversation(cid)
        message = next((m for m in conversation.messages if m.id == mid), None)
        if not message:
            raise KeyError("消息不存在")
        if message.role != "assistant":
            raise ValueError("仅支持朗读 AI 回复")
        character = store.get_character(conversation.character_id)
        profile_id = (value.profile_id if value else None) or character.tts_profile_id or load_provider_profiles().active_tts_profile_id
        if not profile_id:
            raise ValueError("请在模型与语音设置中配置 TTS，或为角色绑定音色")
        profile = get_profile("tts", profile_id)
        if not profile.endpoint.strip():
            raise ValueError("当前 TTS 缺少 Endpoint")
        audio = await asyncio.wait_for(HttpTts().synthesize(normalize_voice_reply(message.content), profile), timeout=120)
        if audio.startswith(b"RIFF"):
            mime = "audio/wav"
        elif audio.startswith(b"OggS"):
            mime = "audio/ogg"
        elif audio.startswith(b"fLaC"):
            mime = "audio/flac"
        elif audio.startswith(b"ID3") or len(audio) > 1 and audio[0] == 255 and audio[1] & 224 == 224:
            mime = "audio/mpeg"
        else:
            raise ValueError("TTS 返回了无法识别的音频格式，请配置 WAV、MP3、OGG 或 FLAC")
        return Response(audio, media_type=mime, headers={"Cache-Control": "no-store"})
    except (httpx.HTTPError, ProviderError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="TTS 服务调用失败，请检查连接、权限与音色配置") from exc
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.put("/api/conversations/{cid}/heartbeat")
def heartbeat_settings(cid: str, value: HeartbeatSettings):
    try:
        return store.save_heartbeat(cid, value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post("/api/conversations/{cid}/heartbeat/check")
async def check_heartbeat(cid: str):
    try:
        job, reason = core.heartbeat(cid)
        return {"status": "running", "request_id": job.request_id} if job else {"status": "skipped", "reason": reason}
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.get("/api/conversations/{cid}/heartbeat/logs")
def heartbeat_logs(cid: str):
    try:
        return store.heartbeat_logs(cid)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.get("/api/search/settings")
def search_settings():
    return public_search_settings()


@router.put("/api/search/settings")
def update_search_settings(value: SearchSettings):
    try:
        return save_search_settings(value)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post("/api/search/test")
async def test_search():
    try:
        results = await search_web("天气")
        return {"ok": True, "results": results}
    except ValueError as exc:
        raise api_error(exc) from exc


@router.delete("/api/conversations/{cid}")
def remove_conversation(cid: str):
    try:
        store.delete_conversation(cid)
        return {"ok": True}
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc


@router.post('/api/conversations/{cid}/messages/{mid}/resend')
async def resend_message(cid: str, mid: str, value: TextTurn):
    try:
        job = core.submit(cid, value.request_id, value.content, value.timezone, 'web', value.search_mode, resend_mid=mid)
        return stream_job(job)
    except (KeyError, ValueError) as exc:
        raise api_error(exc) from exc


@router.post("/api/conversations/{cid}/messages/{mid}/regenerate")
async def regenerate_message(cid: str, mid: str, value: TextTurn):
    try:
        job = core.submit(cid, value.request_id, value.content, value.timezone, "web", value.search_mode, regenerate_mid=mid, images=value.images)
        return stream_job(job)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc
