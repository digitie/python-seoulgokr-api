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
  기록한다. 지정 시간이 client backoff 상한보다 길면 자동 재시도하지 않는다.
- application-level `ERROR-337` 또는 명시적인 quota 문구는 자동 재시도하지 않고
  `upstream_quota_cooldown_seconds`만큼 bounded cooldown을 기록한다.

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
