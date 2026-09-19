"""서울 열린데이터광장 교통정보 API facade."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Self, TypeVar

import httpx

from .config import SeoulOpenDataConfig
from .errors import (
    SeoulConfigurationError,
    SeoulParseError,
    SeoulUpstreamError,
    is_upstream_quota_error,
)
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
from .redaction import redact_value
from .transport import AsyncSeoulTransport, TransportResponse

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
        if transport is not None:
            if api_key is not None or subway_api_key is not None:
                raise ValueError(
                    "transport와 api_key/subway_api_key를 동시에 지정할 수 없습니다"
                )
            if config is None:
                config = transport.config
            elif config != transport.config:
                raise ValueError("config와 transport.config가 일치해야 합니다")
        elif config is None:
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

        response_format = _normalize_response_format(
            response_format, allowed={"xml"}, service="TrafficInfo"
        )

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

        response_format = _normalize_response_format(
            response_format, allowed={"json", "xml"}, service="realtimeStationArrival"
        )

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
        max_items: int | None = None,
    ) -> SeoulApiResult[SubwayArrival]:
        """`OA-15799` 전체역 도착 API를 조회한다.

        이 endpoint는 일반 역조회와 달리 문서 샘플이 pagination segment 없는
        ``realtimeStationArrival/ALL`` 형태다. 반환 건수가 클 수 있으므로 호출
        간격과 일일 예산을 반드시 운영 설정으로 지정해야 한다.
        """

        response_format = _normalize_response_format(
            response_format,
            allowed={"json", "xml"},
            service="realtimeStationArrival/ALL",
        )
        if not self.config.allow_all_station_arrivals:
            raise SeoulConfigurationError(
                "전체역 도착 API는 allow_all_station_arrivals=True로 명시적으로 활성화해야 합니다"
            )
        if (
            self.config.subway_key is not None
            and self.config.subway_key.get_secret_value() == "sample"
        ):
            raise SeoulConfigurationError(
                "sample 지하철 키로는 전체역 도착 API를 사용할 수 없습니다"
            )
        if max_items is not None and max_items <= 0:
            raise SeoulConfigurationError("max_items는 양수여야 합니다")
        effective_max_items = min(
            max_items or self.config.all_station_arrivals_max_items,
            self.config.all_station_arrivals_max_items,
        )

        return await self._query(
            source_id="OA-15799",
            service="realtimeStationArrival/ALL",
            parser=parse_subway_arrivals,
            api="subway",
            response_format=response_format,
            include_pagination=False,
            max_items=effective_max_items,
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

        response_format = _normalize_response_format(
            response_format, allowed={"json", "xml"}, service="realtimePosition"
        )

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

        response_format = _normalize_response_format(
            response_format, allowed={"json", "xml"}, service="GetParkingInfo"
        )

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

        response_format = _normalize_response_format(
            response_format, allowed={"json", "xml"}, service="GetParkInfo"
        )

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

        response_format = _normalize_response_format(
            response_format, allowed={"json", "xml"}, service="citydata"
        )

        if (
            self.config.api_key is not None
            and self.config.api_key.get_secret_value() == "sample"
        ):
            raise SeoulConfigurationError(
                "sample 일반 키는 citydata의 요청 장소를 보장하지 않으므로 사용할 수 없습니다"
            )

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
        parser: Callable[..., tuple[ParsedEnvelope, tuple[T, ...]]],
        api: str,
        max_items: int | None = None,
        **request_kwargs: Any,
    ) -> SeoulApiResult[T]:
        """transport 오류와 HTTP 200 application-level 일시 오류를 함께 처리한다."""

        response: TransportResponse | None = None
        for attempt in range(self.config.max_retries + 1):
            response = await self.transport.request(
                service=service, api=api, **request_kwargs
            )
            recursion_error = False
            try:
                payload = redact_value(
                    parse_payload(response.content, content_type=response.content_type),
                    self._secret_values(),
                )
                effective_max_items = max_items
                if effective_max_items is None:
                    effective_max_items = _paginated_response_limit(
                        api=api, request_kwargs=request_kwargs
                    )
                envelope, items = parser(payload, max_items=effective_max_items)
            except RecursionError:
                recursion_error = True
            except SeoulParseError:
                # Do not retain a raw response object in traceback frame locals.
                response = None
                payload = {}
                raise
            except SeoulUpstreamError as exc:
                exc.request = dict(response.request)
                quota_error = is_upstream_quota_error(exc.code, exc.message)
                if quota_error:
                    self.transport.mark_cooldown(
                        api=api,
                        service=service,
                        delay_seconds=self.config.upstream_quota_cooldown_seconds,
                    )
                if (
                    quota_error
                    or not exc.retryable
                    or attempt >= self.config.max_retries
                ):
                    response = None
                    payload = {}
                    raise
                response = None
                payload = {}
                delay = min(
                    self.config.retry_backoff_seconds * (2**attempt),
                    self.config.retry_backoff_max_seconds,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            if recursion_error:
                response = None
                payload = {}
                raise SeoulParseError(
                    f"{service} 응답이 허용된 중첩 깊이를 초과했습니다"
                )
            assert response is not None
            return _result(source_id, service, response, envelope, items)
        raise RuntimeError("서울 Open API query loop가 예기치 않게 종료되었습니다")

    def _secret_values(self) -> tuple[str, ...]:
        """redaction 동안에만 평문 키를 만들고 객체 속성에는 보관하지 않는다."""

        return tuple(
            secret.get_secret_value()
            for secret in (self.config.api_key, self.config.subway_key)
            if secret is not None
        )


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


def _normalize_response_format(value: str, *, allowed: set[str], service: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise SeoulConfigurationError(
            f"{service} response_format은 {allowed_text} 중 하나여야 합니다"
        )
    return normalized


def _paginated_response_limit(
    *, api: str, request_kwargs: Mapping[str, Any]
) -> int | None:
    """페이지 계약보다 큰 upstream row 응답을 typed 변환 전에 차단한다."""

    if request_kwargs.get("include_pagination", True) is False:
        return None
    start_index = request_kwargs.get("start_index")
    end_index = request_kwargs.get("end_index")
    if not isinstance(start_index, int) or not isinstance(end_index, int):
        return None
    return end_index - start_index + (1 if api == "general" else 0)
