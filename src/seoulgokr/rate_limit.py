"""서비스별 최소 호출 간격과 애플리케이션 quota 보호."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

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
    cooldown_until: float | None = None


class ServiceRateLimiter:
    """동일 이벤트 루프 내부에서 동작하는 보수적인 서비스 limiter.

    upstream의 quota가 공개되지 않은 서비스에 임의의 quota를 주장하지 않기 위해
    기본 daily budget은 무제한(``None``)이며, 운영자가 서비스별 예산을 명시할 때만
    차단한다. 실시간 지하철의 공식 1,000/day 안내만 별도 설정으로 반영한다. 다른
    이벤트 루프나 프로세스가 같은 키를 공유하는 경우에는 외부 distributed limiter가
    필요하다.
    """

    def __init__(
        self,
        *,
        default_policy: RateLimitPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        timezone_name: str = "Asia/Seoul",
    ) -> None:
        self.default_policy = default_policy or RateLimitPolicy()
        self._sleep = sleep or asyncio.sleep
        self._states: dict[str, _ServiceState] = {}
        self._states_lock = asyncio.Lock()
        self._timezone = ZoneInfo(timezone_name)

    _shared: ClassVar[dict[tuple[str, int, str], ServiceRateLimiter]] = {}

    @classmethod
    def shared(cls, scope: str, *, timezone_name: str) -> ServiceRateLimiter:
        """동일 key scope의 client가 같은 이벤트 루프에서 limiter를 공유한다."""

        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = 0
        shared_key = (scope, loop_id, timezone_name)
        limiter = cls._shared.get(shared_key)
        if limiter is None:
            limiter = cls(timezone_name=timezone_name)
            cls._shared[shared_key] = limiter
        return limiter

    @staticmethod
    def scope_for(*parts: str) -> str:
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

    async def _state(self, service: str) -> _ServiceState:
        async with self._states_lock:
            state = self._states.get(service)
            if state is None:
                state = _ServiceState()
                self._states[service] = state
            return state

    async def cooldown(self, service: str, delay_seconds: float | None) -> None:
        if delay_seconds is None or delay_seconds <= 0:
            return
        state = await self._state(service)
        async with state.lock:
            self._set_cooldown(state, delay_seconds)

    def mark_cooldown(self, service: str, delay_seconds: float | None) -> None:
        """현재 이벤트 루프 차례 안에서 다음 slot의 대기를 예약한다."""

        if delay_seconds is None or delay_seconds <= 0:
            return
        state = self._states.get(service)
        if state is not None:
            self._set_cooldown(state, delay_seconds)

    @staticmethod
    def _set_cooldown(state: _ServiceState, delay_seconds: float) -> None:
        until = time.monotonic() + delay_seconds
        state.cooldown_until = max(state.cooldown_until or 0.0, until)

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
                if state.cooldown_until is not None:
                    wait_for = state.cooldown_until - time.monotonic()
                    if wait_for > 0:
                        await self._sleep(wait_for)
                    state.cooldown_until = None
                self._rollover(state)
                if (
                    policy.daily_budget is not None
                    and state.calls_today >= policy.daily_budget
                ):
                    raise SeoulQuotaError(
                        f"서비스 {service}의 애플리케이션 일일 호출 예산({policy.daily_budget})을 소진했습니다"
                    )
                wait_for = 0.0
                if state.last_started is not None:
                    wait_for = policy.minimum_interval_seconds - (
                        time.monotonic() - state.last_started
                    )
                if wait_for > 0:
                    await self._sleep(wait_for)
                    self._rollover(state)
                state.last_started = time.monotonic()
                state.calls_today += 1
            try:
                yield
            finally:
                pass

    def _rollover(self, state: _ServiceState) -> None:
        today = datetime.now(self._timezone).date()
        if state.call_date != today:
            state.call_date = today
            state.calls_today = 0
