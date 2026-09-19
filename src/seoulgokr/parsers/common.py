"""JSON/XML envelope와 느슨한 정부 API 값 변환."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

from ..errors import (
    TRANSIENT_UPSTREAM_CODES,
    SeoulParseError,
    SeoulUpstreamError,
)

KOREA_TZ = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ParsedEnvelope:
    payload: Mapping[str, Any]
    service_payload: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    list_total_count: int | None
    result_code: str | None
    result_message: str | None


def parse_payload(content: bytes, *, content_type: str = "") -> Mapping[str, Any]:
    """응답 body를 JSON/XML 모두 mapping으로 변환한다."""

    try:
        text = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise SeoulParseError("서울 Open API 응답이 UTF-8이 아닙니다") from exc
    if not text:
        raise SeoulParseError("서울 Open API가 빈 응답을 반환했습니다")
    looks_xml = "xml" in content_type.lower() or text.startswith("<")
    if not looks_xml:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SeoulParseError(f"JSON 응답을 해석할 수 없습니다: {exc}") from exc
        if not isinstance(value, Mapping):
            raise SeoulParseError("JSON 응답 최상위가 object가 아닙니다")
        return dict(value)
    try:
        root = SafeET.fromstring(text)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise SeoulParseError(f"XML 응답을 해석할 수 없습니다: {exc}") from exc
    return {strip_tag(root.tag): _xml_value(root)}


def extract_envelope(payload: Mapping[str, Any], *, service: str) -> ParsedEnvelope:
    service_payload = _unwrap_service(payload, service)
    if not _has_envelope_marker(payload, service_payload, service=service):
        raise SeoulParseError(
            f"{service} 응답에 서울 Open API envelope 표식이 없습니다"
        )
    result_code, result_message = _extract_result(payload, service_payload)
    if result_code is None:
        raise SeoulParseError(f"{service} 응답에 RESULT.CODE가 없습니다")
    list_total_count = _list_total_count(payload, service_payload)
    rows = _extract_rows(service_payload)
    if result_code and result_code != "INFO-000":
        if result_code == "INFO-200":
            rows = ()
        else:
            raise SeoulUpstreamError(
                result_code,
                result_message or "서울 Open API가 오류를 반환했습니다",
                service=service,
                retryable=result_code in TRANSIENT_UPSTREAM_CODES,
            )
    if result_code != "INFO-200" and not _has_data_marker(payload, service_payload):
        raise SeoulParseError(
            f"{service} INFO-000 응답에 list/row 데이터 표식이 없습니다"
        )
    return ParsedEnvelope(
        payload=payload,
        service_payload=service_payload,
        rows=rows,
        list_total_count=list_total_count,
        result_code=result_code,
        result_message=result_message,
    )


def extract_citydata_envelope(
    payload: Mapping[str, Any], *, service: str
) -> ParsedEnvelope:
    """row가 없는 citydata 응답도 공통 오류 규칙으로 검사한다."""

    service_payload = _unwrap_service(payload, service)
    if not _has_citydata_marker(payload, service_payload):
        raise SeoulParseError(
            "citydata 응답에 CITYDATA 또는 서울 Open API 결과 표식이 없습니다"
        )
    result_code, result_message = _extract_result(payload, service_payload)
    if result_code is None:
        raise SeoulParseError("citydata 응답에 RESULT.CODE가 없습니다")
    if result_code not in {"INFO-000", "INFO-200"}:
        raise SeoulUpstreamError(
            result_code,
            result_message or "서울 Open API가 오류를 반환했습니다",
            service=service,
            retryable=result_code in TRANSIENT_UPSTREAM_CODES,
        )
    return ParsedEnvelope(
        payload=payload,
        service_payload=service_payload,
        rows=(),
        list_total_count=_list_total_count(payload, service_payload),
        result_code=result_code,
        result_message=result_message,
    )


def text_value(row: Mapping[str, Any], *names: str) -> str | None:
    value = first_value(row, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def int_value(row: Mapping[str, Any], *names: str) -> int | None:
    return _int_or_none(first_value(row, *names))


def float_value(row: Mapping[str, Any], *names: str) -> float | None:
    value = first_value(row, *names)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def bool_value(row: Mapping[str, Any], *names: str) -> bool | None:
    value = first_value(row, *names)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "y", "yes", "예"}


def datetime_value(row: Mapping[str, Any], *names: str) -> datetime | None:
    value = text_value(row, *names)
    if not value:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=KOREA_TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=KOREA_TZ)
    except ValueError:
        return None


def first_value(mapping: Mapping[str, Any], *names: str) -> Any:
    normalized = {_normalize_key(str(key)): value for key, value in mapping.items()}
    for name in names:
        key = _normalize_key(name)
        if key in normalized:
            return normalized[key]
    return None


def _unwrap_service(payload: Mapping[str, Any], service: str) -> Mapping[str, Any]:
    direct = first_value(payload, service)
    if isinstance(direct, Mapping):
        return direct
    if len(payload) == 1:
        only = next(iter(payload.values()))
        if isinstance(only, Mapping):
            return only
    return payload


def _has_envelope_marker(
    payload: Mapping[str, Any], service_payload: Mapping[str, Any], *, service: str
) -> bool:
    if isinstance(first_value(payload, service), Mapping):
        return bool(service_payload)
    for name in (
        "RESULT",
        "errorMessage",
        "list_total_count",
        "totalCount",
        "row",
        "realtimeArrivalList",
        "realtimePositionList",
        "GetParkingInfo",
        "GetParkInfo",
    ):
        if first_value(payload, name) is not None:
            return True
        if (
            service_payload is payload
            and first_value(service_payload, name) is not None
        ):
            return True
    return False


def _has_citydata_marker(
    payload: Mapping[str, Any], service_payload: Mapping[str, Any]
) -> bool:
    if isinstance(first_value(payload, "CITYDATA"), Mapping):
        return True
    for name in (
        "RESULT",
        "errorMessage",
        "list_total_count",
        "AREA_NM",
        "LIVE_PPLTN_STTS",
        "ROAD_TRAFFIC_STTS",
        "PRK_STTS",
        "SUB_STTS",
    ):
        if first_value(payload, name) is not None:
            return True
        if (
            service_payload is payload
            and first_value(service_payload, name) is not None
        ):
            return True
    return False


def _has_data_marker(
    payload: Mapping[str, Any], service_payload: Mapping[str, Any]
) -> bool:
    for name in (
        "list_total_count",
        "totalCount",
        "total",
        "row",
        "realtimeArrivalList",
        "realtimePositionList",
    ):
        if first_value(payload, name) is not None:
            return True
        if first_value(service_payload, name) is not None:
            return True
    return False


def _extract_result(
    payload: Mapping[str, Any], service_payload: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    candidates = (
        _mapping_value(service_payload, "RESULT"),
        _mapping_value(payload, "RESULT"),
        _mapping_value(service_payload, "errorMessage"),
        _mapping_value(payload, "errorMessage"),
    )
    for result in candidates:
        if result is not None:
            code = text_value(
                result, "CODE", "code", "statusCode", "status", "RESULT.CODE"
            )
            message = text_value(result, "MESSAGE", "message", "RESULT.MESSAGE")
            if code:
                return code, message
    direct_code = text_value(
        service_payload, "RESULT.CODE", "RESULT_CODE", "resultCode"
    ) or text_value(payload, "RESULT.CODE", "RESULT_CODE", "resultCode")
    direct_message = text_value(
        service_payload, "RESULT.MESSAGE", "RESULT_MESSAGE", "resultMessage"
    ) or text_value(payload, "RESULT.MESSAGE", "RESULT_MESSAGE", "resultMessage")
    if direct_code:
        return direct_code, direct_message
    code = text_value(service_payload, "code", "CODE") or text_value(
        payload, "code", "CODE"
    )
    message = text_value(service_payload, "message", "MESSAGE") or text_value(
        payload, "message", "MESSAGE"
    )
    return code, message


def _extract_rows(service_payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for name in (
        "row",
        "realtimeArrivalList",
        "realtimePositionList",
        "GetParkingInfo",
        "GetParkInfo",
    ):
        value = first_value(service_payload, name)
        if value is None:
            continue
        if isinstance(value, Mapping):
            return (value,)
        if isinstance(value, list):
            if any(not isinstance(item, Mapping) for item in value):
                raise SeoulParseError(f"{name} row에 object가 아닌 항목이 있습니다")
            return tuple(value)
        raise SeoulParseError(f"{name} row가 object/list가 아닙니다")
    return ()


def _mapping_value(mapping: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    value = first_value(mapping, name)
    return value if isinstance(value, Mapping) else None


def _first_value(mapping: Mapping[str, Any], *names: str) -> Any:
    return first_value(mapping, *names)


def _list_total_count(
    payload: Mapping[str, Any], service_payload: Mapping[str, Any]
) -> int | None:
    value = _first_value(
        service_payload, "list_total_count", "totalCount", "total", "TOTAL_COUNT"
    )
    if value is None:
        value = _first_value(payload, "list_total_count", "totalCount", "total")
    if value is None:
        for result_name in ("errorMessage", "RESULT"):
            result_mapping = _mapping_value(payload, result_name)
            if result_mapping is not None:
                value = _first_value(
                    result_mapping, "list_total_count", "totalCount", "total"
                )
                if value is not None:
                    break
    return _int_or_none(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def strip_tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _xml_value(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return (element.text or "").strip()
    result: dict[str, Any] = {}
    for child in children:
        key = strip_tag(child.tag)
        value = _xml_value(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result
