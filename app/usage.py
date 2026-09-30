"""只归一化 Provider 实际返回的用量，未知值始终为 None。"""
from typing import Any
from .models import TokenUsage


def _count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def read_usage(body: Any) -> TokenUsage:
    if not isinstance(body, dict):
        return TokenUsage()
    containers = [body.get(key) for key in ("usage", "usage_metadata", "usageMetadata")]
    result = TokenUsage()
    fields = {
        "input_tokens": ("prompt_tokens", "input_tokens", "promptTokens", "inputTokens", "promptTokenCount", "inputTokenCount"),
        "output_tokens": ("completion_tokens", "output_tokens", "completionTokens", "outputTokens", "candidatesTokenCount"),
        "cached_tokens": ("cached_tokens", "prompt_cache_hit_tokens", "cachedContentTokenCount", "cache_read_input_tokens"),
    }
    for usage in containers:
        if not isinstance(usage, dict):
            continue
        for field, keys in fields.items():
            for key in keys:
                value = _count(usage.get(key))
                if value is not None:
                    setattr(result, field, value)
                    break
        for key in ("prompt_tokens_details", "input_tokens_details"):
            details = usage.get(key)
            if isinstance(details, dict):
                value = _count(details.get("cached_tokens"))
                if value is not None:
                    result.cached_tokens = value
    return result


def merge_usage(previous: TokenUsage, current: TokenUsage) -> TokenUsage:
    return TokenUsage(**{key: value if value is not None else getattr(previous, key)
                         for key, value in current.model_dump().items()})
