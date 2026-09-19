# python-seoulgokr-api 구현 계획

## 1. 목표와 현재 상태

이 프로젝트의 목표는 `data.seoul.go.kr` 및 서울 열린데이터광장의 교통 관련
OpenAPI를 안전하게 호출하는 비동기 Python provider 라이브러리를 만드는 것이다.
국내 여행 서비스가 서울의 도로 소통, 지하철 도착·열차 위치, 서울 주요 장소의
교통·주차 현황을 typed model로 소비할 수 있어야 한다.

현재 1차 provider 구현과 공개 `sample` key live smoke가 완료됐다. 실키 값은 사용하거나
저장하지 않았고, 계약 검증은 key 없는 mock fixture로 수행했다.

## 2. 범위

### 1차 구현 대상

1. 공통 서울 Open API URL/인증/응답 envelope 처리
2. `OA-13291` `TrafficInfo`
3. `OA-12764` `realtimeStationArrival`
4. `OA-12601` `realtimePosition`
5. `OA-15799` `realtimeStationArrival/ALL` (명세 재확인 후)
6. `OA-21709` `GetParkingInfo`
7. `OA-13122` `GetParkInfo`
8. `OA-21285` `citydata`

### 명시적 비범위

- FastAPI/Next.js 웹앱, PostgreSQL schema, Alembic migration
- 데이터 수집 scheduler나 장기 저장소
- 경로 탐색·요금 계산·지도 UI
- data.go.kr의 버스 API를 서울 API의 일부로 추측해 구현하는 것
- 실키를 fixture, 로그, 문서, Git history에 저장하는 것

후속 소비 프로젝트가 저장·분석을 원하면 provider의 raw/typed 결과를 입력으로
사용하고, provider 안에 소비 프로젝트의 DB 모델을 끌어오지 않는다.

## 3. 모듈 경계(계획)

현재 구현은 다음 경계를 작은 모듈로 나눈다.

```text
src/seoulgokr/
├── config.py          # SecretStr 기반 설정, endpoint와 기본 timeout
├── client.py          # 외부에 노출하는 async client/context manager
├── transport.py       # httpx 주입, timeout, 응답 본문 수집
├── models/
│   ├── common.py      # RESULT/errorMessage, list_total_count, provenance 메타데이터
│   ├── traffic.py     # TrafficInfo typed model
│   ├── subway.py      # 도착·열차 위치 model
│   ├── parking.py     # GetParkInfo/GetParkingInfo model
│   └── citydata.py    # citydata의 장소·교통·주차 부분 model
├── parsers/
│   ├── common.py      # JSON/XML envelope 및 숫자/빈 문자열 변환
│   └── ...            # API별 필드 정규화
├── rate_limit.py     # service/key별 동시성·간격·quota budget
├── errors.py          # HTTP·upstream·quota·parse 예외
└── redaction.py      # URL/headers/본문 로그 마스킹
```

`client.py`는 API별 facade를 제공하되 HTTP와 parsing을 직접 섞지 않는다.
`transport.py`는 테스트에서 fake/MockTransport로 교체할 수 있어야 한다.

## 4. typed model과 raw 보존

- 모든 typed model은 upstream 필드명을 처음부터 임의로 번역하지 않는다.
- 숫자처럼 보이는 값도 빈 문자열, `null`, 비정상 문자열을 허용할 수 있도록
  source별 coercion 정책을 명시한다.
- 알 수 없는 필드는 버리지 않고 raw mapping에 보존한다. upstream이 필드를
  추가해도 파싱이 즉시 깨지지 않아야 한다.
- 호출 결과는 `typed`와 `raw`를 함께 가지는 결과 객체로 설계한다.
- `SeoulApiResult`에는 서비스명, 요청 범위, 수집 시각과 파싱된 원문 mapping을
  보존한다. `KEY`가 포함된 실제 URL은 redacted URL로만 반환하며 raw payload에도
  키를 넣지 않는다.
