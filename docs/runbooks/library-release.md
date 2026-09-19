# provider 라이브러리 release runbook

## 현재 단계

provider 1차 구현이 완료된 상태다. 이 runbook은 실제 인증키 신청·원격 공개·release
전 검증 절차를 고정한다. 인증키 값 자체는 어느 단계에서도 저장하지 않는다.

## 구현 전 확인

- [ ] `docs/data-sources.md`의 source id/service/endpoint를 공식 명세에서 재확인
- [ ] 신청된 key의 일 quota·rate limit·reset 시각을 기록하되 값 자체는 저장하지 않음
- [ ] HTTPS endpoint와 인증키 전송 보호를 확인
- [ ] 운영 수집 주기와 caller별 호출 예산을 정함

## 로컬 검증

- [ ] WSL2에서 `pytest` unit/contract test
- [ ] `mypy` 또는 동등한 typing 검사
- [ ] `ruff check` 및 formatter 검사
- [ ] package build와 clean environment install
- [ ] secret scanner 및 key redaction 테스트
- [ ] live smoke는 opt-in이며 결과·URL·응답에 key가 없어야 함

## GitHub 절차

1. `codex/` feature branch에서 변경한다.
2. 관련 문서·fixture·테스트를 함께 커밋한다.
3. 사용자의 승인 뒤 `github.com/digitie/python-seoulgokr-api` 원격을 생성/등록한다.
4. main 직접 push 없이 push와 Draft PR을 사용한다.
5. CI, James/Popper 적대적 리뷰, key leak 검사 후 merge한다.
6. release 전에는 changelog와 package metadata를 확인한다.

## 장애 대응

- `INFO-100`, `ERROR-300`, `ERROR-301`, `ERROR-310`, `ERROR-331`~`ERROR-336`은
  요청/설정 오류로 분류하고 자동 retry하지 않는다.
- `ERROR-500`, `ERROR-600`, `ERROR-601`, HTTP 5xx, timeout은 bounded retry 후
  upstream 장애로 기록한다.
- 429 또는 quota 초과는 limiter cooldown으로 막고, 공식 reset 정보가 없으면
  추정해 무기한 대기하지 말고 운영자 확인을 요구한다.
- 로그에서 key가 발견되면 즉시 로그 폐기·key rotation·재발 방지 검사를 진행한다.
