from __future__ import annotations

import asyncio

import httpx
import pytest

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig
from seoulgokr.errors import (
    SeoulConfigurationError,
    SeoulHttpError,
    SeoulParseError,
    SeoulQuotaError,
    SeoulRateLimitError,
    SeoulUpstreamError,
)
from seoulgokr.parsers.services import parse_parking_lots
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
async def test_traffic_xml_is_typed_and_key_is_redacted(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "unit-fixture-key" in str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><list_total_count>1</list_total_count>"
                "<RESULT><CODE>INFO-000</CODE><MESSAGE>정상 처리되었습니다</MESSAGE></RESULT>"
                "<row><link_id>1220003800</link_id><prcs_spd>34</prcs_spd>"
                "<prcs_trv_time>318</prcs_trv_time></row></TrafficInfo>"
            ).encode(),
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.traffic_info("1220003800")

    assert result.source_id == "OA-13291"
    assert result.items[0].link_id == "1220003800"
    assert result.items[0].process_speed_kph == 34
    assert result.items[0].process_travel_time_seconds == 318
    assert "unit-fixture-key" not in result.request["url"]
    assert "<redacted>" in result.request["url"]


@pytest.mark.asyncio
async def test_response_provenance_and_upstream_error_redact_echoed_key(config):
    responses = [
        httpx.Response(
            200,
            json={
                "TrafficInfo": {
                    "list_total_count": 1,
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"},
                    "row": [{"link_id": "unit-fixture-key"}],
                }
            },
        ),
        httpx.Response(
            200,
            json={
                "RESULT": {
                    "CODE": "ERROR-336",
                    "MESSAGE": "unit-fixture-key was echoed by upstream",
                }
            },
        ),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.traffic_info("link")
        with pytest.raises(SeoulUpstreamError) as error:
            await client.traffic_info("link")

    assert result.items[0].link_id == "<redacted>"
    assert "unit-fixture-key" not in repr(result.items[0].raw)
    assert "unit-fixture-key" not in repr(result.raw_payload)
    assert "unit-fixture-key" not in str(error.value)


@pytest.mark.asyncio
async def test_subway_arrival_envelope_and_empty_values(config):
    payload = {
        "errorMessage": {
            "status": 200,
            "code": "INFO-000",
            "message": "정상 처리되었습니다.",
            "total": 1,
        },
        "realtimeArrivalList": [
            {
                "subwayId": "1002",
                "subwayNm": None,
                "updnLine": "내선",
                "trainLineNm": "성수행 - 강남방면",
                "statnId": "1002000222",
                "statnNm": "강남",
                "btrainNo": "1234",
                "barvlDt": "",
                "recptnDt": "2026-09-19 09:12:53",
                "arvlMsg2": "곧 도착",
                "lstcarAt": "0",
            }
        ],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.subway_arrivals("강남")

    item = result.items[0]
    assert result.list_total_count == 1
    assert item.station_name == "강남"
    assert item.arrival_seconds is None
    assert item.received_at is not None
    assert item.last_car is False


@pytest.mark.asyncio
async def test_position_and_parking_endpoints_use_expected_services(config):
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "realtimePosition" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "errorMessage": {
                        "status": 200,
                        "code": "INFO-000",
                        "message": "정상",
                        "total": 1,
                    },
                    "realtimePositionList": [
                        {
                            "subwayId": "1001",
                            "subwayNm": "1호선",
                            "statnNm": "종각",
                            "trainNo": "0049",
                            "recptnDt": "2026-09-19 09:12:53",
                            "directAt": "1",
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "GetParkingInfo": {
                    "list_total_count": 1,
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"},
                    "row": [
                        {
                            "PKLT_CD": "1",
                            "PKLT_NM": "서울역",
                            "TPKCT": "100",
                            "NOW_PRK_VHCL_CNT": "7",
                        }
                    ],
                }
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        position = await client.subway_positions("1호선")
        parking = await client.parking_realtime()

    assert position.items[0].express is True
    assert parking.items[0].current_vehicle_count == 7
    assert any("realtimePosition" in call for call in calls)
    assert any("GetParkingInfo" in call for call in calls)


@pytest.mark.asyncio
async def test_citydata_preserves_nested_blocks(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "list_total_count": 1,
                "RESULT": {
                    "RESULT.CODE": "INFO-000",
                    "RESULT.MESSAGE": "정상 처리되었습니다.",
                },
                "CITYDATA": {
                    "AREA_NM": "광화문·덕수궁",
                    "AREA_CD": "POI001",
                    "LIVE_PPLTN_STTS": [
                        {"AREA_CONGEST_LVL": "여유", "AREA_CONGEST_MSG": "원활"}
                    ],
                    "ROAD_TRAFFIC_STTS": {"AVG_ROAD_DATA": "원문"},
                    "PRK_STTS": [{"PRK_NM": "주차"}],
                },
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.citydata("광화문·덕수궁")

    assert result.items[0].area_code == "POI001"
    assert result.items[0].area_congestion_level == "여유"
    assert result.items[0].road_traffic["AVG_ROAD_DATA"] == "원문"
    assert result.items[0].parking[0]["PRK_NM"] == "주차"


@pytest.mark.asyncio
async def test_upstream_error_is_not_silently_treated_as_empty(config):
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                200,
                json={"RESULT": {"CODE": "ERROR-500", "MESSAGE": "temporary"}},
            )
        return httpx.Response(
            200,
            json={
                "TrafficInfo": {
                    "list_total_count": 0,
                    "RESULT": {"CODE": "INFO-200", "MESSAGE": "empty"},
                    "row": [],
                }
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.traffic_info("link")

    assert attempts == 2
    assert result.items == ()


@pytest.mark.asyncio
async def test_non_retryable_upstream_error_is_raised(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"RESULT": {"CODE": "ERROR-336", "MESSAGE": "too many"}}
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulUpstreamError, match="ERROR-336"):
            await client.traffic_info("link")


@pytest.mark.asyncio
async def test_malformed_envelope_and_traffic_row_are_rejected(config):
    responses = [
        httpx.Response(200, json={"unexpected": "payload"}),
        httpx.Response(
            200,
            json={
                "TrafficInfo": {
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"},
                    "row": [{}],
                }
            },
        ),
        httpx.Response(
            200,
            json={
                "TrafficInfo": {
                    "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"},
                    "garbage": "value",
                }
            },
        ),
        httpx.Response(
            200,
            json={"RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"}},
        ),
        httpx.Response(
            200,
            json={"TrafficInfo": {"row": [{"LINK_ID": "x"}]}},
        ),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulParseError, match="envelope"):
            await client.traffic_info("link")
        with pytest.raises(SeoulParseError, match="link_id"):
            await client.traffic_info("link")
        with pytest.raises(SeoulParseError, match="list/row"):
            await client.traffic_info("link")
        with pytest.raises(SeoulParseError, match="list/row"):
            await client.traffic_info("link")
        with pytest.raises(SeoulParseError, match="RESULT.CODE"):
            await client.traffic_info("link")


@pytest.mark.asyncio
async def test_citydata_info_200_is_an_empty_result(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "RESULT": {
                    "RESULT.CODE": "INFO-200",
                    "RESULT.MESSAGE": "데이터 없음",
                }
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        result = await client.citydata("강남역")

    assert result.items == ()
    assert result.result_code == "INFO-200"


@pytest.mark.asyncio
async def test_all_station_endpoint_requires_opt_in_and_bounds_items(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errorMessage": {"code": "INFO-000", "message": "정상"},
                "realtimeArrivalList": [
                    {"statnNm": "서울"},
                    {"statnNm": "시청"},
                ],
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulConfigurationError, match="명시적으로 활성화"):
            await client.subway_arrivals_all()

    all_config = config.model_copy(
        update={"allow_all_station_arrivals": True, "all_station_arrivals_max_items": 1}
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=all_config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulParseError, match="최대 항목 수"):
            await client.subway_arrivals_all(max_items=999)


@pytest.mark.asyncio
async def test_retry_after_cooldown_is_shared_between_clients(config):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.05"})
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    first_config = config.model_copy(
        update={"max_retries": 0, "general_min_interval_seconds": 0}
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as first_http:
        first = SeoulOpenDataClient(config=first_config, http_client=first_http)
        with pytest.raises(SeoulRateLimitError):
            await first.traffic_info("link")

    started = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(transport=transport) as second_http:
        second = SeoulOpenDataClient(config=first_config, http_client=second_http)
        result = await second.traffic_info("link")
    elapsed = asyncio.get_running_loop().time() - started

    assert result.items[0].link_id == "link"
    assert elapsed >= 0.04


@pytest.mark.asyncio
async def test_application_quota_error_sets_shared_bounded_cooldown():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"RESULT": {"CODE": "ERROR-337", "MESSAGE": "한도 초과"}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    config = SeoulOpenDataConfig(
        api_key="application-quota-key",
        max_retries=0,
        general_min_interval_seconds=0,
        upstream_quota_cooldown_seconds=0.05,
        allow_insecure_http=True,
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as first_http:
        first = SeoulOpenDataClient(config=config, http_client=first_http)
        with pytest.raises(SeoulUpstreamError, match="ERROR-337"):
            await first.traffic_info("link")

    started = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(transport=transport) as second_http:
        second = SeoulOpenDataClient(config=config, http_client=second_http)
        result = await second.traffic_info("link")
    elapsed = asyncio.get_running_loop().time() - started

    assert result.items[0].link_id == "link"
    assert elapsed >= 0.04
    assert calls == 2


@pytest.mark.asyncio
async def test_quota_message_disables_transient_retry():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "RESULT": {
                    "CODE": "ERROR-500",
                    "MESSAGE": "요청 한도를 초과했습니다",
                }
            },
        )

    config = SeoulOpenDataConfig(
        api_key="quota-message-key",
        max_retries=1,
        general_min_interval_seconds=0,
        retry_backoff_seconds=0,
        upstream_quota_cooldown_seconds=0.01,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulUpstreamError, match="ERROR-500"):
            await client.traffic_info("link")

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 503])
async def test_oversized_retry_after_is_rejected_before_sleep(config, status_code):
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, headers={"Retry-After": "9999999"})

    limited_config = config.model_copy(
        update={"max_retries": 1, "retry_backoff_max_seconds": 1.0}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        transport = AsyncSeoulTransport(
            limited_config,
            http_client=http_client,
            sleep=lambda delay: _record_sleep(sleeps, delay),
        )
        async with SeoulOpenDataClient(transport=transport) as client:
            with pytest.raises(SeoulRateLimitError, match="너무 길어"):
                await client.traffic_info("link")

    assert sleeps == []


@pytest.mark.asyncio
async def test_injected_http_client_still_has_a_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={})

    config = SeoulOpenDataConfig(
        api_key="timeout-key",
        timeout_seconds=0.01,
        max_retries=0,
        general_min_interval_seconds=0,
        allow_insecure_http=True,
    )
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulHttpError, match="네트워크"):
            await client.traffic_info("link")


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.UnsupportedProtocol])
async def test_transport_errors_are_normalized_without_key_cause(config, error_type):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("transport failure", request=request)

    no_retry_config = config.model_copy(update={"max_retries": 0})
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=no_retry_config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulHttpError) as error:
            await client.traffic_info("link")

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "unit-fixture-key" not in repr(error.value)
    assert "unit-fixture-key" not in _traceback_locals_repr(error.value)


