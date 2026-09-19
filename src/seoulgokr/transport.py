"""서울 Open API의 HTTP, retry, timeout, quota 경계."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx

from .config import SeoulOpenDataConfig, validate_base_url
from .errors import (
    SeoulConfigurationError,
    SeoulGokrError,
    SeoulHttpError,
    SeoulRateLimitError,
)
from .rate_limit import RateLimitPolicy, ServiceRateLimiter
from .redaction import safe_request


@dataclass(frozen=True)
class TransportResponse:
    content: bytes
    status_code: int
    content_type: str
    headers: Mapping[str, str]
    fetched_at: datetime
    request: Mapping[str, str]


@dataclass
class RetryBudget:
    """논리 호출 전체가 공유하는 bounded retry 예산."""

    remaining: int
    used: int = 0

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        self.used += 1
        return True


class AsyncSeoulTransport:
    """주입 가능한 httpx transport를 사용하는 비동기 HTTP client."""

    def __init__(
        self,
        config: SeoulOpenDataConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        limiter: ServiceRateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        try:
            validated_config = config.validated_copy()
        finally:
            config = None  # type: ignore[assignment]
        self.config = validated_config
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(validated_config.timeout_seconds),
            headers={
                "User-Agent": validated_config.user_agent,
                "Accept": "application/json, application/xml",
            },
        )
        self._owns_client = http_client is None
        self._sleep = sleep or asyncio.sleep
        self._provided_limiter = limiter
        self._limiters: dict[str, ServiceRateLimiter] = {}

    async def aclose(self) -> None:
        try:
            if self._owns_client:
                await self._client.aclose()
        finally:
            # Do not keep loop-bound semaphores alive after the transport's
            # lifecycle has ended.
            self._limiters.clear()

    async def request(
        self,
        *,
        api: str,
        service: str,
        response_format: str,
        start_index: int | None = None,
        end_index: int | None = None,
        filter_value: str | None = None,
        include_pagination: bool = True,
        retry_budget: RetryBudget | None = None,
    ) -> TransportResponse:
        key = None
        base_url = ""
        path_parts: list[tuple[str, bool]] = []
        url = ""
        try:
            if api not in {"general", "subway"}:
                raise ValueError("api는 general 또는 subway여야 합니다")
            key = self.config.api_key if api == "general" else self.config.subway_key
            if key is None:
                raise SeoulConfigurationError(
                    f"{api} API 호출에 필요한 인증키가 설정되지 않았습니다"
                )
            base_url = (
                self.config.general_base_url
                if api == "general"
                else self.config.subway_base_url
            )
            base_url = validate_base_url(base_url)
            if base_url.startswith("http://") and not self.config.allow_insecure_http:
                raise SeoulConfigurationError(
                    "서울 Open API 공식 endpoint가 HTTP이므로 기본적으로 차단했습니다. "
                    "HTTPS proxy를 사용하거나 backend 전용 설정에서 allow_insecure_http=True를 명시하세요"
                )
            if include_pagination:
                if start_index is None or end_index is None:
                    raise ValueError(
                        "pagination을 포함할 때 start_index와 end_index가 필요합니다"
                    )
                _validate_pagination(
                    api=api,
                    service=service,
                    key=key.get_secret_value(),
                    start_index=start_index,
                    end_index=end_index,
                )
            path_parts = [
                (key.get_secret_value(), False),
                (response_format, False),
                (service, True),
            ]
            if include_pagination:
                path_parts.extend(
                    [
                        (str(start_index), False),
                        (str(end_index), False),
                        (filter_value or "", False),
                    ]
                )
            elif filter_value:
                path_parts.append((filter_value, False))
            url = "/".join(
                [
                    base_url,
                    *(
                        quote(part, safe="/" if allow_slash else "")
                        for part, allow_slash in path_parts
                    ),
                ]
            )
            request_info = safe_request("GET", url, secrets=(key.get_secret_value(),))
            minimum, daily_budget = self.config.policy_for(service)
            policy = RateLimitPolicy(
                minimum_interval_seconds=minimum,
                daily_budget=daily_budget,
                max_concurrency=self.config.max_concurrency,
            )
            return await self._request_with_retry(
                url,
                request_info,
                self.config.quota_group(service),
                policy,
                limiter=self._limiter_for(api),
                retry_budget=retry_budget,
            )
        finally:
            # Any traceback through this frame must not retain raw path segments.
            key = None
            path_parts.clear()
            url = ""
            base_url = ""

    def _limiter_for(self, api: str) -> ServiceRateLimiter:
        if self._provided_limiter is not None:
            return self._provided_limiter
        key = ""
        base_url = ""
        try:
            if api == "general":
                key = (
                    self.config.api_key.get_secret_value()
                    if self.config.api_key
                    else ""
                )
                base_url = validate_base_url(self.config.general_base_url)
            elif api == "subway":
                key = (
                    self.config.subway_key.get_secret_value()
                    if self.config.subway_key
                    else ""
                )
                base_url = validate_base_url(self.config.subway_base_url)
            else:
                raise ValueError("api는 general 또는 subway여야 합니다")
            limiter = ServiceRateLimiter.shared(
                ServiceRateLimiter.scope_for(key, base_url),
                timezone_name=self.config.quota_timezone,
                max_concurrency=self.config.max_concurrency,
            )
            # Re-resolve the scope on every request. Config has validated
            # assignment enabled, and changing credentials/endpoint/policy
            # must not silently reuse a stale limiter.
            self._limiters[api] = limiter
            return limiter
        finally:
            key = ""
            base_url = ""

    def mark_cooldown(
        self, *, api: str, service: str, delay_seconds: float | None
    ) -> None:
        """application-level quota 오류를 다음 호출에 반영한다."""

        if api not in {"general", "subway"}:
            raise ValueError("api는 general 또는 subway여야 합니다")
        self._limiter_for(api).mark_cooldown(
            self.config.quota_group(service), delay_seconds
        )

    async def _request_with_retry(
        self,
        url: str,
        request_info: Mapping[str, str],
        service: str,
        policy: RateLimitPolicy,
        *,
        limiter: ServiceRateLimiter,
        retry_budget: RetryBudget | None = None,
    ) -> TransportResponse:
        last_error: Exception | None = None
        response: httpx.Response | None = None
        response_content = b""
        response_headers: dict[str, str] = {}
        response_status = 0
        network_failure = False
        cancelled = False
        error: SeoulGokrError
        budget = retry_budget or RetryBudget(self.config.max_retries)

        def sanitize_locals() -> None:
            """이 함수의 traceback frame에서 raw request 값을 지운다."""

            nonlocal last_error, response, response_content, response_headers
            nonlocal response_status, url
            last_error = None
            response = None
            response_content = b""
            response_headers = {}
            response_status = 0
            url = ""

        try:
            while True:
                try:
                    async with limiter.slot(service, policy):
                        async with asyncio.timeout(self.config.timeout_seconds):
                            async with self._client.stream("GET", url) as response:
                                response_status = response.status_code
                                response_headers = dict(response.headers)
                                response_content = b""
                                if 200 <= response_status < 300:
                                    content_length = _content_length(response_headers)
                                    if (
                                        content_length is not None
                                        and content_length
                                        > self.config.max_response_bytes
                                    ):
                                        response = None
                                        raise SeoulHttpError(
                                            413,
                                            "서울 Open API 응답이 허용된 크기를 초과했습니다",
                                            request=request_info,
                                        )
                                    chunks: list[bytes] = []
                                    total_bytes = 0
                                    try:
                                        async for chunk in response.aiter_bytes(
                                            chunk_size=min(
                                                64 * 1024,
                                                self.config.max_response_bytes,
                                            )
                                        ):
                                            total_bytes += len(chunk)
                                            if (
                                                total_bytes
                                                > self.config.max_response_bytes
                                            ):
                                                chunks.clear()
                                                chunk = b""
                                                response = None
                                                raise SeoulHttpError(
                                                    413,
                                                    "서울 Open API 응답이 허용된 크기를 초과했습니다",
                                                    request=request_info,
                                                )
                                            chunks.append(chunk)
                                        response_content = b"".join(chunks)
                                    finally:
                                        chunks.clear()
                except SeoulGokrError:
                    sanitize_locals()
                    raise
                except httpx.InvalidURL:
                    network_failure = True
                    break
                except (TimeoutError, httpx.TransportError) as exc:
                    last_error = exc
                    if not budget.consume():
                        network_failure = True
                        break
                    await self._backoff(budget.used - 1)
                    continue
                if response_status == 429:
                    retry_after = _retry_after_seconds(response_headers)
                    if (
                        retry_after is not None
                        and retry_after > self.config.retry_backoff_max_seconds
                    ):
                        limiter.mark_cooldown(
                            service, self.config.retry_backoff_max_seconds
                        )
                        error = SeoulRateLimitError(
                            "서울 Open API가 지정한 Retry-After가 너무 길어 재시도를 중단했습니다",
                            retry_after=retry_after,
                            status_code=429,
                            request=request_info,
                        )
                        sanitize_locals()
                        raise error
                    limiter.mark_cooldown(service, retry_after)
                    last_error = SeoulRateLimitError(
                        f"서울 Open API 일시 오류 HTTP {response_status}",
                        retry_after=retry_after,
                        status_code=429,
                        request=request_info,
                    )
                    if budget.consume():
                        await self._backoff(budget.used - 1, retry_after=retry_after)
                        continue
                    assert isinstance(last_error, SeoulRateLimitError)
                    error = last_error
                    sanitize_locals()
                    raise error
                if response_status in {500, 502, 503, 504}:
                    retry_after = _retry_after_seconds(response_headers)
                    if (
                        retry_after is not None
                        and retry_after > self.config.retry_backoff_max_seconds
                    ):
                        limiter.mark_cooldown(
                            service, self.config.retry_backoff_max_seconds
                        )
                        error = SeoulRateLimitError(
                            "서울 Open API 5xx Retry-After가 너무 길어 재시도를 중단했습니다",
                            retry_after=retry_after,
                            status_code=response_status,
                            request=request_info,
                        )
                        sanitize_locals()
                        raise error
                    limiter.mark_cooldown(service, retry_after)
                    last_error = SeoulRateLimitError(
                        f"서울 Open API 일시 오류 HTTP {response_status}",
                        retry_after=retry_after,
                        status_code=response_status,
                        request=request_info,
                    )
                    if budget.consume():
                        await self._backoff(budget.used - 1, retry_after=retry_after)
                        continue
                    assert isinstance(last_error, SeoulRateLimitError)
                    error = last_error
                    sanitize_locals()
                    raise error
                if response_status < 200 or response_status >= 300:
                    error = SeoulHttpError(
                        response_status,
                        "서울 Open API가 HTTP 오류를 반환했습니다",
                        request=request_info,
                    )
                    sanitize_locals()
                    raise error
                return TransportResponse(
                    content=response_content,
                    status_code=response_status,
                    content_type=response_headers.get("content-type", ""),
                    headers={
                        key: value
                        for key, value in response_headers.items()
                        if key.lower() in {"content-type", "retry-after"}
                    },
                    fetched_at=datetime.now(UTC),
                    request=request_info,
                )
            if network_failure:
                # This raise is intentionally outside the except block. Raising
                # a sanitized error inside it would retain the httpx exception
                # in ``__context__`` along with its request URL and credentials.
                error = SeoulHttpError(
                    0,
                    "서울 Open API 네트워크 요청이 실패했습니다",
                    request=request_info,
                )
                sanitize_locals()
                raise error
            error = SeoulHttpError(
                503,
                "서울 Open API 일시 오류 재시도 한도를 초과했습니다",
                request=request_info,
            )
            sanitize_locals()
            raise error
        except asyncio.CancelledError:
            # Do not re-raise the original cancellation traceback: httpx may
            # retain the key-bearing URL in its internal stream frame locals.
            cancelled = True
        finally:
            sanitize_locals()
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("서울 Open API transport가 예기치 않게 종료되었습니다")

    async def _backoff(self, attempt: int, *, retry_after: float | None = None) -> None:
        if retry_after is not None:
            delay = retry_after
        else:
            base = self.config.retry_backoff_seconds * (2**attempt)
            delay = min(
                base + random.uniform(0, min(base * 0.1, 0.5)),
                self.config.retry_backoff_max_seconds,
            )
        if delay > 0:
            await self._sleep(delay)


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after") or headers.get("Retry-After")
    if not value:
        return None
    try:
        parsed = float(value)
        return max(0.0, parsed) if math.isfinite(parsed) else None
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("content-length") or headers.get("Content-Length")
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _validate_pagination(
    *, api: str, service: str, key: str, start_index: int, end_index: int
) -> None:
    minimum = 1 if api == "general" else 0
    if start_index < minimum or end_index < start_index:
        key = ""
        raise SeoulConfigurationError(
            f"{api} API pagination이 올바르지 않습니다: start={start_index}, end={end_index}"
        )
    page_size = (
        end_index - start_index if api == "subway" else end_index - start_index + 1
    )
    if page_size < 1 or page_size > 1000:
        key = ""
        raise SeoulConfigurationError(
            "서울 Open API 한 호출의 페이지 범위는 1~1,000건이어야 합니다"
        )
    if key == "sample" and api == "subway" and (start_index != 0 or end_index > 5):
        key = ""
        raise SeoulConfigurationError(
            "sample 지하철 키는 0..5 범위만 요청할 수 있습니다"
        )
    if key == "sample" and api == "general" and page_size > 5:
        key = ""
        raise SeoulConfigurationError(
            "sample 인증키는 한 호출에 최대 5건만 요청할 수 있습니다"
        )
