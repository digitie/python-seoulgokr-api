from __future__ import annotations

import httpx
import pytest

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig
from seoulgokr.errors import SeoulConfigurationError, SeoulQuotaError


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
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="1,000건"):
            await client.traffic_info("link", start_index=1, end_index=1002)
