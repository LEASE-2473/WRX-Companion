"""聊天历史统一选择，预览、常驻统计及真实请求共享规则。"""
from datetime import datetime
from app.settings.store import freeze_runtime_settings


def select_history(messages, settings=None):
    settings = settings or freeze_runtime_settings()
    if settings.history_mode == 'count':
        return messages[-settings.history_depth:] if settings.history_depth else []
    boundary = datetime.fromisoformat(settings.history_since)
    selected = []
    for message in messages:
        if not message.timestamp:
            continue
        try:
            timestamp = datetime.fromisoformat(message.timestamp)
            if timestamp.tzinfo and timestamp >= boundary:
                selected.append(message)
        except ValueError:
            continue
    return selected
