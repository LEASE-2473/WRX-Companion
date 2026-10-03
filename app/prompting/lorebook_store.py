"""WRX Lorebook v1 的持久化、CRUD 与 SillyTavern 核心子集导入。"""

from __future__ import annotations

import os
import re
from app.common.identity import new_id, valid_id
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.config import WRX_LOREBOOKS_FILE
from app.models import Lorebook, LorebookEntry, LorebooksState
from app.prompting.compiler import MARKERS


VALID_CATEGORIES = {"char", "user", "world", "mechanism", "other"}
VALID_POSITIONS = {"before_char", "after_char", "at_depth"}
VALID_ROLES = {"system", "user", "assistant"}
ST_POSITION_MAP = {0: "before_char", 1: "after_char", 4: "at_depth"}
ST_ROLE_MAP = {0: "system", 1: "user", 2: "assistant"}
REGEX_KEY = re.compile(r"^/.+/[a-z]*$", re.IGNORECASE)
ST_MACRO = re.compile(r"\{\{[^{}]+\}\}")
SUPPORTED_LOREBOOK_MACROS = {"user", "char"}
ST_ENTRY_FIELDS = {
    "id", "uid", "title", "comment", "content", "constant", "key", "keys",
    "keysecondary", "secondary_keys", "enabled", "disable", "order", "insertion_order",
    "position", "depth", "role", "scanDepth", "scan_depth", "category", "extensions",
    "selective", "selectiveLogic", "probability", "useProbability", "vectorized",
    "excludeRecursion", "preventRecursion", "delayUntilRecursion", "group", "groupOverride",
    "groupWeight", "caseSensitive", "matchWholeWords", "useGroupScoring", "automationId",
    "sticky", "cooldown", "delay", "triggers", "ignoreBudget", "outletName", "addMemo",
    "displayIndex", "matchPersonaDescription", "matchCharacterDescription",
    "matchCharacterPersonality", "matchCharacterDepthPrompt", "matchScenario", "matchCreatorNotes",
}
ST_EXTENSION_FIELDS = {
    "position", "role", "depth", "scan_depth", "category", "probability", "useProbability",
    "vectorized", "exclude_recursion", "prevent_recursion", "delay_until_recursion",
    "group", "group_override", "group_weight", "case_sensitive", "match_whole_words",
    "use_group_scoring", "automation_id", "sticky", "cooldown", "delay", "triggers",
    "ignore_budget", "outlet_name", "display_index", "match_persona_description",
    "match_character_description", "match_character_personality", "match_character_depth_prompt",
    "match_scenario", "match_creator_notes",
}


def default_lorebook() -> Lorebook:
    return Lorebook(id="wrx-empty-lorebook", name="WRX 空世界书")


def default_lorebooks_state() -> LorebooksState:
    book = default_lorebook()
    return LorebooksState(lorebooks=[book], active_lorebook_id=book.id)


def _path(path: Path | None = None) -> Path:
    return path or WRX_LOREBOOKS_FILE


def _validate_lorebook(book: Lorebook) -> Lorebook:
    book = book.model_copy(deep=True)
    book.id = book.id.strip()
    book.name = book.name.strip()
    if not book.id:
        raise ValueError("Lorebook ID 不能为空")
    if not book.name:
        raise ValueError("Lorebook 名称不能为空")
    ids = [entry.id.strip() for entry in book.entries]
    if any(not entry_id for entry_id in ids):
        raise ValueError("Lorebook 条目 ID 不能为空")
    if len(ids) != len(set(ids)):
        raise ValueError("同一 Lorebook 内的条目 ID 必须唯一")
    for entry, entry_id in zip(book.entries, ids):
        entry.id = entry_id
        entry.title = entry.title.strip() or entry_id
        entry.keys = [key.strip() for key in entry.keys if key.strip()]
        entry.comment = entry.comment.strip()
        if entry.position == "at_depth":
            entry.outlet = None
    return book


