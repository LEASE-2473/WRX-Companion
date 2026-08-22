import json
from datetime import datetime
from uuid import uuid4

from .config import CONVERSATIONS_FILE
from .models import ChatMessage, ConversationRecord


def _now() -> datetime:
    return datetime.now().astimezone()


def _read() -> list[ConversationRecord]:
    if not CONVERSATIONS_FILE.exists():
        return []
    try:
        raw = json.loads(CONVERSATIONS_FILE.read_text(encoding="utf-8"))
        return [ConversationRecord.model_validate(item) for item in raw]
    except (OSError, ValueError, TypeError):
        return []


def _write(items: list[ConversationRecord]) -> None:
    CONVERSATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONVERSATIONS_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(CONVERSATIONS_FILE)


def list_conversations() -> list[ConversationRecord]:
    return sorted(_read(), key=lambda item: item.updated_at, reverse=True)


def create_conversation() -> ConversationRecord:
    created = _now()
    item = ConversationRecord(
        id=str(uuid4()),
        name=created.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
        messages=[],
    )
    items = _read()
    items.append(item)
    _write(items)
    return item


def save_conversation(conversation_id: str, messages: list[ChatMessage]) -> ConversationRecord | None:
    items = _read()
    current = next((item for item in items if item.id == conversation_id), None)
    if current is None:
        return None
    current.messages = [message for message in messages if message.role in {"user", "assistant"}]
    current.updated_at = _now().isoformat()
    _write(items)
    return current
