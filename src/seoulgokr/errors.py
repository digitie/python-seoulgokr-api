"""서울 Open API 오류 타입."""

from __future__ import annotations

from collections.abc import Mapping

TRANSIENT_UPSTREAM_CODES = frozenset({"ERROR-500", "ERROR-600", "ERROR-601"})
UPSTREAM_QUOTA_CODES = frozenset({"ERROR-337"})
_QUOTA_MESSAGE_MARKERS = (
    "quota",
    "rate limit",
    "daily limit",
    "limit exceeded",
    "한도 초과",
    "호출 한도",
    "일일 호출",
    "호출 횟수",
)


def is_upstream_quota_error(code: str, message: str) -> bool:
    """서울 API의 quota 초과 응답인지 판별한다.

    ``ERROR-335``/``ERROR-336``은 호출 1회의 페이지 크기 오류이므로
    cooldown 대상에서 제외한다. 서울시가 일일 한도 초과에 사용하는
    ``ERROR-337``과 명시적인 quota 문구만 quota로 분류한다.
    """

    normalized_message = message.casefold()
    return code in UPSTREAM_QUOTA_CODES or any(
        marker in normalized_message for marker in _QUOTA_MESSAGE_MARKERS
    )


class SeoulGokrError(Exception):
    """provider 오류의 공통 기반 클래스."""


class SeoulConfigurationError(SeoulGokrError):
    """인증키·URL·호출 설정이 유효하지 않다."""


class SeoulRateLimitError(SeoulGokrError):
    """호출 간격 또는 동시성 제한으로 현재 호출을 수행할 수 없다."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
        request: Mapping[str, str] | None = None,
    ) -> None:
        self.retry_after = retry_after
        self.status_code = status_code
        self.request = dict(request or {})
        super().__init__(message)


class SeoulQuotaError(SeoulRateLimitError):
    """애플리케이션이 설정한 일일 예산을 소진했다."""


class SeoulParseError(SeoulGokrError):
    """응답 형식 또는 필드가 계약과 맞지 않는다."""


class SeoulHttpError(SeoulGokrError):
    """HTTP 오류다."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        request: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.request = dict(request or {})
        super().__init__(f"서울 Open API HTTP {status_code}: {message}")


class SeoulUpstreamError(SeoulGokrError):
    """HTTP 200 안에 담긴 서울 API application-level 오류다."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        service: str,
        request: Mapping[str, str] | None = None,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.service = service
        self.request = dict(request or {})
        self.retryable = retryable
        super().__init__(f"서울 Open API {service} {code}: {message}")
