"""서울 지하철 실시간 typed models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SubwayArrival(BaseModel):
    model_config = ConfigDict(extra="allow")

    subway_id: str | None = None
    subway_name: str | None = None
    updn_line: str | None = None
    train_line_name: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    station_fid: str | None = None
    station_tid: str | None = None
    destination_name: str | None = None
    train_no: str | None = None
    arrival_seconds: int | None = Field(
        default=None, description="barvlDt를 초로 변환한 값"
    )
    received_at: datetime | None = None
    arrival_message: str | None = None
    arrival_message_2: str | None = None
    arrival_message_3: str | None = None
    arrival_code: str | None = None
    last_car: bool | None = None
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)


class SubwayPosition(BaseModel):
    model_config = ConfigDict(extra="allow")

    subway_id: str | None = None
    subway_name: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    train_no: str | None = None
    last_received_date: str | None = None
    received_at: datetime | None = None
    updn_line: str | None = None
    destination_station_id: str | None = None
    destination_name: str | None = None
    train_status: str | None = None
    express: bool | None = None
    last_car: bool | None = None
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)
