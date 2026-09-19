# python-seoulgokr-api 테스트 실행

이 저장소는 서울 열린데이터광장 provider 라이브러리다. PostgreSQL 저장, 주기 수집,
FastAPI OpenAPI와 운영 E2E는 `kor-travel-transport`에서 별도로 검증한다.

## WSL2 1차 검증

저장소 루트에서 다음 명령을 실행한다.

```bash
uv run --locked --extra dev ruff format src tests scripts
uv run --locked --extra dev ruff check src tests scripts
uv run --locked --extra dev mypy src
uv run --locked --extra dev python -m pytest -q
```

pytest는 `httpx.MockTransport` fixture로 외부 호출을 격리한다. transport, parser, typed
result, retry/quota, redaction, limiter 동시성 경계를 함께 검증한다.

## 패키지 검증

```bash
uv run --locked --extra dev python scripts/check_no_secrets.py
rm -rf dist
uv run --locked --extra dev python -m build --wheel --sdist
uv run --locked --extra dev python -m twine check dist/*
```

wheel clean-install과 sdist 내용 검사를 수행해 내부 문서·테스트·스크립트가 배포물에
포함되지 않는지 확인한다.

## 공개 sample smoke

실제 외부 호출은 명시적으로 승인된 경우에만 실행한다.

```bash
uv run --locked --extra dev python examples/sample_smoke.py
```

이 명령은 공개 `sample` key로 `TrafficInfo`와 지하철 도착의 최소 응답만 확인한다.
출력에 인증키, 전체 URL, 원문 응답을 추가하지 않는다. 실키 quota·HTTPS 지원 여부는
인증키 신청 후 별도 운영 검증으로 기록한다.

## CI와 merge gate

`.github/workflows/ci.yml`은 Python 3.11·3.12·3.13에서 secret scan, Ruff, mypy,
pytest, wheel/sdist build, `twine check`, clean wheel import를 실행한다. CI가 green이고
두 명의 독립 적대적 리뷰에서 P0/P1이 없을 때만 Draft PR을 Ready로 전환하고 merge한다.
