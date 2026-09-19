from __future__ import annotations

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig
from seoulgokr.errors import SeoulConfigurationError, SeoulQuotaError
from seoulgokr.rate_limit import RateLimitPolicy, ServiceRateLimiter
from seoulgokr.transport import AsyncSeoulTransport


@pytest.mark.asyncio
async def test_sample_key_page_guard_happens_before_network():
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    config = SeoulOpenDataConfig(
        api_key="sample",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="최대 5건"):
            await client.traffic_info("link", start_index=1, end_index=7)
    assert called is False


@pytest.mark.asyncio
async def test_general_page_range_guard_happens_before_network():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    config = SeoulOpenDataConfig(
        api_key="key",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="1,000건"):
            await client.traffic_info("link", start_index=1, end_index=1002)


@pytest.mark.asyncio
async def test_general_page_range_is_inclusive_at_the_boundary():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    config = SeoulOpenDataConfig(
        api_key="key",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="1,000건"):
            await client.traffic_info("link", start_index=1, end_index=1001)


@pytest.mark.asyncio
async def test_sample_subway_page_guard_rejects_index_six():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    config = SeoulOpenDataConfig(
        api_key="sample",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="0..5"):
            await client.subway_arrivals("서울", start_index=0, end_index=6)


@pytest.mark.asyncio
async def test_realtime_subway_daily_budget_defaults_to_configured_public_limit():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "errorMessage": {"code": "INFO-000", "message": "정상"},
                "realtimeArrivalList": [{"statnNm": "서울"}],
            },
        )

    config = SeoulOpenDataConfig(
        api_key="subway-budget-key",
        realtime_subway_daily_budget=1,
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        await client.subway_arrivals("서울")
        with pytest.raises(SeoulQuotaError, match="일일 호출 예산"):
            await client.subway_positions("1호선")

    assert calls == 1


@pytest.mark.asyncio
async def test_http_endpoint_is_fail_closed_by_default():
    config = SeoulOpenDataConfig(api_key="key")
    async with SeoulOpenDataClient(config=config) as client:
        with pytest.raises(SeoulConfigurationError, match="HTTP"):
            await client.traffic_info("link")


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.com/api",
        "https://example.com/api?service_key=password",
        "https://example.com/api#password",
        "https://example.com:invalid/api",
    ],
)
def test_base_url_rejects_embedded_credentials_and_query_secrets(base_url):
    with pytest.raises(ValidationError, match="base URL"):
        SeoulOpenDataConfig(api_key="key", general_base_url=base_url)


@pytest.mark.asyncio
async def test_extended_cooldown_is_not_cleared_by_an_older_waiter():
    limiter = ServiceRateLimiter()
    await limiter.cooldown("service", 0.02)

    started = asyncio.get_running_loop().time()

    async def enter_slot() -> None:
        async with limiter.slot("service", RateLimitPolicy(minimum_interval_seconds=0)):
            return

    task = asyncio.create_task(enter_slot())
    await asyncio.sleep(0.005)
    limiter.mark_cooldown("service", 0.05)
    await task

    assert asyncio.get_running_loop().time() - started >= 0.04


@pytest.mark.asyncio
async def test_limiter_rejects_conflicting_concurrency_policy():
    limiter = ServiceRateLimiter()
    async with limiter.slot("service", RateLimitPolicy(max_concurrency=1)):
        pass

    with pytest.raises(ValueError, match="max_concurrency"):
        async with limiter.slot("service", RateLimitPolicy(max_concurrency=2)):
            pass


def test_subway_only_configuration_can_be_created_from_env(monkeypatch):
    monkeypatch.delenv("SEOUL_OPEN_DATA_API_KEY", raising=False)
    monkeypatch.setenv("SEOUL_SUBWAY_API_KEY", "subway-key")
    config = SeoulOpenDataConfig.from_env()
    assert config.api_key is None
    assert config.subway_key is not None


@pytest.mark.asyncio
async def test_config_and_transport_must_match():
    config = SeoulOpenDataConfig(api_key="key", allow_insecure_http=True)
    other = config.model_copy(update={"general_min_interval_seconds": 2.0})
    transport = AsyncSeoulTransport(config)
    try:
        with pytest.raises(ValueError, match="일치"):
            SeoulOpenDataClient(config=other, transport=transport)
    finally:
        await transport.aclose()
