"""阶段 4.1 Provider Profile 的本地存储与请求级快照。"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import DATA_DIR, PROVIDER_PROFILES_FILE
from .models import (
    LlmProviderProfile,
    ProviderProfilesState,
    SttProviderProfile,
    TtsProviderProfile,
)

ProviderKind = Literal["stt", "llm", "tts"]


@dataclass(frozen=True)
class ProviderSnapshot:
    stt: SttProviderProfile
    llm: LlmProviderProfile
    tts: TtsProviderProfile


def load_provider_profiles(path: Path | None = None) -> ProviderProfilesState:
    target = path or PROVIDER_PROFILES_FILE
    if not target.exists():
        return ProviderProfilesState()
    try:
        return ProviderProfilesState.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ProviderProfilesState()


def save_provider_profiles(state: ProviderProfilesState, path: Path | None = None) -> None:
    target = path or PROVIDER_PROFILES_FILE
    DATA_DIR.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _collection_name(kind: ProviderKind) -> str:
    return f"{kind}_profiles"


def _active_name(kind: ProviderKind) -> str:
    return f"active_{kind}_profile_id"


def _profile_model(kind: ProviderKind):
    return {"stt": SttProviderProfile, "llm": LlmProviderProfile, "tts": TtsProviderProfile}[kind]


def upsert_provider_profile(kind: ProviderKind, value: dict, path: Path | None = None) -> ProviderProfilesState:
    state = load_provider_profiles(path)
    collection = getattr(state, _collection_name(kind))
    profile_id = str(value.get("id") or "").strip()
    if not profile_id:
        raise ValueError("Provider Profile id 不能为空")
    existing = next((item for item in collection if item.id == profile_id), None)
    incoming = dict(value)
    # 页面永不回读 Key；保存时留空代表保留已有 Key。新 Profile 留空则确实为空。
    if existing is not None and not str(incoming.get("api_key") or ""):
        incoming["api_key"] = existing.api_key
    profile = _profile_model(kind).model_validate(incoming)
    index = next((index for index, item in enumerate(collection) if item.id == profile.id), None)
    if index is None:
        collection.append(profile)
    else:
        collection[index] = profile
    active_name = _active_name(kind)
    if not getattr(state, active_name):
        setattr(state, active_name, profile.id)
    save_provider_profiles(state, path)
    return state


def delete_provider_profile(kind: ProviderKind, profile_id: str, path: Path | None = None) -> ProviderProfilesState:
    state = load_provider_profiles(path)
    collection = getattr(state, _collection_name(kind))
    collection[:] = [item for item in collection if item.id != profile_id]
    active_name = _active_name(kind)
    if getattr(state, active_name) == profile_id:
        setattr(state, active_name, collection[0].id if collection else None)
    save_provider_profiles(state, path)
    return state


def set_active_provider_profile(kind: ProviderKind, profile_id: str, path: Path | None = None) -> ProviderProfilesState:
    state = load_provider_profiles(path)
    collection = getattr(state, _collection_name(kind))
    if not any(item.id == profile_id for item in collection):
        raise KeyError(f"{kind.upper()} Provider Profile 不存在：{profile_id}")
    setattr(state, _active_name(kind), profile_id)
    save_provider_profiles(state, path)
    return state


def get_profile(kind: ProviderKind, profile_id: str, path: Path | None = None):
    state = load_provider_profiles(path)
    profile = next((item for item in getattr(state, _collection_name(kind)) if item.id == profile_id), None)
    if profile is None:
        raise KeyError(f"{kind.upper()} Provider Profile 不存在：{profile_id}")
    return profile.model_copy(deep=True)


def public_provider_profiles(state: ProviderProfilesState | None = None) -> dict:
    state = state or load_provider_profiles()
    data = state.model_dump()
    for kind in ("stt", "llm", "tts"):
        for profile in data[f"{kind}_profiles"]:
            profile["api_key_set"] = bool(profile.get("api_key"))
            profile["api_key"] = ""
    return data


def freeze_active_provider_snapshot(path: Path | None = None) -> ProviderSnapshot:
    state = load_provider_profiles(path)
    selected = {}
    for kind in ("stt", "llm", "tts"):
        profile_id = getattr(state, _active_name(kind))
        collection = getattr(state, _collection_name(kind))
        profile = next((item for item in collection if item.id == profile_id), None)
        if profile is None:
            raise ValueError(f"尚未选择 {kind.upper()} Provider Profile，请先在页面保存并选择")
        selected[kind] = profile.model_copy(deep=True)
    return ProviderSnapshot(**selected)


def provider_snapshot_public(snapshot: ProviderSnapshot) -> dict:
    return {
        "stt": {"id": snapshot.stt.id, "name": snapshot.stt.name, "provider_type": snapshot.stt.provider_type},
        "llm": {"id": snapshot.llm.id, "name": snapshot.llm.name, "provider_type": snapshot.llm.provider_type, "model": snapshot.llm.model},
        "tts": {"id": snapshot.tts.id, "name": snapshot.tts.name, "provider_type": snapshot.tts.provider_type, "voice_type": snapshot.tts.voice_type},
    }