def load_lorebooks(path: Path | None = None) -> LorebooksState:
    target = _path(path)
    if not target.exists():
        return default_lorebooks_state()
    try:
        state = LorebooksState.model_validate_json(target.read_text(encoding="utf-8"))
        state.lorebooks = [_validate_lorebook(book) for book in state.lorebooks]
        if not state.lorebooks:
            return default_lorebooks_state()
        if state.active_lorebook_id not in {book.id for book in state.lorebooks}:
            state.active_lorebook_id = state.lorebooks[0].id
        return state
    except (OSError, ValueError):
        return default_lorebooks_state()


def save_lorebooks(state: LorebooksState, path: Path | None = None) -> LorebooksState:
    target = _path(path)
    state = state.model_copy(deep=True)
    state.lorebooks = [_validate_lorebook(book) for book in state.lorebooks]
    if not state.lorebooks:
        raise ValueError("至少需要保留一个 Lorebook")
    if state.active_lorebook_id not in {book.id for book in state.lorebooks}:
        state.active_lorebook_id = state.lorebooks[0].id
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return state


def get_lorebook(lorebook_id: str, path: Path | None = None) -> Lorebook:
    state = load_lorebooks(path)
    book = next((item for item in state.lorebooks if item.id == lorebook_id), None)
    if book is None:
        raise KeyError(f"Lorebook 不存在：{lorebook_id}")
    return book.model_copy(deep=True)


def freeze_active_lorebook(path: Path | None = None) -> Lorebook:
    state = load_lorebooks(path)
    book = next((item for item in state.lorebooks if item.id == state.active_lorebook_id), state.lorebooks[0])
    return book.model_copy(deep=True)


def upsert_lorebook(book: Lorebook, path: Path | None = None) -> LorebooksState:
    state = load_lorebooks(path)
    book = _validate_lorebook(book)
    index = next((index for index, item in enumerate(state.lorebooks) if item.id == book.id), None)
    if index is None:
        state.lorebooks.append(book)
    else:
        state.lorebooks[index] = book
    if not state.active_lorebook_id:
        state.active_lorebook_id = book.id
    return save_lorebooks(state, path)


def create_lorebook(name: str = "新 Lorebook", path: Path | None = None) -> tuple[LorebooksState, Lorebook]:
    book = Lorebook(id=new_id(lambda value: any(b.id == value for b in load_lorebooks(path).lorebooks)), name=name.strip() or "新 Lorebook")
    state = upsert_lorebook(book, path)
    state.active_lorebook_id = book.id
    state = save_lorebooks(state, path)
    return state, book


def copy_lorebook(lorebook_id: str, path: Path | None = None) -> tuple[LorebooksState, Lorebook]:
    book = get_lorebook(lorebook_id, path)
    book.id = new_id(lambda value: any(b.id == value for b in load_lorebooks(path).lorebooks))
    book.name = f"{book.name} 副本"
    state = upsert_lorebook(book, path)
    state.active_lorebook_id = book.id
    state = save_lorebooks(state, path)
    return state, book


def delete_lorebook(lorebook_id: str, path: Path | None = None) -> LorebooksState:
    state = load_lorebooks(path)
    if len(state.lorebooks) <= 1:
        raise ValueError("至少需要保留一个 Lorebook")
    remaining = [book for book in state.lorebooks if book.id != lorebook_id]
    if len(remaining) == len(state.lorebooks):
        raise KeyError(f"Lorebook 不存在：{lorebook_id}")
    state.lorebooks = remaining
    if state.active_lorebook_id == lorebook_id:
        state.active_lorebook_id = remaining[0].id
    return save_lorebooks(state, path)


def set_active_lorebook(lorebook_id: str, path: Path | None = None) -> LorebooksState:
    state = load_lorebooks(path)
    if lorebook_id not in {book.id for book in state.lorebooks}:
        raise KeyError(f"Lorebook 不存在：{lorebook_id}")
    state.active_lorebook_id = lorebook_id
    return save_lorebooks(state, path)


def _unknown_fields(value: dict[str, Any], known: set[str]) -> dict[str, Any]:
    raw = deepcopy(value.get("raw_fields") or {})
    raw.update({key: deepcopy(item) for key, item in value.items() if key not in known})
    return raw


