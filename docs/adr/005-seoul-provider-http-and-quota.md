# ADR-005 서울 provider의 HTTP 전송과 quota 보호

## 상태

승인됨 — 2026-09-19

## 결정

- 공식 문서가 `http://` endpoint를 제시하는 서울 OpenAPI는 provider 기본 설정에서
  차단한다.
- backend egress 또는 HTTPS proxy를 운영자가 신뢰하는 경우에만
  `allow_insecure_http=True`를 명시해 opt-in한다. 브라우저에서 key를 직접 호출하지
  않는다.
- 공개되지 않은 서비스별 일 quota는 코드에서 추정하지 않는다. 일반 서비스의 기본
  daily budget은 무제한이며, 소비자가 `service_daily_budgets`로 자체 예산을 설정한다.
- 서울시 이용안내에 명시된 실시간 지하철 일 최대 1,000건은
  `realtime_subway_daily_budget` 기본값으로 적용하고 도착·위치·전체역 endpoint가
  `realtimeSubway` limiter group을 공유한다.
- 실시간 지하철의 보수적 기본 간격은 30초로 둔다. 전체역 도착은 기본 비활성이고,
  명시적 opt-in과 `all_station_arrivals_max_items` 상한이 모두 필요하다.
- 429의 `Retry-After`는 동일 credential·endpoint·이벤트 루프의 limiter에 공유 cooldown으로
  기록한다. 지정 시간이 client backoff 상한보다 길면 자동 재시도하지 않는다. 동일 scope의
  호출 정책이 충돌하면 limiter가 조용히 분리되지 않고 configuration error를 반환한다.
- 5xx를 마지막 재시도에서 반환할 때도 upstream `Retry-After`와 상태 코드를
  `SeoulRateLimitError`에 보존한다. 호출자가 다음 backoff를 판단할 수 있어야 한다.
- `max_retries`는 하나의 논리 호출에 대한 단일 예산으로 관리한다. transport의 HTTP 재시도와
  client의 HTTP 200 application-level transient 재시도가 각각 전체 예산을 소비하므로,
  계층을 겹쳐 호출 수가 곱해지지 않는다.
- application-level `ERROR-337` 또는 명시적인 quota 문구는 자동 재시도하지 않고
  `upstream_quota_cooldown_seconds`만큼 bounded cooldown을 기록한다.
- 응답 body는 `max_response_bytes`(기본 16 MiB)로 제한하고, `max_items`는 row를 typed
  model로 변환하기 전에 검사한다. 페이지 범위·sample capability 오류는 일일 quota와
  구분해 `SeoulConfigurationError`로 반환한다.
- paginated endpoint는 upstream이 요청한 범위를 넘어 반환한 row도 페이지 크기 상한으로
  거부한다.
- 동일 limiter의 cooldown deadline은 더 늦게 설정된 값이 이전 waiter에 의해 지워지지
  않도록 재검사하며, 공유 limiter의 `max_concurrency` 정책은 scope에 고정한다.
- limiter의 shared registry는 이벤트 루프를 소유자로 삼고 module-level에는 약한 참조만
  둔다. 따라서 semaphore가 닫힌 loop를 참조하더라도 registry가 loop 수명을 연장하지
  않는다. `quota_timezone`은 credential scope를 분리하는 키가 아니며, 같은 scope에서
  설정이 다르면 명시적인 configuration error를 반환한다.
- URL canonicalization 후 credential·endpoint scope를 계산해 host 대소문자, 기본 port,
  trailing slash, dot-segment, unreserved percent-encoding 같은 표현 차이로 quota가
  분리되지 않게 한다.
- transport/client 경계에서 `model_copy(update=...)`로 검증을 우회한 설정도 다시 검증하고,
  호출마다 현재 credential·endpoint·동시성 정책으로 limiter를 재확인한다. 따라서 mutable
  config 변경이 stale limiter를 조용히 재사용하거나 quota를 우회하지 않는다.
- 설정 재검증 오류는 원래 Pydantic 예외 context를 그대로 노출하지 않고 안전한 오류로
  재생성한다. path의 raw·percent-encoded 인증키 표현은 대소문자 변형을 포함해 redaction한다.

## 근거

서울 이용약관은 서비스별 이용 시간·횟수 제한과 비정상 사용 시 key 제한 가능성을
명시하지만, 모든 서비스의 구체적인 quota와 reset 시각을 공통으로 공개하지 않는다.
따라서 명세에서 확인한 페이지 상한과 실시간 지하철 안내만 계약으로 고정하고, 나머지는
신청 후 운영 확인 대상으로 남긴다.

## 결과

호출자는 HTTP 차단 오류와 application-level quota 오류를 구분할 수 있고, provider는
key를 가진 URL을 redacted provenance로만 반환한다. 실제 인증키 신청 후 서비스별 quota가
확인되면 소비 프로젝트의 설정값만 조정하며, provider의 추정값을 사실로 바꾸지 않는다.
다중 프로세스/이벤트 루프 배포에는 별도 distributed limiter가 필요하다.
