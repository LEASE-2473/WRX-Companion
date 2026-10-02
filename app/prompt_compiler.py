"""阶段 4 的唯一纯 Prompt 编译入口。

本模块不读取文件、环境变量或 Provider，也不修改输入对象。调用方必须在请求
开始时传入已经冻结的 Preset、Lorebook、历史层数和消息快照。
"""

from dataclasses import dataclass
import math
import re
from typing import Any

from .models import (
    ChatMessage,
    Lorebook,
    LorebookEntry,
    MarkerIdentifier,
    PromptEntry,
    PromptPreset,
)

MARKERS: tuple[MarkerIdentifier, ...] = (
    "worldInfoBefore",
    "charDefinitions",
    "worldInfoAfter",
    "userDefinitions",
    "chatHistory",
)
ROLE_ORDER = {"user": 0, "assistant": 1, "system": 2}


@dataclass(frozen=True)
class PromptCompileResult:
    messages: list[ChatMessage]
    trace: dict[str, Any]
    prompt_token_estimate: int


@dataclass(frozen=True)
class _Injection:
    source: str
    source_id: str
    role: str
    content: str
    depth: int
    order: int
    sequence: int


_TOKEN_PIECES = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")
_PROMPT_MACRO = re.compile(r"\{\{\s*(user|char|char_status|char_status_rules|current_time)\s*\}\}", re.IGNORECASE)
_PROMPT_MACRO_VALUES = {"user": "用户", "char": "当前角色"}


def estimate_text_tokens(text: str) -> int:
    """模型 tokenizer 不可知时使用的轻量 Unicode 估算；结果必须标为估算。"""
    total = 0
    for piece in _TOKEN_PIECES.findall(text):
        if len(piece) == 1 and "\u3400" <= piece <= "\u9fff":
            total += 1
        elif piece.isascii() and (piece[0].isalnum() or piece[0] == "_"):
            total += max(1, math.ceil(len(piece) / 4))
        else:
            total += 1
    return total


def estimate_prompt_tokens(messages: list[ChatMessage]) -> int:
    """估算完整 Chat Completion messages，包含消息/Role 的轻量结构开销。"""
    return 2 + sum(
        4 + estimate_text_tokens(message.role) + estimate_text_tokens(message.content)
        for message in messages
    )


def _expand_prompt_macros(text: str, values=None) -> tuple[str, dict[str, int]]:
    expansions: dict[str, int] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        expansions[name] = expansions.get(name, 0) + 1
        return (values or _PROMPT_MACRO_VALUES).get(name, '')

    return _PROMPT_MACRO.sub(replace, text), expansions


def _activation(entry: LorebookEntry, scan_messages: list[ChatMessage]) -> tuple[bool, str]:
    if not entry.enabled:
        return False, "disabled"
    if not entry.content.strip():
        return False, "empty_content"
    if entry.constant:
        return True, "constant"
    keys = [key.strip() for key in entry.keys if key.strip()]
    if not keys:
        return False, "no_constant_or_keys"
    selected = scan_messages[-entry.scan_depth:] if entry.scan_depth > 0 else []
    haystack = "\n".join(message.content for message in selected).casefold()
    matched = next((key for key in keys if key.casefold() in haystack), None)
    return (True, f"keyword:{matched}") if matched else (False, "keyword_not_matched")


def _marker_for(entry: LorebookEntry) -> MarkerIdentifier:
    if entry.outlet:
        return entry.outlet
    if entry.category == "char":
        return "charDefinitions"
    if entry.category == "user":
        return "userDefinitions"
    return "worldInfoBefore" if entry.position == "before_char" else "worldInfoAfter"


def _inject_history(
    base: list[ChatMessage], injections: list[_Injection]
) -> tuple[list[ChatMessage], list[dict[str, Any]]]:
    buckets: dict[int, list[_Injection]] = {}
    for injection in injections:
        boundary = max(0, len(base) - injection.depth)
        buckets.setdefault(boundary, []).append(injection)

    result: list[ChatMessage] = []
    trace: list[dict[str, Any]] = []
    for boundary in range(len(base) + 1):
        ordered = sorted(
            buckets.get(boundary, []),
            key=lambda item: (ROLE_ORDER[item.role], item.order, item.sequence),
        )
        for item in ordered:
            final_index = len(result)
            result.append(ChatMessage(role=item.role, content=item.content))
            trace.append({
                "source": item.source,
                "source_id": item.source_id,
                "requested_depth": item.depth,
                "actual_history_boundary": boundary,
                "actual_message_index": final_index,
                "role": item.role,
                "order": item.order,
            })
        if boundary < len(base):
            result.append(base[boundary])
    return result, trace


