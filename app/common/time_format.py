"""持久化时间精确到秒；业务日期与外部协议字符串保持原义。"""
from datetime import datetime, timezone
import re

ISO_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$')


def utc_seconds(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def normalize_times(value):
    if isinstance(value, dict):
        return {k: normalize_times(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_times(v) for v in value]
    if isinstance(value, str) and ISO_TIME.fullmatch(value):
        return utc_seconds(value)
    return value
