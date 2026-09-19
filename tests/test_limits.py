from __future__ import annotations

import asyncio
import gc

import httpx
import pytest
from pydantic import ValidationError

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig
from seoulgokr.config import validate_base_url
from seoulgokr.errors import SeoulConfigurationError, SeoulQuotaError
from seoulgokr.rate_limit import RateLimitPolicy, ServiceRateLimiter
from seoulgokr.transport import AsyncSeoulTransport


def _traceback_locals_repr(error: BaseException) -> str:
    frames: list[object] = []
    traceback = error.__traceback__
    while traceback is not None:
        module_name = traceback.tb_frame.f_globals.get("__name__", "")
        if str(module_name).startswith("seoulgokr."):
            frames.append(dict(traceback.tb_frame.f_locals))
        traceback = traceback.tb_next
    return repr(frames)


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
        "https://example.com/api?",
        "https://example.com/api#password",
        "https://example.com/api#",
        "https://example.com:invalid/api",
        "https://",
        "https:///api",
    ],
)
def test_base_url_rejects_embedded_credentials_and_query_secrets(base_url):
    with pytest.raises(ValidationError, match="base URL"):
        SeoulOpenDataConfig(api_key="key", general_base_url=base_url)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPS://EXAMPLE.COM:443/api/", "https://example.com/api"),
        ("http://EXAMPLE.COM:80/api/", "http://example.com/api"),
        ("https://example.com./api///", "https://example.com/api"),
        ("https://example.com/api/.", "https://example.com/api"),
        ("https://example.com/api/../api", "https://example.com/api"),
        ("https://example.com/../api", "https://example.com/api"),
        ("https://example.com/api/%2e%2e/api", "https://example.com/api"),
        ("https://example.com/%7euser", "https://example.com/~user"),
        ("https://example.com/%2f/api", "https://example.com/%2F/api"),
    ],
)
def test_base_url_canonicalizes_host_default_port_and_path(value, expected):
    assert validate_base_url(value) == expected


def test_from_env_validation_does_not_keep_api_key_in_traceback(monkeypatch):
    secret = "from-env-traceback-secret"
    monkeypatch.setenv("SEOUL_OPEN_DATA_API_KEY", secret)

    with pytest.raises(ValidationError) as error:
        SeoulOpenDataConfig.from_env(timeout_seconds=0)

    assert secret not in _traceback_locals_repr(error.value)


@pytest.mark.asyncio
async def test_model_copy_base_url_is_revalidated_before_request():
    config = SeoulOpenDataConfig(
        api_key="copy-key",
        general_min_interval_seconds=0,
        allow_insecure_http=True,
    ).model_copy(update={"general_base_url": "https://example.com/api?secret=key"})
    with pytest.raises(ValueError, match="base URL"):
        SeoulOpenDataClient(config=config)


@pytest.mark.asyncio
async def test_same_scope_rejects_conflicting_max_concurrency():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    first_config = SeoulOpenDataConfig(
        api_key="policy-conflict-key",
        max_concurrency=1,
        general_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    second_config = first_config.model_copy(update={"max_concurrency": 2})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        async with SeoulOpenDataClient(
            config=first_config, http_client=http_client
        ) as first:
            await first.traffic_info("link")
        async with SeoulOpenDataClient(
            config=second_config, http_client=http_client
        ) as second:
            with pytest.raises(ValueError, match="max_concurrency") as error:
                await second.traffic_info("link")

    assert "policy-conflict-key" not in _traceback_locals_repr(error.value)
    assert calls == 1


@pytest.mark.asyncio
async def test_mutating_client_config_cannot_change_shared_max_concurrency():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    config = SeoulOpenDataConfig(
        api_key="mutable-policy-key",
        max_concurrency=1,
        general_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        await client.traffic_info("link")
        client.config.max_concurrency = 2
        with pytest.raises(ValueError, match="max_concurrency"):
            await client.traffic_info("link")

    assert calls == 1


@pytest.mark.asyncio
async def test_model_copy_secret_is_validated_before_transport(config):
    copied = config.model_copy(update={"api_key": "raw-copy-key"})
    response = httpx.Response(
        200,
        headers={"content-type": "application/xml"},
        content=(
            "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
            "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
        ).encode(),
    )
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: response)
        ) as http_client,
        SeoulOpenDataClient(config=copied, http_client=http_client) as client,
    ):
        result = await client.traffic_info("link")

    assert client.config.api_key is not None
    assert client.config.api_key.get_secret_value() == "raw-copy-key"
    assert result.items[0].link_id == "link"


@pytest.mark.asyncio
async def test_same_scope_rejects_conflicting_quota_timezone():
    scope = "timezone-policy-conflict"
    first = ServiceRateLimiter.shared(scope, timezone_name="Asia/Seoul")

    assert first._timezone_name == "Asia/Seoul"
    with pytest.raises(ValueError, match="quota_timezone"):
        ServiceRateLimiter.shared(scope, timezone_name="UTC")


def test_shared_registry_does_not_retain_closed_event_loops():
    scope_prefix = "closed-loop-cleanup-"

    async def contend(scope: str) -> None:
        limiter = ServiceRateLimiter.shared(scope, timezone_name="Asia/Seoul")

        async def enter() -> None:
            async with limiter.slot(
                "service", RateLimitPolicy(minimum_interval_seconds=0)
            ):
                await asyncio.sleep(0)

        await asyncio.gather(enter(), enter())

    for index in range(5):
        asyncio.run(contend(f"{scope_prefix}{index}"))
    gc.collect()

    assert all(
        registry_ref() is None
        or not any(scope.startswith(scope_prefix) for scope in registry_ref().limiters)
        for registry_ref in ServiceRateLimiter._shared.values()
    )
    assert all(not loop.is_closed() for loop in ServiceRateLimiter._shared)


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/", "/.", "/%2e%2e"])
async def test_canonical_base_url_keeps_shared_quota_scope(suffix):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    first_config = SeoulOpenDataConfig(
        api_key="canonical-scope-key",
        service_daily_budgets={"TrafficInfo": 1},
        general_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    second_config = first_config.model_copy(
        update={"general_base_url": f"{first_config.general_base_url}{suffix}"}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        async with SeoulOpenDataClient(
            config=first_config, http_client=http_client
        ) as first:
            await first.traffic_info("link")
        async with SeoulOpenDataClient(
            config=second_config, http_client=http_client
        ) as second:
            with pytest.raises(SeoulQuotaError, match="일일 호출 예산"):
                await second.traffic_info("link")

    assert calls == 1


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
