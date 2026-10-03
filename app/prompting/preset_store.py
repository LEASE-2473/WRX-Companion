"""WRX Prompt Preset v1 的持久化、CRUD 与导入规范化。"""

from __future__ import annotations

import os
import re
from app.common.identity import new_id
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import WRX_PROMPT_PRESETS_FILE
from app.models import PromptEntry, PromptOrderEntry, PromptPreset, PromptPresetsState
from app.prompting.compiler import MARKERS


DEFAULT_MAIN_PROMPT = """你是一个用于实时语音聊天的助手。

请遵守：
- 像真人聊天一样自然、直接、简洁。
- 保持上下文连续，记住用户刚才说过的内容，不要无故重复自我介绍。
- 不确定时直接说明不确定，不要编造事实。
- 除非用户要求，不要把回答写成客服话术或总结报告。"""

DEFAULT_VOICE_PROMPT = """回答必须适合直接朗读：
- 只输出自然语言，不使用 Markdown、代码块、XML、JSON、动作描写或情绪标签。
- 默认一到三段短句；用标点自然表达停顿和语气。
- 避免连续长句、复杂数字、网址和不适合朗读的符号。"""

NATIVE_MARKERS = set(MARKERS)
CHARACTER_MARKERS = {
    "charDescription", "charPersonality", "characterDescription",
    "characterPersonality", "scenario", "characterExamples",
}
PERSONA_MARKERS = {"persona", "personaDescription", "userPersona", "userDescription"}
PREFILL_FIELD_NAMES = {
    "assistant_prefill", "assistantPrefill", "start_reply_with", "startReplyWith",
    "openai_start_reply_with", "continue_prefill",
}
ST_INJECTION_POSITION_MAP = {0: "relative", 1: "in_chat", "0": "relative", "1": "in_chat"}
ST_FLAT_GENERATION_FIELDS = {
    "temperature", "frequency_penalty", "presence_penalty", "top_p", "top_k",
    "top_a", "min_p", "repetition_penalty", "openai_max_context",
    "openai_max_tokens", "seed", "n",
}
ST_MACRO = re.compile(r"\{\{[^{}]+\}\}")
SUPPORTED_PROMPT_MACROS = {"user", "char", "char_status", "char_status_rules", "current_time"}


def default_wrx_preset() -> PromptPreset:
    prompts = [
        PromptEntry(identifier="main", name="Main Prompt", content=DEFAULT_MAIN_PROMPT),
        PromptEntry(identifier="worldInfoBefore", name="World Info Before", marker=True),
        PromptEntry(identifier="charDefinitions", name="Character Definitions", marker=True),
        PromptEntry(identifier="worldInfoAfter", name="World Info After", marker=True),
        PromptEntry(identifier="userDefinitions", name="User Definitions", marker=True),
        PromptEntry(identifier="chatHistory", name="Chat History", marker=True),
        PromptEntry(identifier="voiceOutput", name="Voice Output", content=DEFAULT_VOICE_PROMPT),
    ]
    return PromptPreset(
        id="wrx-minimal-default",
        name="WRX 最小默认预设",
        prompts=prompts,
        prompt_order=[PromptOrderEntry(identifier=item.identifier) for item in prompts],
    )


def default_prompt_presets_state() -> PromptPresetsState:
    preset = default_wrx_preset()
    return PromptPresetsState(presets=[preset], active_preset_id=preset.id)


def _path(path: Path | None = None) -> Path:
    return path or WRX_PROMPT_PRESETS_FILE


