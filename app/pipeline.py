import re

def describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{exc.__class__.__name__}: {message}" if message else exc.__class__.__name__

def normalize_voice_reply(reply: str) -> str:
    reply = reply.replace("<|next_message|>", "\n")
    reply = re.sub(r"```(?:\w+)?", "", reply)
    reply = re.sub(r"(\*\*|__)(.+?)\1", r"\2", reply, flags=re.DOTALL)
    reply = re.sub(r"^\s{0,3}#{1,6}\s*", "", reply, flags=re.MULTILINE)
    reply = re.sub(r"(^|\s)([*_]{1,3})(?=\S)", r"\1", reply)
    reply = re.sub(r"(?<=\S)([*_]{1,3})(?=\s|[，。！？,.!?]|$)", "", reply)
    reply = re.sub(r"^\s*[-*+]\s+", "", reply, flags=re.MULTILINE)
    return reply.strip()

def take_tts_segment(buffer: str, final: bool = False) -> tuple[str, str]:
    """取出适合立即交给 TTS 的自然边界，避免逐 token 合成破坏韵律。"""
    if final:
        return buffer, ""
    for index, char in enumerate(buffer):
        if char in "。！？!?；;\n" and index >= 5:
            return buffer[:index + 1], buffer[index + 1:]
    if len(buffer) >= 32:
        boundary = max(buffer.rfind(mark, 12, 33) for mark in "，,、：:")
        if boundary >= 12:
            return buffer[:boundary + 1], buffer[boundary + 1:]
    if len(buffer) >= 48:
        return buffer[:48], buffer[48:]
    return "", buffer