- 응답의 `RESULT.CODE`/`RESULT.MESSAGE`가 HTTP 200 안에 오류를 표현할 수 있으므로
  HTTP 상태만으로 성공을 판단하지 않는다.
- provider는 DB에 저장하지 않는다. 저장이 필요한 소비자가 raw/typed 결과와
  provenance를 선택적으로 적재한다.

## 5. 비동기 HTTP와 장애 처리

- `httpx.AsyncClient`를 주입받고 `async with` 수명주기를 명확히 한다.
- connect/read/write/pool timeout을 분리하거나 최소한 명시적인 전체 timeout을
  둔다. 무한 대기는 허용하지 않는다.
- 재시도 대상은 네트워크 timeout/connection 오류, HTTP 429, 일부 HTTP 5xx로
  제한한다.
- 인증 실패, 잘못된 path/type/service, 필수 파라미터 누락, 응답 parsing 오류는
  무조건 재시도하지 않는다.
- 지수 backoff와 jitter를 사용하고, `Retry-After`가 있으면 우선 반영한다.
- 최대 시도 횟수·총 대기 상한을 설정으로 제한한다.
- `ERROR-500`, `ERROR-600`, `ERROR-601` 같은 application-level 장애 코드와
  HTTP 장애를 별도로 기록한다.
- 장애 결과에는 source id, service, sanitized request descriptor, upstream code,
  `retryable`·`retry_after` 같은 공개 오류 속성을 넣되 인증키는 절대 포함하지 않는다.

## 6. 호출 제한과 quota 보호

- 공통 페이지 상한은 공식 명세의 최대 1,000건을 기본값으로 삼고, `sample` 키의
  최대 5건 제한을 fixture/contract test에 고정한다.
- 실시간 지하철의 공식 안내에는 일 최대 1,000건 요청이 표시되어 있다. 다른
  서비스의 일 quota·rate limit은 조사 시점에 공식적으로 확인되지 않았으므로
  수치로 가정하지 않는다. provider는 `realtime_subway_daily_budget` 기본값으로
  실시간 지하철 상한만 적용한다.
- service/key 조합별 최소 호출 간격과 동시 요청 semaphore를 둔다.
- 애플리케이션 자체 daily budget을 별도로 두고, upstream quota와 혼동하지 않게
  이름을 구분한다. 기본 budget 수치는 실키 발급·운영 신청 후 정한다.
- 429 또는 quota 오류가 오면 `Retry-After`/운영자 설정에 따라 backoff하고,
  반복 호출을 즉시 폭주시키지 않는다.
- `citydata`는 한 번에 한 장소만 조회할 수 있으므로 장소 목록을 병렬로 전부
  호출하지 않고 caller가 명시한 대상만 제한적으로 조회한다.
- 동일 인증키를 여러 프로세스가 공유하는 운영을 전제로 하지 않는다. 공유가
  필요하면 외부 distributed limiter를 별도 설계한다.

## 7. API key 보안

- 신규 provider의 canonical 환경변수는 `SEOUL_OPEN_DATA_API_KEY=<placeholder>`로
  확정했다. `kor-travel-map`의 공통 별칭도 값 없이 이름만 지원한다.
- key는 `pydantic.SecretStr` 또는 동일 수준의 secret wrapper로 보관한다.
- 공식 예제 URL이 key를 path에 넣는 HTTP 형식이므로 기본값은 HTTP를 차단한다.
  HTTPS proxy 또는 backend egress를 신뢰하는 운영 설정에서만 `allow_insecure_http=True`
  를 명시한다. public browser 호출은 금지한다.
- URL, exception, retry 로그, metrics label, trace attribute, fixture 이름에 key를
  넣지 않는다. `sample`이라는 공개 테스트 키도 운영 key처럼 redaction 경로를
  거친다.