def _validate_preset(preset: PromptPreset) -> PromptPreset:
    preset = preset.model_copy(deep=True)
    preset.id = preset.id.strip()
    preset.name = preset.name.strip()
    if not preset.id:
        raise ValueError("Preset ID 不能为空")
    if not preset.name:
        raise ValueError("Preset 名称不能为空")

    identifiers = [item.identifier.strip() for item in preset.prompts]
    if any(not identifier for identifier in identifiers):
        raise ValueError("Prompt 条目的 identifier 不能为空")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("同一 Preset 内的 Prompt identifier 必须唯一")
    for item, identifier in zip(preset.prompts, identifiers):
        item.identifier = identifier
        item.name = item.name.strip() or identifier
        if item.marker and identifier in NATIVE_MARKERS:
            item.content = ""
            item.injection_position = "relative"

    order_ids = [item.identifier.strip() for item in preset.prompt_order]
    if any(not identifier for identifier in order_ids):
        raise ValueError("prompt_order identifier 不能为空")
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("prompt_order 不能重复引用同一 identifier")
    for item, identifier in zip(preset.prompt_order, order_ids):
        item.identifier = identifier
    for identifier in identifiers:
        if identifier not in order_ids:
            preset.prompt_order.append(PromptOrderEntry(identifier=identifier))
    return preset


def load_prompt_presets(path: Path | None = None) -> PromptPresetsState:
    target = _path(path)
    if not target.exists():
        return default_prompt_presets_state()
    try:
        state = PromptPresetsState.model_validate_json(target.read_text(encoding="utf-8"))
        state.presets = [_validate_preset(item) for item in state.presets]
        if not state.presets:
            return default_prompt_presets_state()
        if state.active_preset_id not in {item.id for item in state.presets}:
            state.active_preset_id = state.presets[0].id
        return state
    except (OSError, ValueError):
        return default_prompt_presets_state()


def save_prompt_presets(state: PromptPresetsState, path: Path | None = None) -> PromptPresetsState:
    target = _path(path)
    state = state.model_copy(deep=True)
    state.presets = [_validate_preset(item) for item in state.presets]
    if not state.presets:
        raise ValueError("至少需要保留一个 Preset")
    if state.active_preset_id not in {item.id for item in state.presets}:
        state.active_preset_id = state.presets[0].id
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return state


def get_prompt_preset(preset_id: str, path: Path | None = None) -> PromptPreset:
    state = load_prompt_presets(path)
    preset = next((item for item in state.presets if item.id == preset_id), None)
    if preset is None:
        raise KeyError(f"Preset 不存在：{preset_id}")
    return preset.model_copy(deep=True)


def freeze_active_prompt_preset(path: Path | None = None) -> PromptPreset:
    state = load_prompt_presets(path)
    preset = next((item for item in state.presets if item.id == state.active_preset_id), state.presets[0])
    return preset.model_copy(deep=True)


def upsert_prompt_preset(preset: PromptPreset, path: Path | None = None) -> PromptPresetsState:
    state = load_prompt_presets(path)
    preset = _validate_preset(preset)
    index = next((index for index, item in enumerate(state.presets) if item.id == preset.id), None)
    if index is None:
        state.presets.append(preset)
    else:
        state.presets[index] = preset
    if not state.active_preset_id:
        state.active_preset_id = preset.id
    return save_prompt_presets(state, path)


def create_prompt_preset(name: str = "新 Preset", path: Path | None = None) -> tuple[PromptPresetsState, PromptPreset]:
    preset = default_wrx_preset().model_copy(deep=True)
    preset.id = new_id(lambda value: any(p.id == value for p in load_prompt_presets(path).presets))
    preset.name = name.strip() or "新 Preset"
    state = upsert_prompt_preset(preset, path)
    return state, preset


def copy_prompt_preset(preset_id: str, path: Path | None = None) -> tuple[PromptPresetsState, PromptPreset]:
    preset = get_prompt_preset(preset_id, path)
    preset.id = new_id(lambda value: any(p.id == value for p in load_prompt_presets(path).presets))
    preset.name = f"{preset.name} 副本"
    state = upsert_prompt_preset(preset, path)
    return state, preset


def delete_prompt_preset(preset_id: str, path: Path | None = None) -> PromptPresetsState:
    state = load_prompt_presets(path)
    if len(state.presets) <= 1:
        raise ValueError("至少需要保留一个 Preset")
    remaining = [item for item in state.presets if item.id != preset_id]
    if len(remaining) == len(state.presets):
        raise KeyError(f"Preset 不存在：{preset_id}")
    state.presets = remaining
    if state.active_preset_id == preset_id:
        state.active_preset_id = remaining[0].id
    return save_prompt_presets(state, path)


