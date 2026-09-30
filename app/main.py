import base64
import asyncio
import json
import logging
import uuid
from time import perf_counter
from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import APP_VERSION
from .models import (
    Lorebook,
    LorebookActiveUpdate,
    ProcessRequest,
    PromptPreset,
    PromptPresetActiveUpdate,
    ProviderActiveUpdate,
    RuntimeSettings,
    SettingsResponse,
)
from .pipeline import describe_exception
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
    public_provider_profiles,
    set_active_provider_profile,
    upsert_provider_profile,
)
from .providers import fetch_llm_models, get_providers, test_llm_stream, test_stt_real_request, test_tts_real_request
from .runtime_settings_store import freeze_runtime_settings, load_runtime_settings, save_runtime_settings
from .vector_memory_store import (
    delete_vector_library,
    freeze_vector_memory,
    fetch_vector_models,
    get_embeddings,
    get_rerank_scores,
    import_vector_library,
    list_vector_chunks,
    preview_vector_import,
    public_vector_memory,
    save_vector_config,
    set_vector_library_enabled,
    vectorize_library,
)
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
from contextlib import asynccontextmanager
from .companion_core import core
from .companion_routes import router as companion_router, stream_job, api_error
from . import companion_store
from .heartbeat import run_scheduler
from .providers import VolcengineStt

@asynccontextmanager
async def lifespan(app):
    companion_store.recover_interrupted()
    scheduler = asyncio.create_task(run_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)
        await core.shutdown()

app = FastAPI(title="WRX Companion", version=APP_VERSION, lifespan=lifespan)
app.include_router(companion_router)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
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
    return SettingsResponse(version=APP_VERSION, mode="real", prompt_presets=load_prompt_presets(), lorebooks=load_lorebooks(), runtime_settings=load_runtime_settings(), provider_profiles=public, provider_info=info, vector_memory=public_vector_memory())

@app.put("/api/runtime-settings", response_model=RuntimeSettings)
async def update_runtime_settings(value: RuntimeSettings):
    return save_runtime_settings(value)

@app.get("/api/vector-memory")
async def get_vector_memory():
    return public_vector_memory()

@app.put("/api/vector-memory/config")
async def update_vector_memory_config(value: dict):
    try:
        return public_vector_memory(save_vector_config(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/vector-memory/test")
async def test_vector_memory_provider():
    state = freeze_vector_memory()
    try:
        vector = (await get_embeddings(["WRX 向量连接测试"], state.config))[0]
        return {"ok": True, "dimensions": len(vector)}
    except Exception as exc:
        return {"ok": False, "detail": _safe_provider_detail(exc, state.config.api_key)}

@app.post("/api/vector-memory/models")
async def vector_memory_models(value: dict):
    state = freeze_vector_memory()
    kind = str(value.get("kind") or "embedding")
    try:
        if kind == "rerank":
            models = await fetch_vector_models(state.config.rerank_url, state.config.rerank_key)
        else:
            models = await fetch_vector_models(state.config.api_url, state.config.api_key)
        return {"ok": True, "models": models}
    except Exception as exc:
        secret = state.config.rerank_key if kind == "rerank" else state.config.api_key
        return {"ok": False, "models": [], "detail": _safe_provider_detail(exc, secret)}

@app.post("/api/vector-memory/rerank/test")
async def test_vector_memory_rerank():
    state = freeze_vector_memory()
    try:
        scores = await get_rerank_scores("test", ["test"], state.config)
        return {"ok": True, "score": scores[0]}
    except Exception as exc:
        return {"ok": False, "detail": _safe_provider_detail(exc, state.config.rerank_key)}

@app.post("/api/vector-memory/import/preview")
async def preview_vector_memory_import(value: dict):
    try:
        return preview_vector_import(str(value.get("text") or ""), str(value.get("filename") or ""), str(value.get("separator") or "---"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/api/vector-memory/import")
async def commit_vector_memory_import(value: dict):
    try:
        state, library = import_vector_library(str(value.get("name") or ""), str(value.get("text") or ""), str(value.get("filename") or ""), str(value.get("separator") or "---"))
        return {"state": public_vector_memory(state), "library": {"id": library.id, "name": library.name, "source_format": library.source_format, "chunk_count": len(library.chunks)}}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.put("/api/vector-memory/libraries/{library_id}/enabled")
async def toggle_vector_library(library_id: str, value: dict):
    try:
        return public_vector_memory(set_vector_library_enabled(library_id, bool(value.get("enabled"))))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/vector-memory/libraries/{library_id}/chunks")
async def get_vector_library_chunks(library_id: str, offset: int = 0, limit: int = 20, query: str = ""):
    try:
        return list_vector_chunks(library_id, offset, limit, query)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.delete("/api/vector-memory/libraries/{library_id}")
async def remove_vector_library(library_id: str):
    try:
        return public_vector_memory(delete_vector_library(library_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/vector-memory/libraries/{library_id}/vectorize")
async def run_vectorization(library_id: str):
    try:
        state, report = await vectorize_library(library_id)
        return {"state": public_vector_memory(state), "report": report}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        state = freeze_vector_memory()
        raise HTTPException(status_code=502, detail=_safe_provider_detail(exc, state.config.api_key)) from exc

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
    if any(char.preset_id == preset_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该预设已绑定角色，请先解除角色绑定")
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
    if any(char.lorebook_id == lorebook_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该世界书已绑定角色，请先解除角色绑定")
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
    if kind == "llm" and any(char.llm_profile_id == profile_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该 LLM 已绑定角色，请先解除角色绑定")
    if kind == "tts" and any(char.tts_profile_id == profile_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该 TTS 已绑定角色，请先解除角色绑定")
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
        try:
            profile = get_profile("llm", profile_id)
        except KeyError:
            return _configuration_failure("该 Profile 尚未保存或已被删除，请保存当前配置后重试", models=True)
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
        try:
            profile = get_profile("llm", profile_id)
        except KeyError:
            return _configuration_failure("该 Profile 尚未保存或已被删除，请保存当前配置后重试")
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
        try:
            profile = get_profile("stt", profile_id)
        except KeyError:
            return _configuration_failure("该 Profile 尚未保存或已被删除，请保存当前配置后重试")
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
        try:
            profile = get_profile("tts", profile_id)
        except KeyError:
            return _configuration_failure("该 Profile 尚未保存或已被删除，请保存当前配置后重试")
        problem = _configuration_problem("tts", profile)
        if problem:
            return _configuration_failure(problem)
        audio = await test_tts_real_request(profile)
        return {"ok": True, "audio_base64": base64.b64encode(audio).decode(), "audio_mime": "audio/wav", "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "real_request": {"status": "passed", "detail": f"真实合成返回 {len(audio)} bytes"}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return _probe_failure(_safe_provider_detail(exc, secret))

@app.post("/api/process/stream")
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
