import base64
import asyncio
import hashlib
import json
import logging
import uuid
from time import perf_counter
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_VERSION
from .conversation_store import create_conversation, list_conversations, save_conversation
from .models import (
    ChatMessage,
    ConversationRecord,
    ConversationUpdate,
    Lorebook,
    LorebookActiveUpdate,
    ProcessRequest,
    PromptPreset,
    PromptPresetActiveUpdate,
    ProviderActiveUpdate,
    RuntimeSettings,
    SettingsResponse,
)
from .pipeline import describe_exception, normalize_voice_reply
from .prompt_compiler import compile_prompt
from .lorebook_store import (
    copy_lorebook,
    create_lorebook,
    delete_lorebook,
    freeze_active_lorebook,
    get_lorebook,
    import_lorebook,
    load_lorebooks,
    preview_lorebook_import,
    set_active_lorebook,
    upsert_lorebook,
)
from .provider_store import (
    delete_provider_profile,
    freeze_active_provider_snapshot,
    get_profile,
    provider_snapshot_public,
    public_provider_profiles,
    set_active_provider_profile,
    upsert_provider_profile,
)
from .providers import ProviderError, fetch_llm_models, get_providers, test_llm_stream, test_stt_real_request, test_tts_real_request, wav_from_pcm
from .runtime_settings_store import freeze_runtime_settings, load_runtime_settings, save_runtime_settings
from .prompt_store import (
    copy_prompt_preset,
    create_prompt_preset,
    delete_prompt_preset,
    freeze_active_prompt_preset,
    get_prompt_preset,
    import_prompt_preset,
    load_prompt_presets,
    preview_prompt_preset_import,
    restore_default_prompt_preset,
    set_active_prompt_preset,
    upsert_prompt_preset,
)

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="WRX Voice Agent", version=APP_VERSION)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
LLM_FAILURE_SPOKEN_TEXT = "对不起老板……我的脑子刚刚卡了一下，你能不能再说一次？"
PROVIDER_ROUND_SNAPSHOTS: dict[str, object] = {}
PROMPT_ROUND_SNAPSHOTS: dict[str, PromptPreset] = {}
LOREBOOK_ROUND_SNAPSHOTS: dict[str, Lorebook] = {}
HISTORY_DEPTH_ROUND_SNAPSHOTS: dict[str, int] = {}

def stash_provider_snapshot(snapshot) -> str:
    snapshot_id = str(uuid.uuid4())
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

def take_tts_segment(buffer: str, final: bool = False) -> tuple[str, str]:
    """取出适合立即交给 TTS 的自然边界，避免逐 token 合成破坏韵律。"""
    if final:
        return buffer, ""
    for index, char in enumerate(buffer):
        if char in "。！？!?；;\n" and index >= 5:
            return buffer[:index + 1], buffer[index + 1:]
    if len(buffer) >= 32:
        boundary = max(buffer.rfind(mark, 12, 33) for mark in "，,、：:")
        if boundary >= 12:
            return buffer[:boundary + 1], buffer[boundary + 1:]
    if len(buffer) >= 48:
        return buffer[:48], buffer[48:]
    return "", buffer
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")

@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    public = public_provider_profiles()
    info = {}
    for kind in ("stt", "llm", "tts"):
        active_id = public.get(f"active_{kind}_profile_id")
        profile = next((item for item in public.get(f"{kind}_profiles", []) if item["id"] == active_id), None)
        info[kind] = profile["name"] if profile else "未选择"
    llm = next((item for item in public.get("llm_profiles", []) if item["id"] == public.get("active_llm_profile_id")), None)
    info["model"] = llm.get("model", "") if llm else ""
    return SettingsResponse(version=APP_VERSION, mode="real", prompt_presets=load_prompt_presets(), lorebooks=load_lorebooks(), runtime_settings=load_runtime_settings(), provider_profiles=public, provider_info=info)

@app.put("/api/runtime-settings", response_model=RuntimeSettings)
async def update_runtime_settings(value: RuntimeSettings):
    return save_runtime_settings(value)