def _as_keys(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]
    return []


def _nested(source: dict[str, Any], name: str, default: Any = None) -> Any:
    extensions = source.get("extensions") if isinstance(source.get("extensions"), dict) else {}
    return extensions.get(name, source.get(name, default))


def _unsupported(report: dict[str, Any], path: str, reason: str) -> None:
    report["unsupported_fields"].append({"path": path, "reason": reason})


def _converted(report: dict[str, Any], path: str, action: str) -> None:
    report["compatibility_conversions"].append({"path": path, "action": action})


def _report_content_macros(report: dict[str, Any], path: str, content: str) -> None:
    macros = [match[2:-2].strip().lower() for match in ST_MACRO.findall(content)]
    supported = sorted(set(macros) & SUPPORTED_LOREBOOK_MACROS)
    unsupported = sorted(set(macros) - SUPPORTED_LOREBOOK_MACROS)
    if supported:
        _converted(
            report, path,
            "运行时展开常见宏：" + ", ".join(f"{{{{{name}}}}}" for name in supported),
        )
    if unsupported:
        _unsupported(
            report, path,
            "以下 SillyTavern 宏当前不展开、按字面保留："
            + ", ".join(f"{{{{{name}}}}}" for name in unsupported),
        )


def _entry_destination(entry: LorebookEntry) -> str:
    if entry.position == "at_depth":
        return "at_depth"
    if entry.outlet:
        return entry.outlet
    if entry.category == "char":
        return "charDefinitions"
    if entry.category == "user":
        return "userDefinitions"
    return "worldInfoBefore" if entry.position == "before_char" else "worldInfoAfter"


