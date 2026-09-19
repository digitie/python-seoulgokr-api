"""서울 실시간 도시데이터의 보수적 typed model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CityData(BaseModel):
    """장소 단위 도시데이터.

    도시데이터는 여러 block이 동시에 변경될 수 있으므로 교통·주차·지하철
    세부 필드는 raw mapping을 보존하며, 안정적인 장소 식별자만 최상위에 둔다.
    """

    model_config = ConfigDict(extra="allow")

    area_name: str | None = None
    area_code: str | None = None
    area_congestion_level: str | None = None
    area_congestion_message: str | None = None
    road_traffic: Any = Field(default_factory=dict)
    parking: Any = Field(default_factory=dict)
    subway: Any = Field(default_factory=dict)
    raw: Mapping[str, Any] = Field(default_factory=dict, exclude=True)
