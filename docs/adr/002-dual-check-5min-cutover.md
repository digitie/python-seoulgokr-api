# ADR-002: 5분 수집 경계의 이중 확인 컷오버

- **상태**: accepted
- **날짜**: 2026-08-22
- **결정자**: agent + human (T-003, T-027)
- **컨텍스트**: 13번(ODROID, SQLite)에서 14번(PostgreSQL)으로 운영 데이터를 무손실 이전해야
  했다. 13번은 이전 중에도 계속 살아있는 read-only 소스였고, 5분 간격 수집이 겹치는 경계에서
  일부 관측이 빠지거나 중복 적재될 위험이 있었다.
- **결정**: 이전은 "7일 HTTP prewarm(base copy) → 1일 delta import(final delta)" 2단계로
  나누고, 각 단계 실패 시 rollback한다. 컷오버 판정은 5분 연속성을 epsilon 없이 strict하게
  검사하는 gate(7회 × 50초 = 300초 관측)로 하며, gate는 stable legacy lot identity로
  source/target lot을 대조하고 lot freshness·source lag·successful run gap을 모두 300초
  한도로 검사한다. 양쪽 무관측 lot은 명시적 allowlist 없이는 통과시키지 않는다.
- **근거**: base copy와 final delta를 분리하면 대량 이전 중 발생한 실패를 이전 전체 재시도가
  아니라 delta 구간만 재시도로 복구할 수 있다. 5분 수집 주기 대비 300초 관측 gate는 최소
  1회 이상의 정상 수집 사이클을 강제로 통과시켜, 컷오버 직후 우연히 한 번 성공한 것을 안정
  상태로 오판하지 않게 한다.
- **결과 (긍정)**: 컷오버 이후 DB 중복(`migration_http`와 live source가 같은 lot·관측시각을
  가진 행) 재검증에서 중복 `0`을 확인했고, history API 중복 timestamp도 `0`이었다. gate는
  `failed_samples=0`, `source_lots=53`, `target_lots_checked=53` 기준으로 반복 통과했다.
- **결과 (부정)**: strict gate 관측 시간(300초 이상) 동안은 배포/검증 파이프라인이 그만큼
  길어진다. 초기 threshold(수집 주기 300초 그대로)에서는 한 샘플이 `319.7s`로 밀려 실패한
  적이 있어, server14 safety buffer를 120초로 늘려 effective tick을 180초로 재조정했다.
- **후속**: 수집 주기(`300s` configured)나 safety buffer(`120s`)를 바꾸면 이 ADR과
  `docs/architecture/collection.md`, `docs/runbooks/migration.md`를 함께 갱신하고, 변경 전후
  strict gate 재실행 결과(`failed_samples`, `gate_duration_seconds`, `source_lots`,
  `target_lots_checked`)를 `docs/journal.md`에 남긴다.
