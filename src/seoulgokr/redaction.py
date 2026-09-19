"""인증키가 포함되는 서울 API URL의 안전한 진단 표현."""

from __future__ import annotations

from urllib.parse import quote

REDACTED = "<redacted>"


def redact_url(url: str, secrets: tuple[str, ...]) -> str:
    result = url
    for secret in secrets:
        if secret:
            result = result.replace(secret, REDACTED)
            result = result.replace(quote(secret, safe=""), REDACTED)
    return result


def safe_request(method: str, url: str, *, secrets: tuple[str, ...]) -> dict[str, str]:
    return {"method": method, "url": redact_url(url, secrets)}
