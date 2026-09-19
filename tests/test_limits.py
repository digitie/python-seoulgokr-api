from __future__ import annotations

import httpx
import pytest

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig
from seoulgokr.errors import SeoulConfigurationError, SeoulQuotaError
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
        with pytest.raises(SeoulQuotaError, match="최대 5건"):
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
        with pytest.raises(SeoulQuotaError, match="0..5"):
            await client.subway_arrivals("서울", start_index=0, end_index=6)


def test_http_endpoint_is_fail_closed_by_default():
    config = SeoulOpenDataConfig(api_key="key")
    with pytest.raises(SeoulConfigurationError, match="HTTP"):
        SeoulOpenDataClient(config=config)


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
