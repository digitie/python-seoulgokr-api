# python-seoulgokr-api 계획 task

## T-SG-001 — API 계약 재확인

- [x] OA 식별자와 service registry 재확인
- [x] OA-15799 일괄 endpoint의 현재 service path 확인
- [ ] citydata 장소 목록 수(120/122)와 최신 목록 확인
- [ ] HTTPS 지원·인증키 신청 경로·서비스별 quota 확인

## T-SG-002 — 공통 runtime

- [x] canonical settings와 SecretStr
- [x] async transport와 timeout
- [x] JSON/XML envelope parser
- [x] source-aware error normalization
- [x] retry/backoff와 `Retry-After`
- [x] service/key limiter와 daily budget
- [x] key/path/header/body redaction

## T-SG-003 — typed provider

- [x] `TrafficInfo`
- [x] subway arrival/position/all
- [x] `GetParkingInfo`/`GetParkInfo`
- [x] `citydata`
- [x] raw+typed result contract

## T-SG-004 — 검증

- [x] fixture와 contract test
- [x] application-level transient error retry test
- [x] quota/page-size guard test
- [x] key leak regression test
- [x] WSL2 test/lint/type/build
- [ ] HTTP 429/5xx live-equivalent regression test 보강

## T-SG-005 — release 준비

- [x] 사용 예제와 quota 주의사항
- [ ] CI 및 secret scanner
- [ ] hostile review
- [ ] 사용자 승인 후 GitHub remote/Draft PR
