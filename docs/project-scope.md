# 프로젝트 범위 보충

## 기본 정보

- 대상 저장소: `F:\dev\python-seoulgokr-api`
- 목표 원격: `github.com/digitie/python-seoulgokr-api`
- 조사 기준 저장소: `F:\dev\kor-travel-transport`
- 형제 프로젝트 조사 경로: `F:\dev\kor-travel-map`
- 조사 기준일: `2026-09-19` (KST)
- 현재 브랜치: `codex/plan-scaffold`
- 원격 저장소: 아직 생성·등록·push하지 않음

대상 경로는 최초 확인 시 존재하지 않았다. 따라서 빈 Git 저장소를 만들고 계획
단계에 필요한 최소 패키지 디렉터리만 추가했다. 대상 경로가 이미 존재할 때
기존 파일을 덮어쓰지 않도록 하는 보호 조건도 실행 전에 확인했다.

## 원 프로젝트 문서 복제 정책

다음 파일은 `kor-travel-transport`의 원문을 보존하기 위해 그대로 복제했다.

- `CLAUDE.md`
- `AGENTS.md`
- `SKILL.md`
- `docs/` 아래의 기존 Markdown 운영·아키텍처·runbook 문서

원문은 서울 provider 라이브러리의 최종 아키텍처가 아니다. 원문에 있는
`backend/`, `frontend/`, FastAPI, Next.js, PostgreSQL, `parking-radar`, 공항 주차
수집기 관련 내용은 원 프로젝트의 거버넌스와 운영 문맥을 보존하기 위해 남긴
것이다.

이 저장소의 목표·경로·모듈 경계·검증 범위는 다음 보충 문서가 정의한다.

- [구현 계획](implementation-plan.md)
- [데이터 소스 조사](data-sources.md)
- [라이브러리 아키텍처](architecture/seoulgokr-library.md)
- [라이브러리 release runbook](runbooks/library-release.md)
- [현재 resume](resume-seoulgokr.md)
- [계획 task](tasks-seoulgokr.md)

## 복제하지 않은 범위

- `kor-travel-transport/backend/` 및 `frontend/` 구현
- 원 프로젝트의 데이터베이스, Docker volume, `.env`, 백업 파일, API key
- `docs/openapi.json`과 같은 애플리케이션 API 산출물
- `kor-travel-map`의 소스·환경 파일·비밀값

provider는 저장소와 API 서버 사이의 재사용 가능한 경계로만 설계한다. 저장소에
데이터를 적재하거나 FastAPI endpoint를 제공하는 책임은 후속 소비 프로젝트가
명시적으로 맡을 때 별도 설계한다.

## 정책 우선순위 해석

원문 `AGENTS.md`의 보안·Git·문서·검증 정책은 유지한다. 다만 원문에 포함된
애플리케이션 구현 세부사항을 이 저장소에 자동 적용하지 않는다. 이 저장소에서
새로 만드는 문서는 한국어로 작성하고, 공식 API 식별자·필드명·URL·환경변수명은
원문 표기를 유지한다.

