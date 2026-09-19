# python-seoulgokr-api

`data.seoul.go.kr`의 서울 교통정보 OpenAPI를 비동기 Python provider 라이브러리로
제공한다. 저장·수집 scheduler·FastAPI는 소비 프로젝트의 책임으로 남기고, 이
패키지는 typed 결과와 원문 provenance를 안전하게 반환한다.

현재 구현 범위는 도로 소통(`OA-13291`), 지하철 도착·열차 위치·전체역 도착
(`OA-12764`, `OA-12601`, `OA-15799`), 공영주차장 실시간·기준정보
(`OA-21709`, `OA-13122`), 서울 실시간 도시데이터(`OA-21285`)다.

## 설치와 사용

```bash
pip install seoulgokr
export KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY='<발급키>'
# 공식 endpoint가 HTTP로만 문서화된 현재는 backend 전용으로 명시적 opt-in이 필요하다.
export SEOUL_OPEN_DATA_ALLOW_INSECURE_HTTP=true
```

`SEOUL_OPEN_DATA_API_KEY`를 canonical 이름으로 사용할 수 있으며,
`kor-travel-map`의 공통 별칭(`KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY`,
`KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY`, `DATA_GO_KR_SERVICE_KEY`,
`DATAGOKR_API_KEY`, `PUBLIC_DATA_SERVICE_KEY`, `SERVICE_KEY`)도 읽는다. 키 값은
소스·문서·로그에 넣지 않는다.

```python
import asyncio

from seoulgokr import SeoulOpenDataClient, SeoulOpenDataConfig


async def main() -> None:
    config = SeoulOpenDataConfig.from_env(
        # 실시간 서비스는 기본 30초 간격이다. 실제 발급 quota에 맞춰 조정한다.
        # 도착·위치·전체역 endpoint가 공유하는 client 예산
        service_daily_budgets={"realtimeSubway": 900},
    )
    async with SeoulOpenDataClient(config=config) as client:
        result = await client.subway_arrivals("서울")
        for arrival in result.items:
            print(arrival.train_line_name, arrival.arrival_seconds)


asyncio.run(main())
```

`result.request`에는 redacted URL만, `result.raw_payload`에는 인증키가 없는
파싱된 원문 mapping이 담긴다. `fetched_at`과 upstream의 `recptnDt`/원천 시각은
서로 다른 값으로 보존된다.

전체역 도착(`OA-15799`)은 호출량과 응답 크기가 크므로 기본 비활성이다. 운영자가
`allow_all_station_arrivals=True`와 `all_station_arrivals_max_items`를 함께 지정한
경우에만 호출하며, `sample` 키는 사용할 수 없다. `INFO-200`은 빈 결과로 반환하고,
`INFO-000`인데 필수 envelope나 식별 필드가 없는 응답은 파싱 오류로 거부한다.

## quota와 장애 처리

- 일반 API 페이지 범위는 한 호출 1,000건 이하, `sample` 키는 5건 이하로 사전 차단한다.
- 지하철 실시간 API의 기본 최소 간격은 30초이며, 일반 API는 1초다. 이는 공개된
  서비스별 quota를 대신하는 값이 아니라 보수적인 client 보호 장치다.
- 서울시 이용안내에 명시된 실시간 지하철 일 최대 1,000건은
  `realtime_subway_daily_budget` 기본값으로 적용하며, 도착·위치·전체역 endpoint가
  하나의 limiter 일일 예산을 공유한다. 발급 key의 별도 계약이 있으면 운영자가 이
  값을 조정하되, 확인되지 않은 일반 서비스 quota는 추정하지 않는다.
- `service_daily_budgets`로 애플리케이션 자체 일일 예산을 설정할 수 있다. 미확인
  upstream quota를 코드에서 임의로 주장하지 않는다.
- timeout, HTTP 429와 transient 5xx(500/502/503/504), 네트워크 오류는 bounded retry를 사용한다. HTTP 200 본문의
  `ERROR-500/600/601`도 같은 방식으로 제한 재시도하며, `INFO-200`은 정상적인 빈
  결과로 반환한다. upstream `ERROR-337` 또는 명시적인 quota 문구는 재시도하지 않고
  `upstream_quota_cooldown_seconds`만큼 limiter에 bounded cooldown을 기록한다.
- 응답 body는 기본 16 MiB(`max_response_bytes`)에서 읽기를 중단하고, 전체역 등
  caller가 지정한 `max_items` 상한은 typed model을 만들기 전에 적용한다. 페이지 범위와
  `sample` 기능 제한은 application daily quota가 아닌 `SeoulConfigurationError`로
  반환한다.
- 공식 endpoint가 HTTP 형태로 문서화되어 있어 `allow_insecure_http` 기본값은
  `False`다. backend egress/proxy를 명시적으로 신뢰하는 환경에서만 opt-in하고,
  인증키를 브라우저에서 직접 호출하지 않는다. HTTPS 지원 여부와 실제
  서비스별 quota·reset 시각은 인증키 신청 후 운영자가 확인해야 한다.
- limiter 공유 범위는 동일 credential·endpoint·이벤트 루프다. 여러 프로세스나 이벤트
  루프가 같은 key를 사용하면 Redis 등 외부 distributed limiter를 별도로 둔다.

먼저 읽을 문서:

- [프로젝트 범위 보충](https://github.com/digitie/python-seoulgokr-api/blob/main/docs/project-scope.md)
- [구현 계획](https://github.com/digitie/python-seoulgokr-api/blob/main/docs/implementation-plan.md)
- [서울 데이터 소스 조사](https://github.com/digitie/python-seoulgokr-api/blob/main/docs/data-sources.md)
- [현재 재개 지점](https://github.com/digitie/python-seoulgokr-api/blob/main/docs/resume-seoulgokr.md)
- [라이브러리 아키텍처](https://github.com/digitie/python-seoulgokr-api/blob/main/docs/architecture/seoulgokr-library.md)

원 프로젝트의 운영 문서는 요청에 따라 원문 그대로 복제했다. 복제 문서 안의
`kor-travel-transport`, FastAPI, Next.js, PostgreSQL, `parking-radar` 관련 내용은
정책·운영 참고용이며, 이 라이브러리에 backend/frontend를 복사했다는 뜻이 아니다.
