import re

def describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    return f"{exc.__class__.__name__}: {message}" if message else exc.__class__.__name__

def normalize_voice_reply(reply: str) -> str:
    reply = re.sub(r"```(?:\w+)?", "", reply)
    reply = re.sub(r"^\s{0,3}#{1,6}\s*", "", reply, flags=re.MULTILINE)
    reply = re.sub(r"(^|\s)([*_]{1,3})(?=\S)", r"\1", reply)
    reply = re.sub(r"(?<=\S)([*_]{1,3})(?=\s|[，。！？,.!?]|$)", "", reply)
    reply = re.sub(r"^\s*[-*+]\s+", "", reply, flags=re.MULTILINE)
    return reply.strip()
