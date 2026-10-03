from app.providers.diagnostics import safe_provider_detail as _safe_provider_detail
import base64
from fastapi import HTTPException
from app.models import ProviderActiveUpdate
from app.voice.pipeline import describe_exception
from app.providers.profiles import delete_provider_profile, get_profile, public_provider_profiles, set_active_provider_profile, upsert_provider_profile
from app.providers.client import fetch_llm_models, test_llm_stream, test_stt_real_request, test_tts_real_request
from app.memory.vector_store import get_embeddings, get_rerank_scores
from app.chat import store as companion_store
from fastapi import APIRouter

router = APIRouter()

def _provider_kind(kind: str) -> str:
    if kind not in {"stt", "llm", "tts"}:
        raise HTTPException(status_code=404, detail="Unknown provider kind")
    return kind




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


@router.get("/api/provider-profiles")
async def get_provider_profiles():
    return public_provider_profiles()


@router.put("/api/provider-profiles/{kind}/{profile_id}")
async def save_provider_profile(kind: str, profile_id: str, value: dict):
    kind = _provider_kind(kind)
    value = {**value, "id": profile_id}
    try:
        return public_provider_profiles(upsert_provider_profile(kind, value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/provider-profiles/{kind}/{profile_id}")
async def remove_provider_profile(kind: str, profile_id: str):
    if kind == 'llm':
        from app.character.state import config as emotion_settings
        from app.memory.role import settings as memory_settings
        mem=memory_settings()
        if profile_id in [emotion_settings().llm_profile_id,emotion_settings().contact_llm_profile_id] or any(p.llm_profile_id==profile_id for p in mem.presets.values()) or profile_id in [mem.embedding_profile_id,mem.rerank_profile_id]:
            raise HTTPException(status_code=409,detail='该Profile被角色状态或角色记忆使用，请先解除绑定')
    if kind == "llm" and any(char.llm_profile_id == profile_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该 LLM 已绑定角色，请先解除角色绑定")
    if kind == "tts" and any(char.tts_profile_id == profile_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该 TTS 已绑定角色，请先解除角色绑定")
    return public_provider_profiles(delete_provider_profile(_provider_kind(kind), profile_id))


@router.put("/api/provider-profiles/active/{kind}/select")
async def activate_provider_profile(kind: str, value: ProviderActiveUpdate):
    try:
        return public_provider_profiles(set_active_provider_profile(_provider_kind(kind), value.profile_id))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/provider-profiles/llm/{profile_id}/models")
@router.post("/api/provider-profiles/llm/{profile_id}/connection")
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


@router.post("/api/provider-profiles/llm/{profile_id}/test")
async def test_llm_provider(profile_id: str):
    try:
        try:
            profile = get_profile("llm", profile_id)
        except KeyError:
            return _configuration_failure("该 Profile 尚未保存或已被删除，请保存当前配置后重试")
        problem = _configuration_problem("llm", profile)
        if problem:
            return _configuration_failure(problem)
        if profile.purpose in {'embedding','rerank'}:
            from app.memory.vector_store import get_embeddings, get_rerank_scores
            from app.models import VectorMemoryConfig
            config = VectorMemoryConfig(api_url=profile.base_url, api_key=profile.api_key, model=profile.model, rerank_url=profile.base_url.rstrip('/') if profile.base_url.rstrip('/').endswith('/rerank') else profile.base_url.rstrip('/')+'/rerank', rerank_key=profile.api_key, rerank_model=profile.model)
            if profile.purpose == 'embedding': await get_embeddings(['连接测试'], config)
            else: await get_rerank_scores('测试',['连接测试'],config)
            return {"ok":True,"stages":{"real_request":{"status":"passed","detail":profile.purpose+" 请求成功"}}}
        delta = await test_llm_stream(profile)
        return {"ok": True, "sample": delta[:80], "stages": {"configuration": {"status": "passed"}, "network_auth": {"status": "passed"}, "real_request": {"status": "passed", "detail": "已收到流式正文增量"}}}
    except Exception as exc:
        secret = getattr(locals().get("profile"), "api_key", "")
        return _probe_failure(_safe_provider_detail(exc, secret))


@router.post("/api/provider-profiles/stt/{profile_id}/test")
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


@router.post("/api/provider-profiles/tts/{profile_id}/test")
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