def _normalize_st_entry(
    source: dict[str, Any],
    source_key: str,
    index: int,
    report: dict[str, Any],
    default_scan_depth: int = 20,
) -> LorebookEntry:
    path = f"entries.{source_key}"
    raw = {"sillytavern": deepcopy(source)}
    report["unknown_fields"].extend(f"{path}.{key}" for key in source if key not in ST_ENTRY_FIELDS)
    extensions = source.get("extensions") if isinstance(source.get("extensions"), dict) else {}
    report["unknown_fields"].extend(f"{path}.extensions.{key}" for key in extensions if key not in ST_EXTENSION_FIELDS)
    raw_id = source.get("id", source.get("uid", source_key))
    entry_id = new_id()
    if "id" not in source and "uid" in source:
        _converted(report, f"{path}.uid", f"转换为 WRX id={entry_id!r}")
    keys = _as_keys(source.get("keys", source.get("key", [])))
    if "keys" not in source and "key" in source:
        _converted(report, f"{path}.key", "转换为 WRX keys[]")
    regex_keys = [key for key in keys if REGEX_KEY.match(key)]
    if regex_keys:
        keys = [key for key in keys if key not in regex_keys]
        _unsupported(report, f"{path}.key", "正则关键词第一版暂不支持；已从运行时 keys 移除并保留原始字段")

    enabled = bool(source.get("enabled", not bool(source.get("disable", False))))
    if "enabled" not in source and "disable" in source:
        _converted(report, f"{path}.disable", f"反转为 WRX enabled={enabled}")
    disable_reasons: list[str] = []
    ext_position = _nested(source, "position", source.get("position", 1))
    if isinstance(ext_position, str) and ext_position in VALID_POSITIONS:
        position = ext_position
    else:
        try:
            numeric_position = int(ext_position)
        except (TypeError, ValueError):
            numeric_position = -1
        position = ST_POSITION_MAP.get(numeric_position, "after_char")
        if numeric_position not in ST_POSITION_MAP:
            _unsupported(report, f"{path}.position", f"SillyTavern position={ext_position!r} 不属于 Before/After/@Depth 核心子集；条目已禁用")
            disable_reasons.append("unsupported_position")
        else:
            _converted(report, f"{path}.position", f"{ext_position!r} → {position}")

    raw_role = _nested(source, "role", "system")
    if isinstance(raw_role, str) and raw_role in VALID_ROLES:
        role = raw_role
    else:
        try:
            role = ST_ROLE_MAP[int(raw_role)]
            _converted(report, f"{path}.role", f"{raw_role!r} → {role}")
        except (KeyError, TypeError, ValueError):
            role = "system"
            report["warnings"].append(f"{path}.role={raw_role!r} 无法映射，已回退 system")

    secondary = _as_keys(source.get("keysecondary", source.get("secondary_keys", [])))
    selective = bool(source.get("selective", False))
    if secondary:
        _unsupported(report, f"{path}.keysecondary/selective", "复杂 AND/NOT/secondary keys 第一版暂不支持；为避免错误激活，条目已禁用")
        disable_reasons.append("unsupported_selective_logic")
    elif selective:
        _converted(report, f"{path}.selective", "未提供二级关键词；按主关键词 OR 激活")
    probability = source.get("probability", _nested(source, "probability", 100))
    use_probability = bool(source.get("useProbability", _nested(source, "useProbability", True)))
    if use_probability and probability not in (None, 100, 100.0):
        _unsupported(report, f"{path}.probability", "概率触发第一版暂不支持；为避免把概率事件改成必然事件，条目已禁用")
        disable_reasons.append("unsupported_probability")
    if bool(source.get("delayUntilRecursion", _nested(source, "delay_until_recursion", False))):
        _unsupported(report, f"{path}.delayUntilRecursion", "仅递归时激活第一版暂不支持；条目已禁用")
        disable_reasons.append("unsupported_recursion_only")
    if source.get("group", _nested(source, "group", "")) or bool(source.get("groupOverride", _nested(source, "group_override", False))):
        _unsupported(report, f"{path}.group", "分组互斥第一版暂不支持；为避免同时发送互斥条目，条目已禁用")
        disable_reasons.append("unsupported_group")
    triggers = source.get("triggers", _nested(source, "triggers", []))
    if triggers:
        _unsupported(report, f"{path}.triggers", "按生成类型过滤第一版暂不支持；为避免错误时机激活，条目已禁用")
        disable_reasons.append("unsupported_generation_filter")
    if bool(source.get("vectorized", _nested(source, "vectorized", False))):
        _unsupported(report, f"{path}.vectorized", "向量激活第一版暂不支持；仅保留可映射的常驻或普通关键词语义")
    if bool(source.get("caseSensitive", _nested(source, "case_sensitive", False))):
        _unsupported(report, f"{path}.caseSensitive", "大小写敏感匹配第一版暂不支持；为避免宽松误触发，条目已禁用")
        disable_reasons.append("unsupported_case_sensitive")
    if bool(source.get("matchWholeWords", _nested(source, "match_whole_words", False))):
        _unsupported(report, f"{path}.matchWholeWords", "整词匹配第一版暂不支持；为避免子串误触发，条目已禁用")
        disable_reasons.append("unsupported_whole_words")
    match_context_fields = (
        ("matchPersonaDescription", "match_persona_description"),
        ("matchCharacterDescription", "match_character_description"),
        ("matchCharacterPersonality", "match_character_personality"),
        ("matchCharacterDepthPrompt", "match_character_depth_prompt"),
        ("matchScenario", "match_scenario"),
        ("matchCreatorNotes", "match_creator_notes"),
    )
    if any(bool(source.get(camel, _nested(source, snake, False))) for camel, snake in match_context_fields):
        _unsupported(report, f"{path}.match*", "额外角色/Persona/场景扫描源第一版暂不支持；为避免宽松误触发，条目已禁用")
        disable_reasons.append("unsupported_scan_source")
    for field, nested_name in (
        ("excludeRecursion", "exclude_recursion"), ("preventRecursion", "prevent_recursion"),
        ("sticky", "sticky"), ("cooldown", "cooldown"), ("delay", "delay"),
    ):
        value = source.get(field, _nested(source, nested_name, None))
        if value not in (None, False, 0, ""):
            _unsupported(report, f"{path}.{field}", "递归或定时效果第一版不执行；原始字段已保留")

    category = str(source.get("category", _nested(source, "category", "other")))
    if category not in VALID_CATEGORIES:
        category = "other"
        report["warnings"].append(f"{path}.category 无法映射，已使用 other")
    outlet = None
    outlet_name = str(source.get("outletName", _nested(source, "outlet_name", "")) or "").strip()
    if outlet_name in VALID_CATEGORIES:
        category = outlet_name
        _converted(report, f"{path}.outletName", f"映射为 WRX category={category}")
    elif outlet_name in MARKERS and outlet_name != "chatHistory":
        outlet = outlet_name
        _converted(report, f"{path}.outletName", f"映射为 WRX outlet={outlet}")
    elif outlet_name:
        _unsupported(report, f"{path}.outletName", "命名出口无法映射到 WRX 分类或 Marker；已保留原始字段并使用默认出口")
    scan_depth_value = source.get("scan_depth", _nested(source, "scan_depth", source.get("scanDepth", default_scan_depth)))
    try:
        scan_depth = max(0, int(scan_depth_value if scan_depth_value is not None else 20))
    except (TypeError, ValueError):
        scan_depth = 20
        report["warnings"].append(f"{path}.scanDepth 无法映射，已使用 20")
    try:
        depth = max(0, int(source.get("depth", _nested(source, "depth", 0)) or 0))
    except (TypeError, ValueError):
        depth = 0
        report["warnings"].append(f"{path}.depth 无法映射，已使用 0")
    try:
        order = int(source.get("order", source.get("insertion_order", 100)) or 0)
    except (TypeError, ValueError):
        order = 100
        report["warnings"].append(f"{path}.order 无法映射，已使用 100")

    title = str(source.get("title") or source.get("comment") or (keys[0] if keys else f"Entry {index + 1}"))
    if "title" not in source and source.get("comment"):
        _converted(report, f"{path}.comment", "复制为 WRX title；原 comment 仍保留")
    content = str(source.get("content") or "")
    _report_content_macros(report, f"{path}.content", content)
    raw["import_disable_reasons"] = disable_reasons
    return LorebookEntry(
        id=entry_id, title=title, enabled=enabled and not disable_reasons, category=category,
        content=content, constant=bool(source.get("constant", False)),
        keys=keys, scan_depth=scan_depth, position=position, depth=depth, role=role,
        order=order, comment=str(source.get("comment") or ""), outlet=outlet, raw_fields=raw,
    )


