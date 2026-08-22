"""阶段 4 全局运行设置：原子持久化并为每轮请求提供深拷贝快照。"""

from __future__ import annotations

import os
from pathlib import Path

from .config import WRX_RUNTIME_SETTINGS_FILE
from .models import RuntimeSettings


def _path(path: Path | None = None) -> Path:
    return path or WRX_RUNTIME_SETTINGS_FILE


def load_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    target = _path(path)
    if not target.exists():
        return RuntimeSettings()
    try:
        return RuntimeSettings.model_validate_json(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return RuntimeSettings()


def save_runtime_settings(
    settings: RuntimeSettings, path: Path | None = None,
) -> RuntimeSettings:
    target = _path(path)
    saved = settings.model_copy(deep=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(saved.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return saved


def freeze_runtime_settings(path: Path | None = None) -> RuntimeSettings:
    return load_runtime_settings(path).model_copy(deep=True)
