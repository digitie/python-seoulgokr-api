"""인증키가 포함되는 서울 API URL의 안전한 진단 표현."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

REDACTED = "<redacted>"


def redact_url(url: str, secrets: tuple[str, ...]) -> str:
    redacted = redact_text(url, secrets)
    try:
        parsed = urlsplit(redacted)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return "<invalid-url>"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    hostport = hostname if port is None else f"{hostname}:{port}"
    # Query/fragment/userinfo may contain proxy credentials or other secrets.
    return urlunsplit((parsed.scheme, hostport, parsed.path, "", ""))


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, REDACTED)
            result = result.replace(quote(secret, safe=""), REDACTED)
    return result


def redact_value(value: Any, secrets: tuple[str, ...]) -> Any:
    """응답 payload/model에 key가 echo되어도 provenance에 남기지 않는다."""

    if isinstance(value, Mapping):
        return {
            redact_text(str(key), secrets): redact_value(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def safe_request(method: str, url: str, *, secrets: tuple[str, ...]) -> dict[str, str]:
    return {"method": method, "url": redact_url(url, secrets)}
