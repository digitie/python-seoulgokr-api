"""서울 실시간 도로 소통 typed model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrafficInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    link_id: str | None = Field(default=None, description="서울 교통 표준 링크 ID")
    process_speed_kph: float | None = Field(default=None, description="처리 속도(km/h)")
    process_travel_time_seconds: int | None = Field(
        default=None, description="처리 통행시간(초)"
    )
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)
