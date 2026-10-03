from app.config import APP_VERSION
from app.models import RuntimeSettings, SettingsResponse
from app.prompting.lorebook_store import load_lorebooks
from app.providers.profiles import public_provider_profiles
from app.settings.store import load_runtime_settings, save_runtime_settings
from app.memory.vector_store import public_vector_memory
from app.prompting.preset_store import load_prompt_presets
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/settings", response_model=SettingsResponse)
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


@router.put("/api/runtime-settings", response_model=RuntimeSettings)
async def update_runtime_settings(value: RuntimeSettings):
    return save_runtime_settings(value)
