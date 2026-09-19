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

from .config import SeoulOpenDataConfig
from .errors import (
    SeoulConfigurationError,
    SeoulHttpError,
    SeoulQuotaError,
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
        self.config = config
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_seconds),
            headers={
                "User-Agent": config.user_agent,
                "Accept": "application/json, application/xml",
            },
        )
        self._owns_client = http_client is None
        self._sleep = sleep or asyncio.sleep
        self._provided_limiter = limiter
        self._limiters: dict[str, ServiceRateLimiter] = {}
        if limiter is None:
            self._limiters = {
                "general": ServiceRateLimiter.shared(
                    ServiceRateLimiter.scope_for(
                        config.api_key.get_secret_value() if config.api_key else "",
                        config.general_base_url,
                    ),
                    timezone_name=config.quota_timezone,
                ),
                "subway": ServiceRateLimiter.shared(
                    ServiceRateLimiter.scope_for(
                        config.subway_key.get_secret_value()
                        if config.subway_key
                        else "",
                        config.subway_base_url,
                    ),
                    timezone_name=config.quota_timezone,
                ),
            }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

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
    ) -> TransportResponse:
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
        path_parts: list[tuple[str, bool]] = [
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
        )

    def _limiter_for(self, api: str) -> ServiceRateLimiter:
        if self._provided_limiter is not None:
            return self._provided_limiter
        return self._limiters[api]

    async def _request_with_retry(
        self,
        url: str,
        request_info: Mapping[str, str],
        service: str,
        policy: RateLimitPolicy,
        *,
        limiter: ServiceRateLimiter,
    ) -> TransportResponse:
        last_error: Exception | None = None
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                async with limiter.slot(service, policy):
                    async with asyncio.timeout(self.config.timeout_seconds):
                        response = await self._client.get(url)
            except (TimeoutError, httpx.TransportError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise SeoulHttpError(
                        0,
                        "서울 Open API 네트워크 요청이 실패했습니다",
                        request=request_info,
                    ) from None
                await self._backoff(attempt)
                continue
            if response.status_code == 429:
                retry_after = _retry_after_seconds(response.headers)
                if (
                    retry_after is not None
                    and retry_after > self.config.retry_backoff_max_seconds
                ):
                    limiter.mark_cooldown(
                        service, self.config.retry_backoff_max_seconds
                    )
                    raise SeoulRateLimitError(
                        "서울 Open API가 지정한 Retry-After가 너무 길어 재시도를 중단했습니다",
                        retry_after=retry_after,
                        status_code=429,
                        request=request_info,
                    )
                limiter.mark_cooldown(service, retry_after)
                last_error = SeoulRateLimitError(
                    f"서울 Open API 일시 오류 HTTP {response.status_code}",
                    retry_after=retry_after,
                    status_code=429,
                    request=request_info,
                )
                if attempt + 1 < attempts:
                    await self._backoff(attempt, retry_after=retry_after)
                    continue
                raise last_error
            if response.status_code in {500, 502, 503, 504}:
                retry_after = _retry_after_seconds(response.headers)
                if (
                    retry_after is not None
                    and retry_after > self.config.retry_backoff_max_seconds
                ):
                    limiter.mark_cooldown(
                        service, self.config.retry_backoff_max_seconds
                    )
                    raise SeoulRateLimitError(
                        "서울 Open API 5xx Retry-After가 너무 길어 재시도를 중단했습니다",
                        retry_after=retry_after,
                        status_code=response.status_code,
                        request=request_info,
                    )
                limiter.mark_cooldown(service, retry_after)
                last_error = SeoulRateLimitError(
                    f"서울 Open API 일시 오류 HTTP {response.status_code}"
                )
                if attempt + 1 < attempts:
                    await self._backoff(attempt, retry_after=retry_after)
                    continue
            if response.status_code < 200 or response.status_code >= 300:
                raise SeoulHttpError(
                    response.status_code,
                    "서울 Open API가 HTTP 오류를 반환했습니다",
                    request=request_info,
                )
            return TransportResponse(
                content=response.content,
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"content-type", "retry-after"}
                },
                fetched_at=datetime.now(UTC),
                request=request_info,
            )
        raise SeoulHttpError(
            503,
            "서울 Open API 일시 오류 재시도 한도를 초과했습니다",
            request=request_info,
        ) from None

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


def _validate_pagination(
    *, api: str, service: str, key: str, start_index: int, end_index: int
) -> None:
    minimum = 1 if api == "general" else 0
    if start_index < minimum or end_index < start_index:
        raise SeoulConfigurationError(
            f"{api} API pagination이 올바르지 않습니다: start={start_index}, end={end_index}"
        )
    page_size = (
        end_index - start_index if api == "subway" else end_index - start_index + 1
    )
    if page_size < 1 or page_size > 1000:
        raise SeoulConfigurationError(
            "서울 Open API 한 호출의 페이지 범위는 1~1,000건이어야 합니다"
        )
    if key == "sample" and api == "subway" and (start_index != 0 or end_index > 5):
        raise SeoulQuotaError("sample 지하철 키는 0..5 범위만 요청할 수 있습니다")
    if key == "sample" and api == "general" and page_size > 5:
        raise SeoulQuotaError("sample 인증키는 한 호출에 최대 5건만 요청할 수 있습니다")
