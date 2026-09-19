"""서울 열린데이터광장 교통정보 API facade."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Self, TypeVar

import httpx

from .config import SeoulOpenDataConfig
from .errors import SeoulUpstreamError
from .models import (
    CityData,
    ParkingLot,
    ParkingRealtime,
    SeoulApiResult,
    SubwayArrival,
    SubwayPosition,
    TrafficInfo,
)
from .parsers import (
    ParsedEnvelope,
    parse_citydata,
    parse_parking_lots,
    parse_parking_realtime,
    parse_payload,
    parse_subway_arrivals,
    parse_subway_positions,
    parse_traffic_info,
)
from .transport import AsyncSeoulTransport

T = TypeVar("T")


class SeoulOpenDataClient:
    """서울 교통 관련 OpenAPI를 typed result로 제공한다.

    provider는 저장소나 scheduler를 소유하지 않는다. 호출자는 반환된
    ``SeoulApiResult.items``와 ``raw_payload``를 필요한 DB에 적재할 수 있다.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        subway_api_key: str | None = None,
        config: SeoulOpenDataConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
        transport: AsyncSeoulTransport | None = None,
    ) -> None:
        if config is None:
            config = SeoulOpenDataConfig.from_env(
                api_key=api_key, subway_api_key=subway_api_key
            )
        elif api_key is not None or subway_api_key is not None:
            raise ValueError(
                "config과 api_key/subway_api_key를 동시에 지정할 수 없습니다"
            )
        self.config = config
        self.transport = transport or AsyncSeoulTransport(
            config, http_client=http_client
        )
        self._owns_transport = transport is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._owns_transport:
            await self.transport.aclose()

    async def traffic_info(
        self,
        link_id: str,
        *,
        start_index: int = 1,
        end_index: int = 5,
        response_format: str = "xml",
    ) -> SeoulApiResult[TrafficInfo]:
        """`OA-13291` 서울시 실시간 도로 소통 정보를 조회한다."""

        return await self._query(
            source_id="OA-13291",
            service="TrafficInfo",
            parser=parse_traffic_info,
            api="general",
            response_format=response_format,
            start_index=start_index,
            end_index=end_index,
            filter_value=link_id,
        )

    async def subway_arrivals(
        self,
        station_name: str,
        *,
        start_index: int = 0,
        end_index: int = 5,
        response_format: str = "json",
    ) -> SeoulApiResult[SubwayArrival]:
        """`OA-12764` 역명 기준 서울 지하철 실시간 도착정보를 조회한다."""

        return await self._query(
            source_id="OA-12764",
            service="realtimeStationArrival",
            parser=parse_subway_arrivals,
            api="subway",
            response_format=response_format,
            start_index=start_index,
            end_index=end_index,
            filter_value=station_name,
        )

    async def subway_arrivals_all(
        self,
        *,
        response_format: str = "json",
    ) -> SeoulApiResult[SubwayArrival]:
        """`OA-15799` 전체역 도착 API를 조회한다.

        이 endpoint는 일반 역조회와 달리 문서 샘플이 pagination segment 없는
        ``realtimeStationArrival/ALL`` 형태다. 반환 건수가 클 수 있으므로 호출
        간격과 일일 예산을 반드시 운영 설정으로 지정해야 한다.
        """

        return await self._query(
            source_id="OA-15799",
            service="realtimeStationArrival/ALL",
            parser=parse_subway_arrivals,
            api="subway",
            response_format=response_format,
            include_pagination=False,
        )

    async def subway_positions(
        self,
        line_name: str,
        *,
        start_index: int = 0,
        end_index: int = 5,
        response_format: str = "json",
    ) -> SeoulApiResult[SubwayPosition]:
        """`OA-12601` 공식 지하철 노선명 기준 열차 위치를 조회한다."""

        return await self._query(
            source_id="OA-12601",
            service="realtimePosition",
            parser=parse_subway_positions,
            api="subway",
            response_format=response_format,
            start_index=start_index,
            end_index=end_index,
            filter_value=line_name,
        )

    async def parking_realtime(
        self,
        address: str = "",
        *,
        start_index: int = 1,
        end_index: int = 1000,
        response_format: str = "json",
    ) -> SeoulApiResult[ParkingRealtime]:
        """`OA-21709` 서울시 공영주차장 실시간 주차대수를 조회한다."""

        return await self._query(
            source_id="OA-21709",
            service="GetParkingInfo",
            parser=parse_parking_realtime,
            api="general",
            response_format=response_format,
            start_index=start_index,
            end_index=end_index,
            filter_value=address,
        )

    async def parking_lots(
        self,
        address: str = "",
        *,
        start_index: int = 1,
        end_index: int = 1000,
        response_format: str = "json",
    ) -> SeoulApiResult[ParkingLot]:
        """`OA-13122` 서울시 공영주차장 기준정보를 조회한다."""

        return await self._query(
            source_id="OA-13122",
            service="GetParkInfo",
            parser=parse_parking_lots,
            api="general",
            response_format=response_format,
            start_index=start_index,
            end_index=end_index,
            filter_value=address,
        )

    async def citydata(
        self,
        area_name: str,
        *,
        response_format: str = "json",
    ) -> SeoulApiResult[CityData]:
        """`OA-21285` 장소 하나의 서울 실시간 도시데이터를 조회한다."""

        return await self._query(
            source_id="OA-21285",
            service="citydata",
            parser=parse_citydata,
            api="general",
            response_format=response_format,
            start_index=1,
            end_index=5,
            filter_value=area_name,
        )

    async def _query(
        self,
        *,
        source_id: str,
        service: str,
        parser: Callable[[Mapping[str, Any]], tuple[ParsedEnvelope, tuple[T, ...]]],
        **request_kwargs: Any,
    ) -> SeoulApiResult[T]:
        """transport 오류와 HTTP 200 application-level 일시 오류를 함께 처리한다."""

        transient_codes = {"ERROR-500", "ERROR-600", "ERROR-601"}
        for attempt in range(self.config.max_retries + 1):
            response = await self.transport.request(service=service, **request_kwargs)
            try:
                payload = parse_payload(
                    response.content, content_type=response.content_type
                )
                envelope, items = parser(payload)
            except SeoulUpstreamError as exc:
                exc.request = dict(response.request)
                if (
                    exc.code not in transient_codes
                    or attempt >= self.config.max_retries
                ):
                    raise
                delay = min(
                    self.config.retry_backoff_seconds * (2**attempt),
                    self.config.retry_backoff_max_seconds,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            return _result(source_id, service, response, envelope, items)
        raise RuntimeError("서울 Open API query loop가 예기치 않게 종료되었습니다")


def _result(
    source_id: str,
    service: str,
    response: Any,
    envelope: Any,
    items: tuple[T, ...],
) -> SeoulApiResult[T]:
    return SeoulApiResult(
        source_id=source_id,
        service=service,
        items=items,
        list_total_count=envelope.list_total_count,
        result_code=envelope.result_code,
        result_message=envelope.result_message,
        fetched_at=response.fetched_at,
        request=response.request,
        raw_payload=envelope.payload,
    )
