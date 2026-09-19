"""환경변수와 호출 제한을 다루는 서울 Open API 설정."""

from __future__ import annotations

import os
from typing import ClassVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .errors import SeoulConfigurationError


class SeoulOpenDataConfig(BaseModel):
    """서울 열린데이터광장 provider의 실행 설정.

    ``data.seoul.go.kr``가 발급한 인증키는 upstream URL path에 들어간다. 따라서
    이 객체는 키를 ``SecretStr``로만 보관하고, transport가 만드는 진단 정보에는
    키를 포함하지 않는다.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    api_key: SecretStr | None = None
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
    realtime_subway_daily_budget: int | None = Field(default=1000, ge=1)
    upstream_quota_cooldown_seconds: float = Field(default=60.0, gt=0, le=86400)
    quota_timezone: str = "Asia/Seoul"
    allow_insecure_http: bool = False
    allow_all_station_arrivals: bool = False
    all_station_arrivals_max_items: int = Field(default=5000, gt=0)
    max_response_bytes: int = Field(
        default=16 * 1024 * 1024, ge=1024, le=128 * 1024 * 1024
    )
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
        return validate_base_url(value)

    @field_validator("service_daily_budgets")
    @classmethod
    def _positive_service_budgets(cls, value: dict[str, int]) -> dict[str, int]:
        if any(budget <= 0 for budget in value.values()):
            raise ValueError("service_daily_budgets 값은 양수여야 합니다")
        return value

    @field_validator("quota_timezone")
    @classmethod
    def _valid_quota_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"알 수 없는 quota timezone입니다: {value}") from exc
        return value

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
        subway_key = overrides.pop("subway_api_key", None)
        if subway_key is None:
            subway_key = _first_env(cls._SUBWAY_KEY_ENV_NAMES)
        values: dict[str, object] = dict(overrides)
        values["api_key"] = key
        if subway_key is not None:
            values["subway_api_key"] = subway_key
        if "allow_insecure_http" not in values:
            insecure = os.getenv("SEOUL_OPEN_DATA_ALLOW_INSECURE_HTTP")
            if insecure is not None:
                values["allow_insecure_http"] = insecure
        if not key and not subway_key:
            names = ", ".join((*cls._KEY_ENV_NAMES, *cls._SUBWAY_KEY_ENV_NAMES[:2]))
            raise SeoulConfigurationError(
                f"서울 Open API 인증키가 없습니다. 다음 환경변수 중 하나를 설정하세요: {names}"
            )
        return cls.model_validate(values)

    @property
    def subway_key(self) -> SecretStr | None:
        return self.subway_api_key or self.api_key

    def policy_for(self, service: str) -> tuple[float, int | None]:
        """서비스별 최소 간격과 애플리케이션 예산을 반환한다."""

        original_service = service
        service = self.quota_group(service)
        realtime = service.startswith("realtime")
        minimum = (
            self.realtime_min_interval_seconds
            if realtime
            else self.general_min_interval_seconds
        )
        budget = self.service_daily_budgets.get(service)
        if budget is None:
            budget = self.service_daily_budgets.get(
                original_service, self.default_daily_budget
            )
        if budget is None and service == "realtimeSubway":
            budget = self.realtime_subway_daily_budget
        return minimum, budget

    @staticmethod
    def quota_group(service: str) -> str:
        if service in {
            "realtimeStationArrival",
            "realtimeStationArrival/ALL",
            "realtimePosition",
        }:
            return "realtimeSubway"
        return service


def validate_base_url(value: str) -> str:
    """Pydantic 검증을 우회한 model_copy 값도 transport 직전에 검증한다."""

    value = value.strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("base URL은 http:// 또는 https://로 시작해야 합니다")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("base URL의 host/port가 올바르지 않습니다") from exc
    if not parsed.hostname:
        raise ValueError("base URL에 host가 필요합니다")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL에는 userinfo·query·fragment를 넣을 수 없습니다")
    return value.rstrip("/")


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
