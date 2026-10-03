import base64
import asyncio
import json
import logging
from app.common.identity import new_id
from time import perf_counter
from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from app.models import Lorebook, ProcessRequest, PromptPreset
from app.prompting.lorebook_store import freeze_active_lorebook
from app.providers.profiles import freeze_active_provider_snapshot
from app.providers.client import get_providers
from app.settings.store import freeze_runtime_settings
from app.prompting.preset_store import freeze_active_prompt_preset
from app.chat.core import core
from app.chat.routes import stream_job
from app.chat import store as companion_store
from app.providers.client import VolcengineStt
from app.common.errors import api_error
from app.providers.diagnostics import safe_provider_detail as _safe_provider_detail
from fastapi import APIRouter

router = APIRouter()

PROVIDER_ROUND_SNAPSHOTS: dict[str, object] = {}


PROMPT_ROUND_SNAPSHOTS: dict[str, PromptPreset] = {}


LOREBOOK_ROUND_SNAPSHOTS: dict[str, Lorebook] = {}


HISTORY_DEPTH_ROUND_SNAPSHOTS: dict[str, int] = {}


def stash_provider_snapshot(snapshot) -> str:
    snapshot_id = new_id(lambda value: value in PROVIDER_ROUND_SNAPSHOTS)
    PROVIDER_ROUND_SNAPSHOTS[snapshot_id] = snapshot
    PROMPT_ROUND_SNAPSHOTS[snapshot_id] = freeze_active_prompt_preset()
    LOREBOOK_ROUND_SNAPSHOTS[snapshot_id] = freeze_active_lorebook()
    HISTORY_DEPTH_ROUND_SNAPSHOTS[snapshot_id] = freeze_runtime_settings().history_depth
    return snapshot_id


def take_provider_snapshot(snapshot_id: str):
    if not snapshot_id:
        return freeze_active_provider_snapshot()
    snapshot = PROVIDER_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    if snapshot is None:
        raise ValueError("本轮 Provider 快照已失效，请重新录音")
    return snapshot


def take_prompt_snapshot(snapshot_id: str) -> PromptPreset:
    if not snapshot_id:
        return freeze_active_prompt_preset()
    snapshot = PROMPT_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    if snapshot is None:
        raise ValueError("本轮 Prompt 快照已失效，请重新录音")
    return snapshot


def take_lorebook_snapshot(snapshot_id: str) -> Lorebook:
    if not snapshot_id:
        return freeze_active_lorebook()
    snapshot = LOREBOOK_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    if snapshot is None:
        raise ValueError("本轮 Lorebook 快照已失效，请重新录音")
    return snapshot


def take_history_depth_snapshot(snapshot_id: str) -> int:
    if not snapshot_id:
        return freeze_runtime_settings().history_depth
    snapshot = HISTORY_DEPTH_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    if snapshot is None:
        raise ValueError("本轮历史层数快照已失效，请重新录音")
    return snapshot


async def expire_provider_snapshot(snapshot_id: str) -> None:
    await asyncio.sleep(300)
    PROVIDER_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    PROMPT_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    LOREBOOK_ROUND_SNAPSHOTS.pop(snapshot_id, None)
    HISTORY_DEPTH_ROUND_SNAPSHOTS.pop(snapshot_id, None)


@router.post("/api/process/stream")
async def process_stream(request: ProcessRequest):
    if not request.conversation_id or not request.request_id:
        raise HTTPException(status_code=422, detail="语音请求需要 conversation_id 与 request_id")
    try:
        companion_store.get_conversation(request.conversation_id)
        companion_store.valid_timezone(request.timezone)
        snapshot = take_provider_snapshot(request.provider_snapshot_id)
        preset = take_prompt_snapshot(request.provider_snapshot_id)
        lorebook = take_lorebook_snapshot(request.provider_snapshot_id)
        take_history_depth_snapshot(request.provider_snapshot_id)
        transcript = request.transcript.strip()
        if not transcript:
            audio = base64.b64decode(request.audio_base64, validate=True)
            if len(audio) < 44:
                raise ValueError("No speech detected")
            transcript = await VolcengineStt(snapshot.stt).transcribe(audio)
        if not transcript.strip():
            raise ValueError("No speech detected")
        job = core.submit(request.conversation_id, request.request_id, transcript, request.timezone,
                          "voice", request.search_mode, snapshot, preset, lorebook)
        return stream_job(job)
    except (ValueError, KeyError) as exc:
        raise api_error(exc) from exc
    except Exception:
        raise HTTPException(status_code=502, detail="语音识别失败，请检查 STT 配置") from None


@router.websocket("/api/stt/stream")
async def stream_stt(websocket: WebSocket):
    await websocket.accept()
    try:
        provider_snapshot = freeze_active_provider_snapshot()
        stt, _, _ = get_providers(provider_snapshot)
        provider_snapshot_id = stash_provider_snapshot(provider_snapshot)
        asyncio.create_task(expire_provider_snapshot(provider_snapshot_id))
    except Exception as exc:
        await websocket.send_json({"type": "error", "detail": _safe_provider_detail(exc)})
        await websocket.close()
        return
    if not hasattr(stt, "transcribe_stream"):
        await websocket.send_json({"type": "error", "detail": "当前 STT Provider 不支持边录边传"})
        await websocket.close()
        return
    finish_received_at = None

    async def chunks():
        nonlocal finish_received_at
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if message.get("bytes") is not None:
                yield message["bytes"]
                continue
            if message.get("text"):
                try:
                    value = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if value.get("type") == "finish":
                    finish_received_at = perf_counter()
                    break

    async def ready():
        await websocket.send_json({"type": "ready", "provider_snapshot_id": provider_snapshot_id})

    async def partial(text: str):
        await websocket.send_json({"type": "partial", "text": text})

    try:
        transcript = await stt.transcribe_stream(chunks(), on_ready=ready, on_partial=partial)
        finalization_latency = perf_counter() - finish_received_at if finish_received_at is not None else 0.0
        await websocket.send_json({"type": "final", "text": transcript, "finalization_latency": finalization_latency})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        secrets = [getattr(getattr(provider_snapshot, kind, None), "api_key", "") for kind in ("stt", "llm", "tts")]
        safe_detail = _safe_provider_detail(exc, *secrets)
        logging.error("streaming STT failed: %s", safe_detail)
        try:
            await websocket.send_json({"type": "error", "detail": safe_detail})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
