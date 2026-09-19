"""서비스별 최소 호출 간격과 애플리케이션 quota 보호."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .errors import SeoulQuotaError


@dataclass(frozen=True)
class RateLimitPolicy:
    minimum_interval_seconds: float = 1.0
    daily_budget: int | None = None
    max_concurrency: int = 1


@dataclass
class _ServiceState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    semaphore: asyncio.Semaphore | None = None
    semaphore_limit: int | None = None
    last_started: float | None = None
    calls_today: int = 0
    call_date: object | None = None


class ServiceRateLimiter:
    """프로세스 내부에서만 동작하는 보수적인 서비스 limiter.

    upstream의 quota가 공개되지 않은 서비스에 임의의 quota를 주장하지 않기 위해
    기본 daily budget은 무제한(``None``)이며, 운영자가 서비스별 예산을 명시할 때만
    차단한다. 여러 프로세스가 같은 키를 공유하는 경우에는 외부 limiter가 필요하다.
    """

    def __init__(
        self,
        *,
        default_policy: RateLimitPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.default_policy = default_policy or RateLimitPolicy()
        self._sleep = sleep or asyncio.sleep
        self._states: dict[str, _ServiceState] = {}
        self._states_lock = asyncio.Lock()

    async def _state(self, service: str) -> _ServiceState:
        async with self._states_lock:
            state = self._states.get(service)
            if state is None:
                state = _ServiceState()
                self._states[service] = state
            return state

    @asynccontextmanager
    async def slot(
        self, service: str, policy: RateLimitPolicy | None = None
    ) -> AsyncIterator[None]:
        policy = policy or self.default_policy
        state = await self._state(service)
        if state.semaphore is None or state.semaphore_limit != policy.max_concurrency:
            state.semaphore = asyncio.Semaphore(policy.max_concurrency)
            state.semaphore_limit = policy.max_concurrency
        async with state.semaphore:
            async with state.lock:
                today = datetime.now(UTC).date()
                if state.call_date != today:
                    state.call_date = today
                    state.calls_today = 0
                if (
                    policy.daily_budget is not None
                    and state.calls_today >= policy.daily_budget
                ):
                    raise SeoulQuotaError(
                        f"서비스 {service}의 애플리케이션 일일 호출 예산({policy.daily_budget})을 소진했습니다"
                    )
                if state.last_started is not None:
                    wait_for = policy.minimum_interval_seconds - (
                        time.monotonic() - state.last_started
                    )
                    if wait_for > 0:
                        await self._sleep(wait_for)
                state.last_started = time.monotonic()
                state.calls_today += 1
            try:
                yield
            finally:
                pass
