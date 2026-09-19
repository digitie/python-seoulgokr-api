"""모든 서울 API 호출 결과가 공유하는 provenance 모델."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SeoulApiResult(Generic[T]):
    source_id: str
    service: str
    items: tuple[T, ...]
    list_total_count: int | None
    result_code: str | None
    result_message: str | None
    fetched_at: datetime
    request: Mapping[str, str]
    raw_payload: Mapping[str, Any]

    def __len__(self) -> int:
        return len(self.items)
