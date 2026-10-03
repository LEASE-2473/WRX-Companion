"""Safe provider exception details shared by HTTP and voice routes."""
from app.voice.pipeline import describe_exception

def safe_provider_detail(exc: Exception, *secrets: str) -> str:
    detail = describe_exception(exc)
    for secret in secrets:
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    return detail