@app.get("/api/prompt-presets")
async def get_prompt_presets():
    return load_prompt_presets()

@app.post("/api/prompt-presets/new")
async def new_prompt_preset(value: dict | None = None):
    state, preset = create_prompt_preset((value or {}).get("name", "新 Preset"))
    state.active_preset_id = preset.id
    return set_active_prompt_preset(preset.id)

@app.post("/api/prompt-presets/import/preview")
async def preview_preset_import(value: dict):
    try:
        return preview_prompt_preset_import(value.get("data"), value.get("marker_mappings"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/prompt-presets/import")
async def commit_preset_import(value: dict):
    try:
        state, preset, report = import_prompt_preset(value.get("data"), value.get("marker_mappings"))
        return {"state": state, "preset": preset, "report": report, "saved": True}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/prompt-presets/restore-default")
async def restore_prompt_preset():
    return restore_default_prompt_preset()

@app.put("/api/prompt-presets/active/select")
async def activate_prompt_preset(value: PromptPresetActiveUpdate):
    try:
        return set_active_prompt_preset(value.preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/prompt-presets/{preset_id}/copy")
async def duplicate_prompt_preset(preset_id: str):
    try:
        state, preset = copy_prompt_preset(preset_id)
        state = set_active_prompt_preset(preset.id)
        return state
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/prompt-presets/{preset_id}/export")
async def export_prompt_preset(preset_id: str):
    try:
        return get_prompt_preset(preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.put("/api/prompt-presets/{preset_id}")
async def save_prompt_preset(preset_id: str, value: PromptPreset):
    if value.id != preset_id:
        value = value.model_copy(update={"id": preset_id})
    try:
        return upsert_prompt_preset(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.delete("/api/prompt-presets/{preset_id}")
async def remove_prompt_preset(preset_id: str):
    try:
        return delete_prompt_preset(preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.get("/api/lorebooks")
async def get_lorebooks():
    return load_lorebooks()

@app.post("/api/lorebooks/new")
async def new_lorebook(value: dict | None = None):
    state, _ = create_lorebook((value or {}).get("name", "新 Lorebook"))
    return state

@app.post("/api/lorebooks/import/preview")
async def preview_worldbook_import(value: dict):
    try:
        return preview_lorebook_import(value.get("data"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/lorebooks/import")
async def commit_worldbook_import(value: dict):
    try:
        state, book, report = import_lorebook(value.get("data"))
        return {"state": state, "lorebook": book, "report": report, "saved": True}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.put("/api/lorebooks/active/select")
async def activate_lorebook(value: LorebookActiveUpdate):
    try:
        return set_active_lorebook(value.lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/lorebooks/{lorebook_id}/copy")
async def duplicate_lorebook(lorebook_id: str):
    try:
        state, _ = copy_lorebook(lorebook_id)
        return state
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/lorebooks/{lorebook_id}/export")
async def export_lorebook(lorebook_id: str):
    try:
        return get_lorebook(lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.put("/api/lorebooks/{lorebook_id}")
async def save_lorebook(lorebook_id: str, value: Lorebook):
    if value.id != lorebook_id:
        value = value.model_copy(update={"id": lorebook_id})
    try:
        return upsert_lorebook(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.delete("/api/lorebooks/{lorebook_id}")
async def remove_lorebook(lorebook_id: str):
    try:
        return delete_lorebook(lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

def _provider_kind(kind: str) -> str:
    if kind not in {"stt", "llm", "tts"}:
        raise HTTPException(status_code=404, detail="Unknown provider kind")
    return kind

def _safe_provider_detail(exc: Exception, *secrets: str) -> str:
    detail = describe_exception(exc)
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    return detail

def _probe_failure(detail: str) -> dict:
    return {
        "ok": False,
        "stages": {
            "configuration": {"status": "passed"},
            "network_auth": {"status": "failed", "detail": detail},
            "real_request": {"status": "not_completed"},
        },
    }

def _configuration_problem(kind: str, profile, *, require_llm_model: bool = True) -> str:
    if kind == "llm":
        required = [("Base URL", profile.base_url), ("API Key", profile.api_key)]
        if require_llm_model:
            required.append(("Model", profile.model))
        missing = [label for label, value in required if not str(value).strip()]
    elif kind == "stt":
        missing = [label for label, value in (("Endpoint", profile.endpoint), ("Stream Endpoint", profile.stream_endpoint), ("Resource ID", profile.resource_id), ("API Key", profile.api_key)) if not str(value).strip()]
    else:
        required = [("Endpoint", profile.endpoint), ("API Key", profile.api_key)]
        if str(profile.endpoint).startswith("wss://"):
            required.extend((("Resource ID", profile.resource_id), ("Voice Type", profile.voice_type)))
        missing = [label for label, value in required if not str(value).strip()]
    return f"缺少配置：{', '.join(missing)}" if missing else ""

def _configuration_failure(detail: str, *, models: bool = False) -> dict:
    stages = {"configuration": {"status": "failed", "detail": detail}, "network_auth": {"status": "not_completed"}}
    stages["models" if models else "real_request"] = {"status": "not_completed"}
    result = {"ok": False, "stages": stages}
    if models:
        result["models"] = []
        result["stages"]["models"] = {"status": "not_completed"}
    return result

@app.get("/api/provider-profiles")
async def get_provider_profiles():
    return public_provider_profiles()

@app.put("/api/provider-profiles/{kind}/{profile_id}")
async def save_provider_profile(kind: str, profile_id: str, value: dict):
    kind = _provider_kind(kind)
    value = {**value, "id": profile_id}
    try:
        return public_provider_profiles(upsert_provider_profile(kind, value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.delete("/api/provider-profiles/{kind}/{profile_id}")
async def remove_provider_profile(kind: str, profile_id: str):
    return public_provider_profiles(delete_provider_profile(_provider_kind(kind), profile_id))

@app.put("/api/provider-profiles/active/{kind}/select")
async def activate_provider_profile(kind: str, value: ProviderActiveUpdate):
    try:
        return public_provider_profiles(set_active_provider_profile(_provider_kind(kind), value.profile_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/provider-profiles/llm/{profile_id}/models")
async def provider_models(profile_id: str):
    try:
        profile = get_profile("llm", profile_id)
        problem = _configuration_problem("llm", profile, require_llm_model=False)
        if problem:
            return _configuration_failure(problem, models=True)
        models = await fetch_llm_models(profile)
        return {"ok": True, "models": models, "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "models": {"status": "passed", "count": len(models)}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return {"ok": False, "models": [], "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "failed", "detail": _safe_provider_detail(exc, secret)}, "models": {"status": "not_completed"}}}

@app.post("/api/provider-profiles/llm/{profile_id}/test")
async def test_llm_provider(profile_id: str):
    try:
        profile = get_profile("llm", profile_id)
        problem = _configuration_problem("llm", profile)
        if problem:
            return _configuration_failure(problem)
        delta = await test_llm_stream(profile)
        return {"ok": True, "sample": delta[:80], "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "real_request": {"status": "passed", "detail": "已收到流式正文增量"}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return _probe_failure(_safe_provider_detail(exc, secret))

@app.post("/api/provider-profiles/stt/{profile_id}/test")
async def test_stt_provider(profile_id: str):
    try:
        profile = get_profile("stt", profile_id)
        problem = _configuration_problem("stt", profile)
        if problem:
            return _configuration_failure(problem)
        transcript = await test_stt_real_request(profile)
        return {"ok": True, "transcript": transcript, "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "real_request": {"status": "passed", "detail": "真实静音 WAV 识别请求已完成"}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return _probe_failure(_safe_provider_detail(exc, secret))

@app.post("/api/provider-profiles/tts/{profile_id}/test")
async def test_tts_provider(profile_id: str):
    try:
        profile = get_profile("tts", profile_id)
        problem = _configuration_problem("tts", profile)
        if problem:
            return _configuration_failure(problem)
        audio = await test_tts_real_request(profile)
        return {"ok": True, "audio_base64": base64.b64encode(audio).decode(), "audio_mime": "audio/wav", "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "real_request": {"status": "passed", "detail": f"真实合成返回 {len(audio)} bytes"}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return _probe_failure(_safe_provider_detail(exc, secret))

@app.get("/api/conversations", response_model=list[ConversationRecord])
async def get_conversations():
    return list_conversations()

@app.post("/api/conversations", response_model=ConversationRecord)
async def new_conversation():
    return create_conversation()

@app.put("/api/conversations/{conversation_id}", response_model=ConversationRecord)
async def update_conversation(conversation_id: str, value: ConversationUpdate):
    saved = save_conversation(conversation_id, value.messages)
    if saved is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return saved

@app.post("/api/process/stream")
async def process_stream(request: ProcessRequest):
    async def events():
        started = perf_counter()
        latency = {"recording": 0.0, "stt": 0.0, "llm": 0.0, "tts": 0.0, "audio_playback_preparation": 0.0, "total": 0.0}
        stage = "setup"
        tts = None
        preset = None
        prompt_tokens_metric = None

        async def emit_failure(detail: str):
            if stage == "llm" and tts is not None and preset is not None:
                try:
                    fallback_audio = await tts.synthesize(LLM_FAILURE_SPOKEN_TEXT, preset)
                    if fallback_audio:
                        payload = {
                            "type": "failure",
                            "detail": detail,
                            "spoken_text": LLM_FAILURE_SPOKEN_TEXT,
                            "audio_base64": base64.b64encode(fallback_audio).decode(),
                            "audio_mime": "audio/wav",
                            "latency": latency,
                            "prompt_tokens": prompt_tokens_metric,
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        return
                except Exception as fallback_exc:
                    detail = f"{detail}；错误提示语音生成也失败：{describe_exception(fallback_exc)}"
            payload = {"type": "error", "detail": detail}
            if prompt_tokens_metric is not None:
                payload["prompt_tokens"] = prompt_tokens_metric
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            audio = base64.b64decode(request.audio_base64) if request.audio_base64 else b""
            transcript = request.transcript.strip()
            if not transcript and len(audio) < 44:
                yield f"data: {json.dumps({'type': 'error', 'detail': 'No speech detected'}, ensure_ascii=False)}\n\n"
                return
            provider_snapshot = take_provider_snapshot(request.provider_snapshot_id)
            active_prompt_preset = take_prompt_snapshot(request.provider_snapshot_id)
            active_lorebook = take_lorebook_snapshot(request.provider_snapshot_id)
            history_depth = take_history_depth_snapshot(request.provider_snapshot_id)
            stt, llm, tts = get_providers(provider_snapshot)
            set_generation_parameters = getattr(llm, "set_generation_parameters", None)
            if callable(set_generation_parameters):
                set_generation_parameters(active_prompt_preset.generation_parameters)
            preset = provider_snapshot.tts
            latency["recording"] = request.recording_duration if transcript else max(0.0, (len(audio) - 44) / (16000 * 2))
            stage = "stt"
            if transcript:
                latency["stt"] = max(0.0, request.stt_latency)
            else:
                yield f"data: {json.dumps({'type': 'state', 'state': 'Transcribing'}, ensure_ascii=False)}\n\n"
                stt_started = perf_counter()
                transcript = await stt.transcribe(audio)
                latency["stt"] = perf_counter() - stt_started
            if not transcript.strip():
                yield f"data: {json.dumps({'type': 'error', 'detail': 'No speech detected'}, ensure_ascii=False)}\n\n"
                return
            yield f"data: {json.dumps({'type': 'transcript', 'text': transcript}, ensure_ascii=False)}\n\n"
            history = [m for m in request.messages if m.role in {'user', 'assistant'}]
            compiled = compile_prompt(active_prompt_preset, active_lorebook, history_depth, history, transcript)
            compiled.trace["generation_parameters"] = getattr(
                llm, "generation_parameter_report", {"applied": {}, "ignored": {}}
            )
            llm_messages = compiled.messages
            prompt_tokens_metric = {
                "value": compiled.prompt_token_estimate,
                "source": "estimate",
                "label": "估算",
            }
            pieces: list[str] = []
            llm_started = perf_counter()
            first_token_latency = None
            yield f"data: {json.dumps({'type': 'state', 'state': 'Thinking'}, ensure_ascii=False)}\n\n"
            stage = "llm"
            audio_pcm = bytearray()
            tts_error = ""
            first_segment_latency = None
            first_audio_latency = None
            streaming_pcm = getattr(tts, "supports_streaming_pcm", lambda _preset: False)(preset)

            if streaming_pcm:
                event_queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
                text_queue: asyncio.Queue[str | None] = asyncio.Queue()
                tts_handoff_at = None

                async def text_stream():
                    while True:
                        item = await text_queue.get()
                        if item is None:
                            break
                        yield item

                async def produce_llm():
                    nonlocal first_token_latency, first_segment_latency, tts_handoff_at
                    buffer = ""
                    try:
                        async for piece in llm.stream_complete(llm_messages):
                            if first_token_latency is None:
                                first_token_latency = perf_counter() - llm_started
                            pieces.append(piece)
                            buffer += piece
                            await event_queue.put(("delta", piece))
                            while True:
                                segment, buffer = take_tts_segment(buffer)
                                if not segment:
                                    break
                                spoken = normalize_voice_reply(segment).strip()
                                if spoken:
                                    if tts_handoff_at is None:
                                        tts_handoff_at = perf_counter()
                                        first_segment_latency = tts_handoff_at - llm_started
                                    await text_queue.put(spoken)
                        tail, _ = take_tts_segment(buffer, final=True)
                        spoken = normalize_voice_reply(tail).strip()
                        if spoken:
                            if tts_handoff_at is None:
                                tts_handoff_at = perf_counter()
                                first_segment_latency = tts_handoff_at - llm_started
                            await text_queue.put(spoken)
                    except Exception as exc:
                        await event_queue.put(("fatal", exc))
                    finally:
                        latency["llm"] = perf_counter() - llm_started
                        await text_queue.put(None)
                        await event_queue.put(("llm_done", None))

                async def produce_tts():
                    nonlocal tts_error, first_audio_latency
                    try:
                        async for chunk in tts.stream_pcm(text_stream(), preset):
                            if first_audio_latency is None:
                                now = perf_counter()
                                first_audio_latency = now - (tts_handoff_at or llm_started)
                                latency["response_to_first_audio"] = request.stt_latency + now - started
                            audio_pcm.extend(chunk)
                            await event_queue.put(("audio", chunk))
                    except Exception as exc:
                        tts_error = describe_exception(exc)
                    finally:
                        latency["tts"] = max(0.0, perf_counter() - (tts_handoff_at or llm_started))
                        await event_queue.put(("tts_done", None))

                llm_task = asyncio.create_task(produce_llm())
                tts_task = asyncio.create_task(produce_tts())
                llm_done = tts_done = False
                try:
                    while not (llm_done and tts_done):
                        kind, value = await event_queue.get()
                        if kind == "delta":
                            yield f"data: {json.dumps({'type': 'delta', 'text': value}, ensure_ascii=False)}\n\n"
                        elif kind == "audio":
                            payload = {'type': 'audio_chunk', 'audio_base64': base64.b64encode(value).decode(), 'sample_rate': 24000}
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        elif kind == "llm_done":
                            llm_done = True
                        elif kind == "tts_done":
                            tts_done = True
                        elif kind == "fatal":
                            raise value
                    await asyncio.gather(llm_task, tts_task)
                finally:
                    for task in (llm_task, tts_task):
                        if not task.done():
                            task.cancel()
            else:
                async for piece in llm.stream_complete(llm_messages):
                    if first_token_latency is None:
                        first_token_latency = perf_counter() - llm_started
                    pieces.append(piece)
                    yield f"data: {json.dumps({'type': 'delta', 'text': piece}, ensure_ascii=False)}\n\n"
                latency["llm"] = perf_counter() - llm_started

            provider_prompt_tokens = getattr(llm, "last_prompt_tokens", None)
            if isinstance(provider_prompt_tokens, int) and not isinstance(provider_prompt_tokens, bool) and provider_prompt_tokens >= 0:
                prompt_tokens_metric = {
                    "value": provider_prompt_tokens,
                    "source": "provider",
                    "label": "Provider 实际",
                }
            compiled.trace["prompt_tokens"] = prompt_tokens_metric

            reply = normalize_voice_reply(''.join(pieces))
            if not reply:
                raise ProviderError("LLM 未返回可朗读正文")
            messages = history + [ChatMessage(role='user', content=transcript), ChatMessage(role='assistant', content=reply)]
            stage = "tts"
            if audio_pcm:
                audio_bytes = wav_from_pcm(bytes(audio_pcm), 24000)
            elif streaming_pcm:
                # 流式 TTS 偶发正常结束但不返回音频。用完整文本新建一次会话兜底；
                # 仍失败时返回明确的 TTS 错误，绝不让前端播放空 WAV。
                yield f"data: {json.dumps({'type': 'state', 'state': 'Generating Voice'}, ensure_ascii=False)}\n\n"
                retry_started = perf_counter()
                try:
                    audio_bytes = await tts.synthesize(reply, preset)
                    if not audio_bytes:
                        raise ProviderError("TTS 未返回音频")
                except Exception as exc:
                    audio_bytes = b""
                    tts_error = describe_exception(exc)
                latency["tts"] += perf_counter() - retry_started
            else:
                yield f"data: {json.dumps({'type': 'state', 'state': 'Generating Voice'}, ensure_ascii=False)}\n\n"
                tts_started = perf_counter()
                try:
                    audio_bytes = await tts.synthesize(reply, preset)
                except Exception as exc:
                    audio_bytes = b""
                    tts_error = describe_exception(exc)
                latency["tts"] = perf_counter() - tts_started
            latency["total"] = request.stt_latency + perf_counter() - started
            if first_token_latency is not None:
                latency["llm_first_token"] = first_token_latency
            if first_segment_latency is not None:
                latency["llm_first_tts_segment"] = first_segment_latency
            if first_audio_latency is not None:
                latency["tts_first_audio"] = first_audio_latency
            debug = {
                "llm_messages": [message.model_dump() for message in llm_messages],
                "llm_raw": ''.join(pieces),
                "normalized_reply": reply,
                "tts_input": reply,
                "prompt_trace": compiled.trace,
                "prompt_tokens": prompt_tokens_metric,
                "provider": provider_snapshot_public(provider_snapshot),
                "prompt_sha256": hashlib.sha256(json.dumps(compiled.trace["final_messages"], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:12],
            }
            if first_token_latency is not None:
                debug["llm_first_token_latency"] = first_token_latency
            if tts_error:
                debug["tts_error"] = tts_error
            if not audio_bytes and not tts_error:
                tts_error = "TTS 未返回音频"
                debug["tts_error"] = tts_error
            payload = {'type': 'complete', 'transcript': transcript, 'reply': reply, 'audio_base64': base64.b64encode(audio_bytes).decode(), 'audio_mime': 'audio/wav', 'audio_streamed': bool(audio_pcm), 'messages': [m.model_dump() for m in messages], 'latency': latency, 'prompt_tokens': prompt_tokens_metric, 'debug': debug, 'error': tts_error}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except ProviderError as exc:
            async for event in emit_failure(str(exc)):
                yield event
        except Exception as exc:
            snapshot = locals().get("provider_snapshot")
            secrets = [getattr(getattr(snapshot, kind, None), "api_key", "") for kind in ("stt", "llm", "tts")]
            safe_detail = _safe_provider_detail(exc, *secrets)
            logging.error("stream pipeline failed: %s", safe_detail)
            async for event in emit_failure(f"处理失败：{safe_detail}"):
                yield event
    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.websocket("/api/stt/stream")
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
