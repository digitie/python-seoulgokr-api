"""환경변수와 호출 제한을 다루는 서울 Open API 설정."""

from __future__ import annotations

import os
import posixpath
import re
from typing import ClassVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from .errors import SeoulConfigurationError

_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED_PATH_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


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

        key: str | SecretStr | None = None
        subway_key: object = None
        values: dict[str, object] = {}
        try:
            key = api_key if api_key is not None else _first_env(cls._KEY_ENV_NAMES)
            subway_key = overrides.pop("subway_api_key", None)
            if subway_key is None:
                subway_key = _first_env(cls._SUBWAY_KEY_ENV_NAMES)
            values = dict(overrides)
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
        finally:
            # Validation errors can be inspected with their traceback.  Do not
            # leave environment/API key strings in this frame's locals.
            api_key = None
            key = None
            subway_key = None
            values.clear()
            overrides.clear()

    @property
    def subway_key(self) -> SecretStr | None:
        return self.subway_api_key or self.api_key

    def validated_copy(_config: SeoulOpenDataConfig) -> SeoulOpenDataConfig:
        """``model_copy(update=...)``로 우회된 값을 실행 전 재검증한다."""

        values: dict[str, object] = {}
        validation_message: str | None = None
        validated: SeoulOpenDataConfig | None = None
        try:
            for field_name in ("api_key", "subway_api_key"):
                secret = getattr(_config, field_name)
                if secret is not None and not isinstance(secret, SecretStr):
                    object.__setattr__(_config, field_name, SecretStr(str(secret)))
            values = _config.model_dump()
            try:
                validated = type(_config).model_validate(values)
            except ValidationError as exc:
                validation_message = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                    for error in exc.errors(include_url=False)
                )
        finally:
            values.clear()
            _config = None  # type: ignore[assignment]
        if validation_message is not None:
            raise ValueError(
                f"서울 Open API 설정이 유효하지 않습니다: {validation_message}"
            )
        assert validated is not None
        return validated

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
    if not value or any(char.isspace() for char in value):
        raise ValueError("base URL은 공백 없이 유효한 URL이어야 합니다")
    # urlsplit treats an empty ``?``/``#`` as an empty query/fragment, but
    # retaining either delimiter changes how the transport appends path parts.
    if "?" in value or "#" in value:
        raise ValueError("base URL에는 userinfo·query·fragment를 넣을 수 없습니다")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.casefold()
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError("base URL의 host/port가 올바르지 않습니다") from exc
    if scheme not in {"http", "https"}:
        raise ValueError("base URL은 http:// 또는 https://로 시작해야 합니다")
    if not hostname:
        raise ValueError("base URL에 host가 필요합니다")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base URL에는 userinfo·query·fragment를 넣을 수 없습니다")

    hostname = hostname.rstrip(".").casefold()
    if not hostname:
        raise ValueError("base URL에 host가 필요합니다")
    try:
        if ":" not in hostname:
            hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("base URL의 host가 올바르지 않습니다") from exc
    if ":" in hostname:
        netloc = f"[{hostname}]"
    else:
        netloc = hostname
    default_port = 80 if scheme == "http" else 443
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"
    path = posixpath.normpath(_canonicalize_path(parsed.path or ""))
    if path == ".":
        path = ""
    else:
        path = f"/{path.lstrip('/')}"
        path = path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _canonicalize_path(path: str) -> str:
    """동일 의미의 unreserved percent-encoding을 하나의 path로 만든다."""

    def replace(match: re.Match[str]) -> str:
        value = chr(int(match.group(1), 16))
        if value in _UNRESERVED_PATH_CHARS:
            return value
        return f"%{match.group(1).upper()}"

    return _PERCENT_ESCAPE.sub(replace, path)


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None
