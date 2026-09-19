"""환경변수와 호출 제한을 다루는 서울 Open API 설정."""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .errors import SeoulConfigurationError


class SeoulOpenDataConfig(BaseModel):
    """서울 열린데이터광장 provider의 실행 설정.

    ``data.seoul.go.kr``가 발급한 인증키는 upstream URL path에 들어간다. 따라서
    이 객체는 키를 ``SecretStr``로만 보관하고, transport가 만드는 진단 정보에는
    키를 포함하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr
    subway_api_key: SecretStr | None = None
    general_base_url: str = "http://openapi.seoul.go.kr:8088"
    subway_base_url: str = "http://swopenAPI.seoul.go.kr/api/subway"
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=60)
    retry_backoff_max_seconds: float = Field(default=10.0, ge=0, le=120)
    general_min_interval_seconds: float = Field(default=1.0, ge=0, le=3600)
    realtime_min_interval_seconds: float = Field(default=30.0, ge=0, le=3600)
    max_concurrency: int = Field(default=1, ge=1, le=20)
    default_daily_budget: int | None = Field(default=None, ge=1)
    service_daily_budgets: dict[str, int] = Field(default_factory=dict)
    user_agent: str = "python-seoulgokr-api/0.1"

    _KEY_ENV_NAMES: ClassVar[tuple[str, ...]] = (
        "SEOUL_OPEN_DATA_API_KEY",
        "KOR_TRAVEL_MAP_API_SEOULGOKR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "DATAGOKR_API_KEY",
        "PUBLIC_DATA_SERVICE_KEY",
        "SERVICE_KEY",
    )
    _SUBWAY_KEY_ENV_NAMES: ClassVar[tuple[str, ...]] = (
        "SEOUL_SUBWAY_API_KEY",
        "KOR_TRAVEL_MAP_API_SEOUL_SUBWAY_SERVICE_KEY",
        "SEOUL_OPEN_DATA_API_KEY",
        "KOR_TRAVEL_MAP_API_SEOULGOKR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "DATAGOKR_API_KEY",
        "PUBLIC_DATA_SERVICE_KEY",
        "SERVICE_KEY",
    )

    @field_validator("general_base_url", "subway_base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("base URL은 http:// 또는 https://로 시작해야 합니다")
        return value.rstrip("/")

    @classmethod
    def from_env(
        cls, *, api_key: str | SecretStr | None = None, **overrides: object
    ) -> SeoulOpenDataConfig:
        """로컬/CI 환경변수에서 설정을 만든다.

        ``kor-travel-map``가 사용하는 공통 service-key 별칭을 지원하지만, 파일을
        읽거나 값을 복사하지 않는다. 명시적인 ``api_key``가 있으면 환경변수보다
        우선한다.
        """

        key = api_key if api_key is not None else _first_env(cls._KEY_ENV_NAMES)
        if not key:
            names = ", ".join(cls._KEY_ENV_NAMES)
            raise SeoulConfigurationError(
                f"서울 Open API 인증키가 없습니다. 다음 환경변수 중 하나를 설정하세요: {names}"
            )
        subway_key = overrides.pop("subway_api_key", None)
        if subway_key is None:
            subway_key = _first_env(cls._SUBWAY_KEY_ENV_NAMES)
        values: dict[str, object] = dict(overrides)
        values["api_key"] = key
        if subway_key is not None:
            values["subway_api_key"] = subway_key
        return cls.model_validate(values)

    @property
    def subway_key(self) -> SecretStr:
        return self.subway_api_key or self.api_key

    def policy_for(self, service: str) -> tuple[float, int | None]:
        """서비스별 최소 간격과 애플리케이션 예산을 반환한다."""

        realtime = service.startswith("realtime")
        minimum = (
            self.realtime_min_interval_seconds
            if realtime
            else self.general_min_interval_seconds
        )
        budget = self.service_daily_budgets.get(service, self.default_daily_budget)
        return minimum, budget


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
