# 서울 Open Data provider 라이브러리 아키텍처

## 목표 경계

```text
소비 애플리케이션
        │ typed result + raw provenance
        ▼
seoulgokr client facade
        ├── source adapter (TrafficInfo / subway / parking / citydata)
        ├── parser (JSON/XML + source-specific fields)
        ├── async transport (httpx injection)
        ├── retry / error normalization
        ├── rate limiter / quota budget
        └── redaction / safe diagnostics
```

이 저장소는 provider 계층까지만 포함한다. 저장·분석·웹 API·scheduler는 소비
프로젝트의 책임이다.

현재 facade는 다음 source를 제공한다.

- `TrafficInfo` (`OA-13291`): link ID별 실시간 도로 속도·통행시간
- `realtimeStationArrival` (`OA-12764`): 역명별 실시간 도착
- `realtimePosition` (`OA-12601`): 공식 노선명별 열차 위치
- `realtimeStationArrival/ALL` (`OA-15799`): 전체역 도착 endpoint
- `GetParkingInfo`/`GetParkInfo` (`OA-21709`/`OA-13122`): 실시간·기준 주차정보
- `citydata` (`OA-21285`): 장소 단위 실시간 도시데이터와 nested block

## 데이터 계약

- upstream service name과 field name을 raw provenance에 남긴다.
- typed model은 안정적으로 소비할 필드만 노출하되, `raw` mapping을 버리지 않는다.
- 필드 추가에 tolerant하고, 필수 필드 누락은 source별 parse error로 명확히 보고한다.
- `observed_at`/`recptnDt`/`CUR_PRK_TIME`과 provider가 요청한 `fetched_at`을 구분한다.
- `list_total_count`는 pagination 계획에 사용하되, 실시간 API에서 과도한 전체 조회를
  유도하지 않도록 caller의 상한을 둔다. 전체역 endpoint는 pagination 없는 upstream
  계약을 따르므로 기본 30초 간격과 daily budget을 적용한다.

## 보안·운영 경계

- API key는 `SecretStr`와 canonical `SEOUL_OPEN_DATA_API_KEY`로 보관하고,
  `kor-travel-map` 공통 별칭을 환경변수에서만 fallback으로 읽는다.
- key가 URL path에 들어가는 upstream 계약은 redacted request descriptor로만 기록한다.
- 공식 문서가 HTTP URL을 제시하므로 실제 운영 전 HTTPS/TLS 보장을 검증한다.
- 모든 외부 호출은 timeout, bounded retry, per-service limiter를 거친다.
- provider는 인증키가 없으면 명확한 configuration error를 내고, 임의의 sample/live
  전환을 하지 않는다.