def normalize_imported_lorebook(
    data: dict[str, Any], *, existing_ids: set[str] | None = None,
) -> tuple[Lorebook, dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("导入文件顶层必须是 JSON 对象")
    is_wrx = data.get("schema_version") == 1 and isinstance(data.get("entries"), list)
    report: dict[str, Any] = {
        "format": "wrx_v1" if is_wrx else "sillytavern_core",
        "unknown_fields": [], "unsupported_fields": [],
        "compatibility_conversions": [], "entry_mappings": [], "summary": {}, "warnings": [],
    }
    if is_wrx:
        top_known = {"schema_version", "id", "name", "entries", "raw_fields"}
        raw_fields = _unknown_fields(data, top_known)
        report["unknown_fields"].extend(key for key in data if key not in top_known)
        entries = []
        entry_known = {
            "id", "title", "enabled", "category", "content", "constant", "keys", "scan_depth",
            "position", "depth", "role", "order", "comment", "outlet", "raw_fields",
        }
        for index, source in enumerate(data["entries"]):
            if not isinstance(source, dict):
                raw_fields.setdefault("unparsed_entries", []).append(deepcopy(source))
                report["warnings"].append(f"entries[{index}] 不是对象，已保留但不执行")
                continue
            raw = _unknown_fields(source, entry_known)
            report["unknown_fields"].extend(f"entries[{index}].{key}" for key in source if key not in entry_known)
            value = {**source, "raw_fields": raw}
            _report_content_macros(report, f"entries[{index}].content", str(source.get("content") or ""))
            entries.append(LorebookEntry.model_validate(value))
    else:
        top_known = {"name", "entries", "raw_fields", "originalData", "scan_depth", "scanDepth"}
        raw_fields = _unknown_fields(data, top_known)
        raw_fields["sillytavern_top"] = {key: deepcopy(value) for key, value in data.items() if key != "entries"}
        report["unknown_fields"].extend(key for key in data if key not in top_known)
        top_scan_depth = data.get("scan_depth", data.get("scanDepth", 20))
        try:
            default_scan_depth = max(0, int(top_scan_depth if top_scan_depth is not None else 20))
            if "scan_depth" in data or "scanDepth" in data:
                source_name = "scan_depth" if "scan_depth" in data else "scanDepth"
                _converted(report, source_name, f"作为未单独声明条目的默认 scan_depth={default_scan_depth}")
        except (TypeError, ValueError):
            default_scan_depth = 20
            report["warnings"].append(f"scan_depth={top_scan_depth!r} 无法映射，已使用 20")
        source_entries = data.get("entries")
        if isinstance(source_entries, dict):
            pairs = list(source_entries.items())
        elif isinstance(source_entries, list):
            pairs = [(str(index), value) for index, value in enumerate(source_entries)]
        else:
            raise ValueError("SillyTavern Lorebook 缺少 entries 对象或数组")
        entries = []
        for index, (source_key, source) in enumerate(pairs):
            if not isinstance(source, dict):
                raw_fields.setdefault("unparsed_entries", {})[source_key] = deepcopy(source)
                report["warnings"].append(f"entries.{source_key} 不是对象，已保留但不执行")
                continue
            entries.append(_normalize_st_entry(source, source_key, index, report, default_scan_depth))

    seen: set[str] = set()
    for entry in entries:
        if not valid_id(entry.id): entry.id = new_id(lambda value: value in seen)
        if entry.id in seen:
            original = entry.id
            entry.id = new_id(lambda value: value in seen)
            report["warnings"].append(f"条目 ID {original} 重复，已改为 {entry.id}")
        seen.add(entry.id)
    book_id = new_id(lambda value: value in (existing_ids or set()))
    if existing_ids and book_id in existing_ids:
        original = book_id
        book_id = new_id(lambda value: value in (existing_ids or set()))
        report["warnings"].append(f"Lorebook ID {original} 已存在，导入副本使用 {book_id}")
    book = _validate_lorebook(Lorebook(
        schema_version=1, id=book_id,
        name=str(data.get("name") or "导入的 Lorebook").strip() or "导入的 Lorebook",
        entries=entries, raw_fields=raw_fields,
    ))
    report["entry_mappings"] = [
        {
            "id": entry.id,
            "title": entry.title,
            "enabled": entry.enabled,
            "category": entry.category,
            "constant": entry.constant,
            "keys": entry.keys,
            "scan_depth": entry.scan_depth,
            "position": entry.position,
            "depth": entry.depth,
            "role": entry.role,
            "order": entry.order,
            "outlet": entry.outlet,
            "destination": _entry_destination(entry),
            "disable_reasons": list(entry.raw_fields.get("import_disable_reasons") or []),
        }
        for entry in book.entries
    ]
    enabled_count = sum(entry.enabled for entry in book.entries)
    report["summary"] = {
        "total_entries": len(book.entries),
        "enabled_entries": enabled_count,
        "disabled_entries": len(book.entries) - enabled_count,
    }
    return book, report


def preview_lorebook_import(data: dict[str, Any]) -> dict[str, Any]:
    book, report = normalize_imported_lorebook(data)
    return {"lorebook": book.model_dump(), "report": report, "saved": False}


def import_lorebook(
    data: dict[str, Any], path: Path | None = None,
) -> tuple[LorebooksState, Lorebook, dict[str, Any]]:
    state = load_lorebooks(path)
    book, report = normalize_imported_lorebook(data, existing_ids={item.id for item in state.lorebooks})
    state.lorebooks.append(book)
    state.active_lorebook_id = book.id
    state = save_lorebooks(state, path)
    return state, book, report
