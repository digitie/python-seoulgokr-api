"""서울 Open API의 HTTP, retry, timeout, quota 경계."""

from __future__ import annotations

import asyncio
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
        self._limiter = limiter or ServiceRateLimiter()

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
        base_url = (
            self.config.general_base_url
            if api == "general"
            else self.config.subway_base_url
        )
        if include_pagination:
            if start_index is None or end_index is None:
                raise ValueError(
                    "pagination을 포함할 때 start_index와 end_index가 필요합니다"
                )
            _validate_pagination(
                api=api,
                key=key.get_secret_value(),
                start_index=start_index,
                end_index=end_index,
            )
        path_parts = [key.get_secret_value(), response_format, service]
        if include_pagination:
            path_parts.extend([str(start_index), str(end_index), filter_value or ""])
        elif filter_value:
            path_parts.append(filter_value)
        url = "/".join([base_url, *(quote(part, safe="/") for part in path_parts)])
        request_info = safe_request("GET", url, secrets=(key.get_secret_value(),))
        minimum, daily_budget = self.config.policy_for(service)
        policy = RateLimitPolicy(
            minimum_interval_seconds=minimum,
            daily_budget=daily_budget,
            max_concurrency=self.config.max_concurrency,
        )
        return await self._request_with_retry(url, request_info, service, policy)

    async def _request_with_retry(
        self,
        url: str,
        request_info: Mapping[str, str],
        service: str,
        policy: RateLimitPolicy,
    ) -> TransportResponse:
        last_error: Exception | None = None
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                async with self._limiter.slot(service, policy):
                    response = await self._client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise SeoulHttpError(
                        0,
                        "서울 Open API 네트워크 요청이 실패했습니다",
                        request=request_info,
                    ) from exc
                await self._backoff(attempt)
                continue
            if response.status_code == 429 or response.status_code in {
                500,
                502,
                503,
                504,
            }:
                last_error = SeoulRateLimitError(
                    f"서울 Open API 일시 오류 HTTP {response.status_code}"
                )
                if attempt + 1 < attempts:
                    await self._backoff(
                        attempt, retry_after=_retry_after_seconds(response.headers)
                    )
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
        ) from last_error

    async def _backoff(self, attempt: int, *, retry_after: float | None = None) -> None:
        if retry_after is not None:
            delay = min(retry_after, self.config.retry_backoff_max_seconds)
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
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _validate_pagination(
    *, api: str, key: str, start_index: int, end_index: int
) -> None:
    minimum = 1 if api == "general" else 0
    if start_index < minimum or end_index < start_index:
        raise SeoulConfigurationError(
            f"{api} API pagination이 올바르지 않습니다: start={start_index}, end={end_index}"
        )
    if end_index - start_index > 1000:
        raise SeoulConfigurationError(
            "서울 Open API 한 호출의 페이지 범위는 1,000건 이하이어야 합니다"
        )
    if key == "sample" and end_index - start_index > 5:
        raise SeoulQuotaError("sample 인증키는 한 호출에 최대 5건만 요청할 수 있습니다")
