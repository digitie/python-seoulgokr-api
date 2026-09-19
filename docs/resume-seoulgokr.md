# python-seoulgokr-api resume

## 현재 상태

- provider 1차 구현 및 계약 테스트 완료
- 대상 경로는 최초 확인 시 없었고 새 Git 저장소를 생성함
- 브랜치: `codex/implement-seoulgokr-api`
- `src/seoulgokr/`에 config, async transport, retry, limiter, redaction, parser,
  typed models, client facade를 구현함
- `kor-travel-transport` 파일은 수정하지 않음
- `kor-travel-map`의 비밀값은 읽거나 복사하지 않음
- GitHub 원격 `github.com/digitie/python-seoulgokr-api` 생성·등록·feature branch
  push 완료, Draft PR #1 생성

## 완료한 조사

- 원 프로젝트의 `CLAUDE.md` → `AGENTS.md` → `SKILL.md`와 docs 운영 구조를 확인
- 원문 root governance 문서와 Markdown docs를 새 저장소에 복제
- `F:\dev\kor-travel-map` 경로와 API key 환경변수 이름만 확인
- data.seoul.go.kr 후보 API의 식별자, service, endpoint, 응답 필드, 공통 오류,
  페이지 상한, 실시간 지연·갱신 메모를 조사
- 공식 sample XML/JSON 응답으로 `TrafficInfo`, 지하철 envelope와 실시간 위치
  필드를 검증

## 다음 한 작업

Draft PR #1에 대한 CI와 James/Popper 적대적 리뷰를 완료한 뒤, 실제 quota·HTTPS
정책을 신청 후 live smoke에서 확인하고 결과를 문서에 갱신한다. P0/P1 blocker가
없을 때만 사용자가 요청한 merge gate를 진행한다.