def compile_prompt(
    preset: PromptPreset,
    lorebook: Lorebook,
    history_depth: int,
    history: list[ChatMessage],
    current_user_message: str,
    vector_memories: list[dict[str, Any]] | None = None,
    character_name: str = "当前角色",
    user_name: str = "用户",
    marker_contents: dict[str, str] | None = None,
    current_user_suffix: str = "",
    current_images: list[str] | None = None,
    char_status: str = "",
    char_status_rules: str = "",
    current_time: str = "",
) -> PromptCompileResult:
    """编译最终 OpenAI-compatible messages，并返回同源 Trace。"""
    if history_depth < 0:
        raise ValueError("history_depth must be non-negative")

    clean_history = [
        # 历史只发送文字；本轮附件由 current_images 单独传入。
        ChatMessage(role=message.role, content=message.content)
        for message in history
        if message.role in {"user", "assistant"}
    ]
    selected_history = clean_history[-history_depth:] if history_depth else []
    # 本轮元数据只附加到当前输入，不参与世界书关键词激活。
    current_content = current_user_message
    current_time = current_time or current_user_suffix
    chat_messages = selected_history + [ChatMessage(role="user", content=current_content, images=current_images or [])]
    current_message = chat_messages[-1]
    macro_values = {'char': character_name, 'user': user_name, 'char_status': char_status, 'char_status_rules': char_status_rules, 'current_time': current_time}
    scan_messages = clean_history + [ChatMessage(role="user", content=current_user_message)]

    activation_trace: list[dict[str, Any]] = []
    marker_entries: dict[str, list[tuple[int, LorebookEntry]]] = {name: [] for name in MARKERS}
    injections: list[_Injection] = []
    macro_expansions: dict[str, dict[str, int]] = {}
    sequence = 0
    for index, entry in enumerate(lorebook.entries):
        active, reason = _activation(entry, scan_messages)
        destination = "at_depth" if entry.position == "at_depth" else _marker_for(entry)
        activation_trace.append({
            "id": entry.id,
            "title": entry.title,
            "active": active,
            "reason": reason,
            "destination": destination,
        })
        if not active:
            continue
        content, expansions = _expand_prompt_macros(entry.content.strip(), macro_values)
        if expansions:
            macro_expansions[f"lorebook:{entry.id}"] = expansions
        compiled_entry = entry.model_copy(update={"content": content})
        if entry.position == "at_depth":
            injections.append(_Injection("lorebook", entry.id, entry.role, content, entry.depth, entry.order, sequence))
            sequence += 1
        else:
            marker_entries[destination].append((index, compiled_entry))

    recalled = vector_memories or []
    if recalled:
        memory_content = "[向量记忆召回｜仅作为相关背景参考]\n" + "\n\n".join(
            f"[{index}] {item.get('content', '').strip()}"
            for index, item in enumerate(recalled, 1)
            if str(item.get("content", "")).strip()
        )
        if memory_content.strip() != "[向量记忆召回｜仅作为相关背景参考]":
            # depth=1 表示插在当前 user 之前，保持召回内容为独立 system 消息。
            injections.append(_Injection("vector_memory", "retrieved", "system", memory_content, 1, -1000, sequence))
            sequence += 1

    definitions = {item.identifier: item for item in preset.prompts}
    prompt_order_trace: list[dict[str, Any]] = []
    disabled: list[dict[str, str]] = []
    relative_parts: list[tuple[str, list[ChatMessage]]] = []
    expanded_markers: set[str] = set()

    for order_index, order_item in enumerate(preset.prompt_order):
        prompt = definitions.get(order_item.identifier)
        if prompt is None:
            prompt_order_trace.append({"identifier": order_item.identifier, "enabled": False, "reason": "missing_definition"})
            disabled.append({"identifier": order_item.identifier, "reason": "missing_definition"})
            continue
        enabled = bool(order_item.enabled and prompt.enabled)
        prompt_order_trace.append({"identifier": prompt.identifier, "enabled": enabled, "marker": prompt.marker, "order_index": order_index})
        if not enabled:
            disabled.append({"identifier": prompt.identifier, "reason": "disabled"})
            continue
        if prompt.marker:
            if prompt.identifier not in MARKERS:
                disabled.append({"identifier": prompt.identifier, "reason": "unknown_marker"})
                continue
            if prompt.identifier in expanded_markers:
                disabled.append({"identifier": prompt.identifier, "reason": "duplicate_marker"})
                continue
            expanded_markers.add(prompt.identifier)
            if prompt.identifier == "chatHistory":
                relative_parts.append((prompt.identifier, chat_messages))
            else:
                entries = sorted(marker_entries[prompt.identifier], key=lambda pair: (pair[1].order, pair[0]))
                native = (marker_contents or {}).get(prompt.identifier, "")
                relative_parts.append((prompt.identifier, ([ChatMessage(role="system", content=native)] if native else []) + [ChatMessage(role=entry.role, content=entry.content.strip()) for _, entry in entries]))
            continue
        if prompt.injection_position == "in_chat":
            if prompt.content.strip():
                content, expansions = _expand_prompt_macros(prompt.content.strip(), macro_values)
                if expansions:
                    macro_expansions[prompt.identifier] = expansions
                injections.append(_Injection("preset", prompt.identifier, prompt.role, content, prompt.injection_depth, prompt.injection_order, sequence))
                sequence += 1
            else:
                disabled.append({"identifier": prompt.identifier, "reason": "empty_content"})
            continue
        if prompt.content.strip():
            content, expansions = _expand_prompt_macros(prompt.content.strip(), macro_values)
            if expansions:
                macro_expansions[prompt.identifier] = expansions
            relative_parts.append((prompt.identifier, [ChatMessage(role=prompt.role, content=content)]))
        else:
            disabled.append({"identifier": prompt.identifier, "reason": "empty_content"})

    marker_trace: dict[str, Any] = {}
    # 只有实际启用且参与编译的宏才能替代默认注入。
    used_macros = {name for expansions in macro_expansions.values() for name in expansions}
    if 'chatHistory' in expanded_markers:
        if char_status_rules and 'char_status_rules' not in used_macros:
            index = next(i for i, part in enumerate(relative_parts) if part[0] == 'chatHistory')
            relative_parts.insert(index, ('char_status_rules', [ChatMessage(role='system', content=char_status_rules)]))
        dynamic_parts = []
        if char_status and 'char_status' not in used_macros:
            dynamic_parts.append(char_status)
        if current_time and 'current_time' not in used_macros:
            dynamic_parts.append(current_time)
        if dynamic_parts:
            injections.append(_Injection('runtime', 'char_status_context', 'system', '\n\n'.join(dynamic_parts), 1, 100, sequence))
    for marker in MARKERS:
        marker_trace[marker] = {
            "native_content_included": marker in expanded_markers and bool((marker_contents or {}).get(marker)),
            "enabled": marker in expanded_markers,
            "expanded_entry_ids": [entry.id for _, entry in sorted(marker_entries[marker], key=lambda pair: (pair[1].order, pair[0]))],
        }

    final_messages: list[ChatMessage] = []
    injection_trace: list[dict[str, Any]] = []
    chat_history_seen = False
    for identifier, messages in relative_parts:
        if identifier == "chatHistory":
            chat_history_seen = True
            injected, local_trace = _inject_history(messages, injections)
            offset = len(final_messages)
            for item in local_trace:
                item["actual_message_index"] += offset
            injection_trace.extend(local_trace)
            final_messages.extend(injected)
        else:
            final_messages.extend(messages)
    if injections and not chat_history_seen:
        disabled.extend({"identifier": item.source_id, "reason": "chatHistory_marker_disabled"} for item in injections)

    # 本轮 user 永远最后；保留其他条目的角色与相互顺序。
    if chat_history_seen:
        old = list(final_messages)
        near_ids = {id(old[item['actual_message_index']]) for item in injection_trace if item['requested_depth'] <= 1}
        near_messages = [message for message in old if id(message) in near_ids]
        final_messages = [message for message in old if message is not current_message and id(message) not in near_ids] + near_messages + [current_message]
        new_indices = {id(message): i for i, message in enumerate(final_messages)}
        for item in injection_trace:
            item['actual_message_index'] = new_indices[id(old[item['actual_message_index']])]

    sent_lore_ids = {
        item["source_id"] for item in injection_trace if item["source"] == "lorebook"
    }
    for marker in expanded_markers:
        sent_lore_ids.update(marker_trace[marker]["expanded_entry_ids"])
    for item in activation_trace:
        item["sent"] = item["id"] in sent_lore_ids

    prompt_token_estimate = estimate_prompt_tokens(final_messages)
    trace = {
        "schema_version": 1,
        "preset": {"id": preset.id, "name": preset.name},
        "lorebook": {"id": lorebook.id, "name": lorebook.name},
        "prompt_order": prompt_order_trace,
        "macro_expansions": macro_expansions,
        "markers": marker_trace,
        "lorebook_activation": activation_trace,
        "vector_memory": {
            "retrieved_count": len(recalled),
            "results": [
                {
                    "library_id": item.get("library_id"),
                    "library_name": item.get("library_name"),
                    "chunk_id": item.get("chunk_id"),
                    "score": item.get("score"),
                    "vector_score": item.get("vector_score"),
                    "rerank_score": item.get("rerank_score"),
                    "rerank_status": item.get("rerank_status"),
                    "rerank_error": item.get("rerank_error"),
                    "metadata": item.get("metadata", {}),
                }
                for item in recalled
            ],
        },
        "in_chat": injection_trace,
        "history": {
            "requested_layers": history_depth,
            "available_layers": len(clean_history),
            "used_layers": len(selected_history),
            "current_user_included": "chatHistory" in expanded_markers,
        },
        "disabled_or_unsent": disabled,
        "final_messages": [message.model_dump() for message in final_messages],
        "prompt_tokens": {
            "value": prompt_token_estimate,
            "source": "estimate",
            "method": "wrx_unicode_heuristic_v1",
        },
    }
    return PromptCompileResult(
        messages=final_messages,
        trace=trace,
        prompt_token_estimate=prompt_token_estimate,
    )