@pytest.mark.asyncio
async def test_malformed_response_does_not_keep_key_in_parse_cause(config):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"TrafficInfo": "unit-fixture-key",',
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        SeoulOpenDataClient(config=config, http_client=http_client) as client,
    ):
        with pytest.raises(SeoulParseError) as error:
            await client.traffic_info("link")

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "unit-fixture-key" not in repr(error.value)
    assert "unit-fixture-key" not in _traceback_locals_repr(error.value)


@pytest.mark.asyncio
async def test_general_limiter_scope_is_shared_across_subway_credentials():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=(
                "<TrafficInfo><RESULT><CODE>INFO-000</CODE><MESSAGE>정상</MESSAGE>"
                "</RESULT><list_total_count>1</list_total_count>"
                "<row><link_id>link</link_id></row></TrafficInfo>"
            ).encode(),
        )

    def make_config(subway_key: str) -> SeoulOpenDataConfig:
        return SeoulOpenDataConfig(
            api_key="shared-general-credential",
            subway_api_key=subway_key,
            service_daily_budgets={"TrafficInfo": 1},
            general_min_interval_seconds=0,
            realtime_min_interval_seconds=0,
            allow_insecure_http=True,
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as first_http,
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as second_http,
        SeoulOpenDataClient(
            config=make_config("subway-a"), http_client=first_http
        ) as first,
        SeoulOpenDataClient(
            config=make_config("subway-b"), http_client=second_http
        ) as second,
    ):
        await first.traffic_info("link")
        with pytest.raises(SeoulQuotaError, match="일일 호출 예산"):
            await second.traffic_info("link")

    assert calls == 1


def test_static_parking_holiday_and_coordinate_aliases_are_preserved():
    envelope, items = parse_parking_lots(
        {
            "GetParkInfo": {
                "list_total_count": 1,
                "RESULT": {"CODE": "INFO-000", "MESSAGE": "정상"},
                "row": [
                    {
                        "PKLT_CD": "P1",
                        "PKLT_NM": "서울역",
                        "LHLDY_BGNG": "00:00",
                        "LHLDY": "23:59",
                        "LOT": "126.97",
                    }
                ],
            }
        }
    )

    assert envelope.list_total_count == 1
    assert items[0].holiday_open_time == "00:00"
    assert items[0].holiday_close_time == "23:59"
    assert items[0].longitude == 126.97


async def _record_sleep(sleeps: list[float], delay: float) -> None:
    sleeps.append(delay)
