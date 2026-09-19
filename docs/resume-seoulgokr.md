# python-seoulgokr-api resume

## 현재 상태

- provider 1차 구현, 계약 테스트, 적대적 리뷰 보안 회귀 테스트, 패키지 검증 및 공개 sample live smoke 완료
- 대상 경로는 최초 확인 시 없었고 새 Git 저장소를 생성함
- 브랜치: `codex/implement-seoulgokr-api`
- `src/seoulgokr/`에 config, async transport, retry, limiter, redaction, parser,
  typed models, client facade를 구현함
- `kor-travel-transport` 파일은 수정하지 않음
- `kor-travel-map`의 비밀값은 읽거나 복사하지 않음
- GitHub 원격 `github.com/digitie/python-seoulgokr-api` 생성·등록·feature branch
  push 완료, Draft PR #1 생성
- 최신 코드 커밋 `611e3ef` 기준 James/Popper 두 독립 hostile review에서 P0/P1/P2가
  없음을 확인하고 merge 승인받음
- WSL2 Ruff·mypy·pytest 70개, secret scanner, wheel/sdist·`twine check`·clean wheel
  smoke 및 Python 3.11/3.12/3.13 CI를 통과함

## 완료한 조사

- 원 프로젝트의 `CLAUDE.md` → `AGENTS.md` → `SKILL.md`와 docs 운영 구조를 확인
- 원문 root governance 문서와 Markdown docs를 새 저장소에 복제
- `F:\dev\kor-travel-map` 경로와 API key 환경변수 이름만 확인
- data.seoul.go.kr 후보 API의 식별자, service, endpoint, 응답 필드, 공통 오류,
  페이지 상한, 실시간 지연·갱신 메모를 조사
- 공식 sample XML/JSON 응답으로 `TrafficInfo`, 지하철 envelope와 실시간 위치
  필드를 검증

## 다음 한 작업

문서 릴리스 게이트 커밋의 CI가 최신 HEAD에서 통과하는지 확인한 뒤 PR #1을 Ready로 전환하고
머지한다. 이 provider 작업은 머지 후 완료로 보고, 실제 quota·HTTPS 지원은 인증키 신청 후
별도 운영 task로 확인한다.
