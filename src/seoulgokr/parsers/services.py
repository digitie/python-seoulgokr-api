"""서비스별 row를 typed model로 변환한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..models.citydata import CityData
from ..models.parking import ParkingLot, ParkingRealtime
from ..models.subway import SubwayArrival, SubwayPosition
from ..models.traffic import TrafficInfo
from .common import (
    ParsedEnvelope,
    bool_value,
    datetime_value,
    extract_citydata_envelope,
    extract_envelope,
    first_value,
    float_value,
    int_value,
    text_value,
)


def parse_traffic_info(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[TrafficInfo, ...]]:
    envelope = extract_envelope(payload, service="TrafficInfo")
    return envelope, tuple(
        TrafficInfo(
            link_id=text_value(row, "link_id", "LINK_ID"),
            process_speed_kph=float_value(row, "prcs_spd", "PRCS_SPD"),
            process_travel_time_seconds=int_value(
                row, "prcs_trv_time", "PRCS_TRV_TIME"
            ),
            raw=dict(row),
        )
        for row in envelope.rows
    )


def parse_subway_arrivals(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[SubwayArrival, ...]]:
    envelope = extract_envelope(payload, service="realtimeStationArrival")
    return envelope, tuple(_arrival(row) for row in envelope.rows)


def parse_subway_positions(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[SubwayPosition, ...]]:
    envelope = extract_envelope(payload, service="realtimePosition")
    return envelope, tuple(
        SubwayPosition(
            subway_id=text_value(row, "subwayId"),
            subway_name=text_value(row, "subwayNm"),
            station_id=text_value(row, "statnId"),
            station_name=text_value(row, "statnNm"),
            train_no=text_value(row, "trainNo"),
            last_received_date=text_value(row, "lastRecptnDt"),
            received_at=datetime_value(row, "recptnDt"),
            updn_line=text_value(row, "updnLine"),
            destination_station_id=text_value(row, "statnTid"),
            destination_name=text_value(row, "statnTnm"),
            train_status=text_value(row, "trainSttus"),
            express=bool_value(row, "directAt"),
            last_car=bool_value(row, "lstcarAt"),
            raw=dict(row),
        )
        for row in envelope.rows
    )


def parse_parking_realtime(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[ParkingRealtime, ...]]:
    envelope = extract_envelope(payload, service="GetParkingInfo")
    return envelope, tuple(
        ParkingRealtime(
            parking_lot_id=text_value(row, "PKLT_CD", "pklt_cd"),
            parking_lot_name=text_value(row, "PKLT_NM", "pklt_nm"),
            address=text_value(row, "ADDR", "addr"),
            capacity=int_value(row, "TPKCT", "tpkct"),
            current_vehicle_count=int_value(
                row, "NOW_PRK_VHCL_CNT", "now_prk_vhcl_cnt"
            ),
            current_update_time=text_value(
                row, "NOW_PRK_VHCL_UPDT_TM", "now_prk_vhcl_updt_tm"
            ),
            latitude=float_value(row, "LAT", "lat", "Y座標"),
            longitude=float_value(row, "LNG", "lng", "X座標"),
            raw=dict(row),
        )
        for row in envelope.rows
    )


def parse_parking_lots(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[ParkingLot, ...]]:
    envelope = extract_envelope(payload, service="GetParkInfo")
    return envelope, tuple(
        ParkingLot(
            parking_lot_id=text_value(row, "PKLT_CD", "pklt_cd"),
            parking_lot_name=text_value(row, "PKLT_NM", "pklt_nm"),
            address=text_value(row, "ADDR", "addr"),
            capacity=int_value(row, "TPKCT", "tpkct"),
            operation_type=text_value(row, "OPRT_STTS", "OPRT_TYPE", "oprt_stts"),
            weekday_open_time=text_value(row, "WD_OPR_STRT_TM", "wd_opr_strt_tm"),
            weekday_close_time=text_value(row, "WD_OPR_END_TM", "wd_opr_end_tm"),
            saturday_open_time=text_value(row, "SAT_OPR_STRT_TM", "sat_opr_strt_tm"),
            saturday_close_time=text_value(row, "SAT_OPR_END_TM", "sat_opr_end_tm"),
            holiday_open_time=text_value(row, "LH_OPR_STRT_TM", "holiday_open_time"),
            holiday_close_time=text_value(row, "LH_OPR_END_TM", "holiday_close_time"),
            latitude=float_value(row, "LAT", "lat"),
            longitude=float_value(row, "LNG", "lng"),
            last_data_sync_time=text_value(
                row, "LAST_DATA_SYNC_TM", "last_data_sync_tm"
            ),
            raw=dict(row),
        )
        for row in envelope.rows
    )


def parse_citydata(
    payload: Mapping[str, Any],
) -> tuple[ParsedEnvelope, tuple[CityData, ...]]:
    envelope = extract_citydata_envelope(payload, service="citydata")
    data = envelope.service_payload
    live_population = first_value(data, "LIVE_PPLTN_STTS")
    live_population_row = (
        live_population[0]
        if isinstance(live_population, list)
        and live_population
        and isinstance(live_population[0], Mapping)
        else live_population
    )
    if not isinstance(live_population_row, Mapping):
        live_population_row = {}
    return envelope, (
        CityData(
            area_name=text_value(data, "AREA_NM", "area_nm"),
            area_code=text_value(data, "AREA_CD", "area_cd"),
            area_congestion_level=text_value(
                live_population_row, "AREA_CONGEST_LV", "AREA_CONGEST_LVL"
            ),
            area_congestion_message=text_value(live_population_row, "AREA_CONGEST_MSG"),
            road_traffic=_raw_block(data, "ROAD_TRAFFIC_STTS", "ROAD_TRAFFIC"),
            parking=_raw_block(data, "PRK_STTS", "PARKING"),
            subway=_raw_block(data, "SUB_STTS", "SUBWAY"),
            raw=dict(data),
        ),
    ) if data else ()


def _arrival(row: Mapping[str, Any]) -> SubwayArrival:
    return SubwayArrival(
        subway_id=text_value(row, "subwayId"),
        subway_name=text_value(row, "subwayNm"),
        updn_line=text_value(row, "updnLine"),
        train_line_name=text_value(row, "trainLineNm"),
        station_id=text_value(row, "statnId"),
        station_name=text_value(row, "statnNm"),
        station_fid=text_value(row, "statnFid"),
        station_tid=text_value(row, "statnTid"),
        destination_name=text_value(row, "bstatnNm", "statnTnm"),
        train_no=text_value(row, "btrainNo", "trainNo"),
        arrival_seconds=int_value(row, "barvlDt"),
        received_at=datetime_value(row, "recptnDt"),
        arrival_message=text_value(row, "arvlMsg1"),
        arrival_message_2=text_value(row, "arvlMsg2"),
        arrival_message_3=text_value(row, "arvlMsg3"),
        arrival_code=text_value(row, "arvlCd"),
        last_car=bool_value(row, "lstcarAt"),
        raw=dict(row),
    )


def _raw_block(mapping: Mapping[str, Any], *names: str) -> Any:
    value = first_value(mapping, *names)
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return [dict(item) if isinstance(item, Mapping) else item for item in value]
    return {}