def set_active_prompt_preset(preset_id: str, path: Path | None = None) -> PromptPresetsState:
    state = load_prompt_presets(path)
    if preset_id not in {item.id for item in state.presets}:
        raise KeyError(f"Preset 不存在：{preset_id}")
    state.active_preset_id = preset_id
    return save_prompt_presets(state, path)


def restore_default_prompt_preset(path: Path | None = None) -> PromptPresetsState:
    state = load_prompt_presets(path)
    default = default_wrx_preset()
    index = next((index for index, item in enumerate(state.presets) if item.id == default.id), None)
    if index is None:
        state.presets.insert(0, default)
    else:
        state.presets[index] = default
    state.active_preset_id = default.id
    return save_prompt_presets(state, path)


def _unknown_fields(value: dict[str, Any], known: set[str]) -> dict[str, Any]:
    raw = deepcopy(value.get("raw_fields") or {})
    raw.update({key: deepcopy(item) for key, item in value.items() if key not in known})
    return raw


def _prompt_order_items(value: Any, report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(value, list):
        report["warnings"].append("prompt_order 不是数组，已按 prompts[] 顺序补全")
        report["compatibility_conversions"].append({
            "path": "prompt_order",
            "action": "缺失或非数组；按 prompts[] 顺序生成 WRX prompt_order",
        })
        return [], {"unparsed_prompt_order": deepcopy(value)}
    if value and isinstance(value[0], dict) and isinstance(value[0].get("order"), list):
        selected_index = next(
            (index for index, group in enumerate(value) if group.get("character_id") == 100001),
            0,
        )
        selected = value[selected_index]
        if len(value) > 1:
            report["warnings"].append(
                f"检测到多组 SillyTavern prompt_order；已选择第 {selected_index + 1} 组"
                + ("（character_id=100001）" if selected.get("character_id") == 100001 else "")
            )
        wrapper = {key: deepcopy(item) for key, item in selected.items() if key != "order"}
        report["unknown_fields"].extend(f"prompt_order[{selected_index}].{key}" for key in wrapper)
        if len(value) > 1:
            wrapper["additional_groups"] = deepcopy(
                [group for index, group in enumerate(value) if index != selected_index]
            )
        report["compatibility_conversions"].append({
            "path": "prompt_order",
            "action": f"使用第 {selected_index + 1} 组生成 WRX prompt_order",
        })
        return selected["order"], {"sillytavern_prompt_order_wrapper": wrapper}
    return value, {}


def _prefill_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in PREFILL_FIELD_NAMES:
                paths.append(path)
            paths.extend(_prefill_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_prefill_paths(item, f"{prefix}[{index}]"))
    return paths


def normalize_imported_preset(
    data: dict[str, Any], marker_mappings: dict[str, str] | None = None, *,
    existing_ids: set[str] | None = None, require_mappings: bool = False,
) -> tuple[PromptPreset, dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("导入文件顶层必须是 JSON 对象")
    marker_mappings = marker_mappings or {}
    report: dict[str, Any] = {
        "format": "wrx_v1" if data.get("schema_version") == 1 else "sillytavern_core",
        "unknown_fields": [], "unsupported_fields": [], "pending_mappings": [],
        "mapped_markers": [], "compatibility_conversions": [], "warnings": [],
    }
    top_known = {"schema_version", "id", "name", "prompts", "prompt_order", "generation_parameters", "raw_fields"}
    is_wrx = report["format"] == "wrx_v1"
    converted_generation_parameters = deepcopy(data.get("generation_parameters") or {})
    converted_top_fields = set()
    if not is_wrx:
        for field in ST_FLAT_GENERATION_FIELDS:
            if field in data:
                converted_generation_parameters[field] = deepcopy(data[field])
                converted_top_fields.add(field)
                report["compatibility_conversions"].append({
                    "path": field,
                    "action": (
                        f"移入 generation_parameters.{field}；"
                        "运行时仅执行 OpenAI-compatible 安全白名单参数，其余参数保留但不发送"
                    ),
                })
    top_raw = _unknown_fields(data, top_known | converted_top_fields)
    report["unknown_fields"].extend(
        key for key in data if key not in top_known and key not in converted_top_fields
    )
    report["unsupported_fields"].extend(
        {"path": path, "reason": "assistant 预填充 / Start Reply With 第一版暂不支持；原始字段已保留"}
        for path in _prefill_paths(data)
    )

    source_prompts = data.get("prompts")
    if not isinstance(source_prompts, list):
        raise ValueError("导入文件缺少 prompts[]")
    source_order, order_wrapper_raw = _prompt_order_items(data.get("prompt_order"), report)
    top_raw.update(order_wrapper_raw)
    source_to_target: dict[str, str] = {}
    used_marker_targets: set[str] = set()
    prompts: list[PromptEntry] = []
    reserved_marker_targets = {
        str(source.get("identifier"))
        for source in source_prompts
        if isinstance(source, dict) and source.get("marker") and source.get("identifier") in NATIVE_MARKERS
    }
    suggested_marker_targets = set(reserved_marker_targets)
    prompt_known = {
        "identifier", "name", "enabled", "role", "content", "injection_position",
        "injection_depth", "injection_order", "marker", "raw_fields",
    }
    for index, source in enumerate(source_prompts):
        if not isinstance(source, dict):
            report["warnings"].append(f"prompts[{index}] 不是对象，已跳过并保留在 Preset raw_fields")
            top_raw.setdefault("unparsed_prompts", []).append(deepcopy(source))
            continue
        identifier = str(source.get("identifier") or f"imported-{index}").strip()
        is_marker = bool(source.get("marker")) or identifier in NATIVE_MARKERS or identifier in CHARACTER_MARKERS or identifier in PERSONA_MARKERS
        target = identifier
        enabled = bool(source.get("enabled", True))
        if is_marker:
            suggested = "charDefinitions" if identifier in CHARACTER_MARKERS else "userDefinitions" if identifier in PERSONA_MARKERS else None
            if suggested:
                if suggested in suggested_marker_targets:
                    suggested = "__skip__"
                else:
                    suggested_marker_targets.add(suggested)
            if identifier in NATIVE_MARKERS:
                target = identifier
            elif identifier in marker_mappings:
                mapped = marker_mappings[identifier]
                if mapped == "__skip__":
                    enabled = False
                    report["mapped_markers"].append({"source": identifier, "target": None, "status": "明确跳过；保留为禁用待映射 Marker"})
                elif mapped in NATIVE_MARKERS:
                    target = mapped
                    report["mapped_markers"].append({"source": identifier, "target": target, "status": "mapped"})
                else:
                    raise ValueError(f"无效 Marker 映射：{identifier} → {mapped}")
            else:
                report["pending_mappings"].append({"identifier": identifier, "name": str(source.get("name") or identifier), "suggested_target": suggested})
                enabled = False
            if target in NATIVE_MARKERS:
                if target in used_marker_targets:
                    raise ValueError(f"一次导入中运行时 Marker 目标不能重复：{target}")
                used_marker_targets.add(target)
        source_to_target[identifier] = target
        role = source.get("role", "system")
        if role not in {"system", "user", "assistant"}:
            report["warnings"].append(f"{identifier}: 未知 role={role!r}，已回退为 system")
            role = "system"
        source_position = source.get("injection_position", "relative")
        is_st_numeric_position = not isinstance(source_position, bool) and source_position in ST_INJECTION_POSITION_MAP
        position = ST_INJECTION_POSITION_MAP.get(source_position, source_position) if is_st_numeric_position else source_position
        if is_st_numeric_position:
            report["compatibility_conversions"].append({
                "path": f"prompts[{index}].injection_position",
                "action": f"{source_position!r} → {position}",
            })
        if position not in {"relative", "in_chat"}:
            report["warnings"].append(f"{identifier}: 未知 injection_position={position!r}，已回退为 relative")
            position = "relative"
        raw = _unknown_fields(source, prompt_known)
        report["unknown_fields"].extend(f"prompts[{index}].{key}" for key in source if key not in prompt_known)
        if is_marker and source.get("content"):
            raw.setdefault("imported_marker_content", deepcopy(source["content"]))
            report["warnings"].append(f"{identifier}: Marker 正文不参与运行时展开，原值已保存在 raw_fields")
        if is_marker and target != identifier:
            raw.setdefault("source_marker_identifier", identifier)
        content = "" if is_marker else str(source.get("content") or "")
        macros = [match[2:-2].strip().lower() for match in ST_MACRO.findall(content)]
        supported_macros = sorted(set(macros) & SUPPORTED_PROMPT_MACROS)
        unsupported_macros = sorted(set(macros) - SUPPORTED_PROMPT_MACROS)
        if supported_macros:
            report["compatibility_conversions"].append({
                "path": f"prompts[{index}].content",
                "action": "运行时展开常见宏：" + ", ".join(f"{{{{{name}}}}}" for name in supported_macros),
            })
        if unsupported_macros:
            report["unsupported_fields"].append({
                "path": f"prompts[{index}].content",
                "reason": "以下 SillyTavern 宏当前不展开、按字面保留："
                + ", ".join(f"{{{{{name}}}}}" for name in unsupported_macros),
            })
        prompts.append(PromptEntry(
            identifier=target, name=str(source.get("name") or identifier), enabled=enabled,
            role=role, content=content,
            injection_position="relative" if is_marker else position,
            injection_depth=max(0, int(source.get("injection_depth") or 0)),
            injection_order=int(source.get("injection_order") or 100), marker=is_marker,
            raw_fields=raw,
        ))

    if require_mappings and report["pending_mappings"]:
        pending = ", ".join(item["identifier"] for item in report["pending_mappings"])
        raise ValueError(f"仍有待手动映射 Marker：{pending}")

    order_known = {"identifier", "enabled", "raw_fields"}
    prompt_order: list[PromptOrderEntry] = []
    for index, source in enumerate(source_order):
        if not isinstance(source, dict) or not source.get("identifier"):
            report["warnings"].append(f"prompt_order[{index}] 无有效 identifier，已跳过")
            continue
        original = str(source["identifier"])
        target = source_to_target.get(original, original)
        raw = _unknown_fields(source, order_known)
        report["unknown_fields"].extend(f"prompt_order[{index}].{key}" for key in source if key not in order_known)
        prompt_order.append(PromptOrderEntry(identifier=target, enabled=bool(source.get("enabled", True)), raw_fields=raw))

    preset_id = new_id(lambda value: value in (existing_ids or set()))
    if existing_ids and preset_id in existing_ids:
        old_id = preset_id
        preset_id = new_id(lambda value: value in (existing_ids or set()))
        report["warnings"].append(f"Preset ID {old_id} 已存在，导入副本使用新 ID {preset_id}")
    preset = _validate_preset(PromptPreset(
        schema_version=1, id=preset_id,
        name=str(data.get("name") or "导入的 Preset").strip() or "导入的 Preset",
        prompts=prompts, prompt_order=prompt_order,
        generation_parameters=converted_generation_parameters, raw_fields=top_raw,
    ))
    return preset, report


def preview_prompt_preset_import(data: dict[str, Any], marker_mappings: dict[str, str] | None = None) -> dict[str, Any]:
    preset, report = normalize_imported_preset(data, marker_mappings)
    return {"preset": preset.model_dump(), "report": report, "saved": False}


def import_prompt_preset(
    data: dict[str, Any], marker_mappings: dict[str, str] | None = None, path: Path | None = None,
) -> tuple[PromptPresetsState, PromptPreset, dict[str, Any]]:
    state = load_prompt_presets(path)
    preset, report = normalize_imported_preset(
        data, marker_mappings, existing_ids={item.id for item in state.presets}, require_mappings=True,
    )
    state.presets.append(preset)
    state.active_preset_id = preset.id
    state = save_prompt_presets(state, path)
    return state, preset, report
