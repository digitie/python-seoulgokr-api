from __future__ import annotations

import httpx
import pytest

from seoulgokr import SeoulOpenDataClient
from seoulgokr.errors import SeoulUpstreamError


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
