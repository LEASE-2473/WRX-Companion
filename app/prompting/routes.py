from fastapi import HTTPException
from app.models import Lorebook, LorebookActiveUpdate, PromptPreset, PromptPresetActiveUpdate
from app.prompting.lorebook_store import copy_lorebook, create_lorebook, delete_lorebook, get_lorebook, import_lorebook, load_lorebooks, preview_lorebook_import, set_active_lorebook, upsert_lorebook
from app.prompting.preset_store import copy_prompt_preset, create_prompt_preset, delete_prompt_preset, get_prompt_preset, import_prompt_preset, load_prompt_presets, preview_prompt_preset_import, restore_default_prompt_preset, set_active_prompt_preset, upsert_prompt_preset
from app.chat import store as companion_store
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/prompt-presets")
async def get_prompt_presets():
    return load_prompt_presets()


@router.post("/api/prompt-presets/new")
async def new_prompt_preset(value: dict | None = None):
    state, preset = create_prompt_preset((value or {}).get("name", "新 Preset"))
    state.active_preset_id = preset.id
    return set_active_prompt_preset(preset.id)


@router.post("/api/prompt-presets/import/preview")
async def preview_preset_import(value: dict):
    try:
        return preview_prompt_preset_import(value.get("data"), value.get("marker_mappings"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/prompt-presets/import")
async def commit_preset_import(value: dict):
    try:
        state, preset, report = import_prompt_preset(value.get("data"), value.get("marker_mappings"))
        return {"state": state, "preset": preset, "report": report, "saved": True}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/prompt-presets/restore-default")
async def restore_prompt_preset():
    return restore_default_prompt_preset()


@router.put("/api/prompt-presets/active/select")
async def activate_prompt_preset(value: PromptPresetActiveUpdate):
    try:
        return set_active_prompt_preset(value.preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/prompt-presets/{preset_id}/copy")
async def duplicate_prompt_preset(preset_id: str):
    try:
        state, preset = copy_prompt_preset(preset_id)
        state = set_active_prompt_preset(preset.id)
        return state
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/prompt-presets/{preset_id}/export")
async def export_prompt_preset(preset_id: str):
    try:
        return get_prompt_preset(preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/prompt-presets/{preset_id}")
async def save_prompt_preset(preset_id: str, value: PromptPreset):
    if value.id != preset_id:
        value = value.model_copy(update={"id": preset_id})
    try:
        return upsert_prompt_preset(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/prompt-presets/{preset_id}")
async def remove_prompt_preset(preset_id: str):
    if any(char.preset_id == preset_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该预设已绑定角色，请先解除角色绑定")
    try:
        return delete_prompt_preset(preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/lorebooks")
async def get_lorebooks():
    return load_lorebooks()


@router.post("/api/lorebooks/new")
async def new_lorebook(value: dict | None = None):
    state, _ = create_lorebook((value or {}).get("name", "新 Lorebook"))
    return state


@router.post("/api/lorebooks/import/preview")
async def preview_worldbook_import(value: dict):
    try:
        return preview_lorebook_import(value.get("data"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/lorebooks/import")
async def commit_worldbook_import(value: dict):
    try:
        state, book, report = import_lorebook(value.get("data"))
        return {"state": state, "lorebook": book, "report": report, "saved": True}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/api/lorebooks/active/select")
async def activate_lorebook(value: LorebookActiveUpdate):
    try:
        return set_active_lorebook(value.lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/lorebooks/{lorebook_id}/copy")
async def duplicate_lorebook(lorebook_id: str):
    try:
        state, _ = copy_lorebook(lorebook_id)
        return state
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/lorebooks/{lorebook_id}/export")
async def export_lorebook(lorebook_id: str):
    try:
        return get_lorebook(lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/lorebooks/{lorebook_id}")
async def save_lorebook(lorebook_id: str, value: Lorebook):
    if value.id != lorebook_id:
        value = value.model_copy(update={"id": lorebook_id})
    try:
        return upsert_lorebook(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/api/lorebooks/{lorebook_id}")
async def remove_lorebook(lorebook_id: str):
    if any(char.lorebook_id == lorebook_id for char in companion_store.list_characters()):
        raise HTTPException(status_code=409, detail="该世界书已绑定角色，请先解除角色绑定")
    try:
        return delete_lorebook(lorebook_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
