"""서울 provider 테스트 공통 fixture."""

from __future__ import annotations

import httpx
import pytest

from seoulgokr.config import SeoulOpenDataConfig


@pytest.fixture
def config() -> SeoulOpenDataConfig:
    return SeoulOpenDataConfig(
        api_key="unit-fixture-key",
        general_min_interval_seconds=0,
        realtime_min_interval_seconds=0,
        max_retries=1,
        retry_backoff_seconds=0,
    )


@pytest.fixture
def client_factory():
    def factory(handler, config: SeoulOpenDataConfig):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory
