# test-strategy — 테스트 계층과 책임 경계

`docs/runbooks/testing.md`는 "무엇을 어떻게 실행하는가"를 다룬다. 이 문서는 "왜 이렇게
나누고, 각 계층이 무엇을 책임지는가"를 다룬다. 실행 명령이 필요하면 `testing.md`를 본다.

## 계층 구조

| 계층 | 도구 | DB | 대상 | 실행 위치 |
|---|---|---|---|---|
| Provider 단위/계약 | `pytest` | 없음(고정 fixture) | JSON/XML envelope, typed parser, retry/quota, redaction, limiter | WSL2 (1차), CI |
| 정적/패키지 | Ruff, mypy, `build`, `twine` | 없음 | lint, typing, wheel/sdist 계약, clean wheel import | WSL2 (1차), CI |
| 공개 sample smoke | `examples/sample_smoke.py` | 없음 | `TrafficInfo`·지하철 도착의 opt-in 실제 응답 | WSL2 또는 승인된 수동 실행 |

이 저장소는 provider 라이브러리만 포함하며 PostgreSQL, Alembic, FastAPI, frontend와
실제 저장/scheduler는 소비 프로젝트(`kor-travel-transport`)의 책임이다.

## 계층별 책임 경계

- **파싱/typed 계약**은 fixture 기반 단위 테스트가 책임진다. JSON/XML 형태, 필수 식별자,
  `INFO-200`, upstream 오류 코드와 raw/typed result를 검증한다.
- **전송/운영 계약**은 transport·limiter 회귀 테스트가 책임진다. timeout, bounded retry,
  `Retry-After`, quota cooldown, response byte/row 상한, redaction을 검증한다.
- **배포·저장·OpenAPI 계약**은 이 provider의 범위가 아니다. 소비 프로젝트의 PostgreSQL,
  scheduler, FastAPI와 별도 통합 테스트에서 검증한다.

## 외부 API 의존 테스트 정책

- 단위/계약 테스트는 고정 fixture를 사용하며 CI에서 외부 API를 호출하지 않는다.
- 공개 `sample` key smoke는 `examples/sample_smoke.py`로만 opt-in 실행하고, 실키·원문
  URL·원문 응답을 로그에 남기지 않는다.
- 실제 인증키·quota·HTTPS 동작은 인증키 신청 후 별도 운영 검증으로 남긴다.

## 테스트 격리

이 provider 테스트는 네트워크를 `httpx.MockTransport`로 격리하고, 각 테스트가 자체
limiter/config를 사용한다. 공유 limiter를 검증하는 테스트는 credential·endpoint scope를
명시해 다른 테스트의 호출 상태와 섞이지 않도록 한다.

## 회귀 방지 규칙

- 새 provider endpoint/parser를 추가하면 fixture 계약 테스트와 public sample 검증 경계를
  함께 갱신한다.
- 전송·보안·quota 계약을 바꾸면 adversarial regression을 추가한다.
- CI green과 두 독립 hostile review가 끝나기 전에는 머지하지 않는다.

## 커버리지 현황

CI는 현재 `pytest tests -q`를 실행하며 정량적 coverage threshold는 강제하지 않는다.
coverage 목표를 도입하려면 실제 측정값을 먼저 확인한 뒤 별도 task로 등록한다.

## Live E2E의 한계

`examples/sample_smoke.py`는 실제 공개 sample 응답의 최소 연결 검증일 뿐 전체 서비스
계약이나 실키 quota를 대표하지 않는다. 세부 parser·retry·redaction 정확성은 fixture 기반
pytest가 담당하고, 저장·scheduler·외부 OpenAPI 통합은 소비 프로젝트가 담당한다.
