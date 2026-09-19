"""서울 공영주차장 typed models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParkingRealtime(BaseModel):
    model_config = ConfigDict(extra="allow")

    parking_lot_id: str | None = None
    parking_lot_name: str | None = None
    address: str | None = None
    capacity: int | None = None
    current_vehicle_count: int | None = Field(
        default=None, description="현재 주차 차량 수"
    )
    current_update_time: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)


class ParkingLot(BaseModel):
    model_config = ConfigDict(extra="allow")

    parking_lot_id: str | None = None
    parking_lot_name: str | None = None
    address: str | None = None
    capacity: int | None = None
    operation_type: str | None = None
    weekday_open_time: str | None = None
    weekday_close_time: str | None = None
    saturday_open_time: str | None = None
    saturday_close_time: str | None = None
    holiday_open_time: str | None = None
    holiday_close_time: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    last_data_sync_time: str | None = None
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)