- 응답 raw를 debug log에 남기지 않으며, 필요하면 제한된 fixture 파일로만 보관한다.
- `.env`, backup, shell history, CI log, PR comment, issue 본문에 key를 쓰지 않는다.

## 8. fixture와 contract test

구현 단계에서 다음 fixture를 먼저 만든다.

- `TrafficInfo` XML 성공 응답과 `ERROR-301`, `INFO-200` 응답
- `GetParkingInfo` JSON/XML 성공 응답과 빈 값·선택 필드 응답
- `GetParkInfo` 정적 주차장 응답
- `realtimeStationArrival` 역 조회 응답과 `recptnDt` 지연 사례
- `realtimePosition` 노선 조회 응답
- `citydata` 장소 단위 응답(교통·주차 block 포함)
- 429/5xx/network timeout mock

테스트는 다음을 보장해야 한다.

1. URL builder가 key를 query나 로그에 노출하지 않는다.
2. JSON과 XML의 공통 envelope가 동일한 typed 결과로 변환된다.
3. `list_total_count`, `RESULT.CODE`, `RESULT.MESSAGE`, `row`가 계약대로 처리된다.
4. 선택 필드·빈 문자열·추가 필드를 손실 없이 처리한다.
5. start/end pagination이 1,000건 상한을 넘지 않는다.
6. retry 대상과 비대상 오류가 구분된다.
7. limiter가 동시성과 최소 간격을 지킨다.
8. 실키 없는 기본 테스트만으로 전체 unit/contract suite가 실행된다.

live smoke test는 별도 opt-in 명령으로 두고, 결과에는 key·전체 URL·원문 응답을
출력하지 않는다.

## 9. 구현 순서

### 단계 A — 계약 고정

- [x] `docs/data-sources.md`의 최신 명세를 다시 확인
- [x] OA 식별자와 service name registry 확정
- [x] canonical 환경변수명과 local `kor-travel-map` 별칭 확정
- [x] HTTP 기본 차단 및 backend 전용 opt-in 정책 확정
- [ ] HTTPS 지원·실제 key 발급 quota 확인(신청 후 운영 작업)

### 단계 B — 공통 runtime

- [x] 설정, transport, redaction, error, pagination 추가
- [x] retry/backoff와 service별 limiter 추가
- [x] 공통 JSON/XML envelope parser와 raw result 추가

### 단계 C — provider별 adapter

- [x] TrafficInfo
- [x] subway arrival/position/all
- [x] parking info/static
- [x] citydata

### 단계 D — 검증·문서

- [x] fixture/contract/unit test
- [x] typing/lint/package build/sdist metadata 검증
- [x] opt-in sample live smoke 및 결과 기록
- [x] 소비 프로젝트 연동 예제와 key 없는 mock 기준

## 10. release·push 계획

1. `codex/` feature branch에서 작은 변경 단위로 작업한다.
2. WSL2에서 pytest, typing, lint, package build를 실행한다.
3. 필요하면 WSL2 Docker 환경에서 clean install/contract test를 추가로 실행한다.
4. secret scanner와 fixture 검사를 실행한다.
5. GitHub 원격 생성·등록과 push는 사용자의 별도 승인 후 수행한다.
6. push 시 Draft PR을 만들고 CI를 통과시킨다.
7. 원 프로젝트 runbook의 James/Popper 적대적 리뷰 절차를 적용한다.
8. API 명세 변경, quota 변경, breaking model 변경은 changelog와 ADR 검토를 거친다.
9. 첫 안정 release 전에는 실키를 사용한 검증 결과가 아니라 재현 가능한 mock/fixture
   계약을 release gate로 삼는다.

## 11. 완료 조건

- API key가 없는 환경에서 import·unit·contract test가 통과한다.
- 후보 API별 endpoint, request, response, update, quota 상태가 문서화되어 있다.
- raw와 typed 결과를 함께 보존한다.
- retry/limiter/redaction 테스트가 있다.
- 사용자 승인 없이 GitHub remote/push를 하지 않는다.
