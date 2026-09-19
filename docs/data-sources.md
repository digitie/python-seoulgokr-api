# 서울 교통정보 데이터 소스 조사

조사 기준일: `2026-09-19` (KST)

아래 내용은 서울 열린데이터광장의 데이터셋 페이지와 OpenAPI 명세 페이지를
기준으로 정리한 후보 목록이다. API 명세와 서비스 운영 상태는 바뀔 수 있으므로
구현 직전에 각 원문 URL을 다시 확인한다.

## 공통 호출 계약

서울 열린데이터광장 일반 OpenAPI의 문서상 호출 형태는 다음과 같다.

```text
http://openapi.seoul.go.kr:8088/{KEY}/{TYPE}/{SERVICE}/{START_INDEX}/{END_INDEX}/{FILTER}
```

지하철 TOPIS API는 별도 호스트/경로를 사용한다.

```text
http://swopenAPI.seoul.go.kr/api/subway/{KEY}/{TYPE}/{SERVICE}/{START_INDEX}/{END_INDEX}/{FILTER}
```

공통적으로 확인되는 응답 요소는 `list_total_count`, `RESULT.CODE`,
`RESULT.MESSAGE`, `row`다. JSON은 보통 서비스명 객체 아래에 이 요소가 있고,
XML은 서비스명 root 아래에 같은 요소가 있다. 지하철 실시간 API는
`errorMessage.code`와 `realtimeArrivalList`/`realtimePositionList`를 사용한다.
`citydata` sample은 `RESULT` 안에 `RESULT.CODE`/`RESULT.MESSAGE`가 있고
`CITYDATA` 아래에 장소 block이 들어오므로 일반 row parser와 분리한다.

공식 명세에서 확인된 주요 오류는 다음과 같다.

- `INFO-000`: 정상 처리
- `INFO-100`: 인증키 무효/미신청
- `INFO-200`: 해당 데이터 없음
- `ERROR-300`: 필수값 누락
- `ERROR-301`: `TYPE` 누락 또는 무효
- `ERROR-310`: `SERVICE` 없음
- `ERROR-331`~`ERROR-334`: 시작·종료 위치 오류
- `ERROR-335`: `sample` 키는 한 번에 최대 5건
- `ERROR-336`: 한 호출 최대 1,000건
- `ERROR-500`, `ERROR-600`, `ERROR-601`: 서버·DB·SQL 오류

`ERROR-335`/`ERROR-336`은 페이지 크기 제한이지 일일 quota가 아니다. 일일
quota와 분당 rate limit을 이 숫자에서 추정하지 않는다.

## 후보 API

| 우선순위 | 데이터셋/식별자 | service/endpoint | 응답·주요 필드 | 갱신·호출 주의 | 상태 |
|---|---|---|---|---|---|
| 1 | 서울시 실시간 도로 소통 정보 `OA-13291` | `TrafficInfo`<br>`http://openapi.seoul.go.kr:8088/{KEY}/xml/TrafficInfo/1/5/{LINK_ID}` | XML 중심. `LINK_ID`, `PRCS_SPD`, `PRCS_TRV_TIME` 및 공통 envelope | 공식 메타데이터: `비정기(수시) - 실시간/매일`. 링크별 조회라 link registry/캐시 필요 | 1차 후보 |
| 1 | 서울시 지하철 실시간 도착정보 `OA-12764` | `realtimeStationArrival`<br>`http://swopenAPI.seoul.go.kr/api/subway/{KEY}/json/realtimeStationArrival/0/5/{역명}` | `subwayId`, `updnLine`, `trainLineNm`, `statnNm`, `barvlDt`, `btrainNo`, `recptnDt`, `arvlMsg2`, `arvlMsg3`, `arvlCd`, `lstcarAt` | 역명 필수. `recptnDt`와 현재 시각 사이의 원천 처리 지연을 반영해야 함. 서울 외 역구간 미제공 | 1차 후보 |
| 1 | 서울시 지하철 실시간 열차 위치정보 `OA-12601` | `realtimePosition`<br>`http://swopenAPI.seoul.go.kr/api/subway/{KEY}/json/realtimePosition/0/5/{호선명}` | `subwayId`, `subwayNm`, `statnId`, `statnNm`, `trainNo`, `lastRecptnDt`, `recptnDt`, `updnLine`, `statnTnm`, `trainSttus`, `directAt`, `lstcarAt` | 노선 단위 조회. 도착 API와 `trainNo` 연결 가능성을 fixture로 확인 | 1차 후보 |
| 1 | 서울시 지하철 실시간 도착정보(일괄) `OA-15799` | service `realtimeStationArrival/ALL`. `http://swopenAPI.seoul.go.kr/api/subway/{KEY}/json/realtimeStationArrival/ALL` 형태 | 역별 API와 동일 계열 필드. 현재 provider는 pagination 없는 endpoint로 호출 | 전체역 응답은 크고 quota를 빠르게 소모할 수 있어 기본 30초 간격·daily budget을 적용 | 구현 |
| 1 | 서울시 시영주차장 실시간 주차대수 정보 `OA-21709` | `GetParkingInfo`<br>`http://openapi.seoul.go.kr:8088/{KEY}/json/GetParkingInfo/1/1000/{ADDR}` | `PKLT_CD`, `PKLT_NM`, `ADDR`, `TPKCT`, `NOW_PRK_VHCL_CNT`, `NOW_PRK_VHCL_UPDT_TM`, 운영·요금 필드 및 공통 envelope | 공식 설명은 실제 정보가 5분 이상 지연될 수 있다고 안내. 메타 갱신주기는 `비정기(자료변경시)` | 1차 후보 |
| 2 | 서울시 공영주차장 안내 정보 `OA-13122` | `GetParkInfo`<br>`http://openapi.seoul.go.kr:8088/{KEY}/json/GetParkInfo/1/1000/{ADDR}` | `PKLT_NM`, `ADDR`, `PKLT_CD`, `TPKCT`, 운영·요금·좌표·`LAST_DATA_SYNC_TM` 등 | 정적 기준정보 역할. 공식 FAQ는 현재 주차대수(`cur_parking`) 컬럼 삭제를 안내하므로 실시간 수치 계약으로 사용하지 않음 | 1차 후보 |
| 2 | 서울시 실시간 도시데이터 `OA-21285` | `citydata`<br>`http://openapi.seoul.go.kr:8088/{KEY}/xml/citydata/1/5/{AREA_NM}` | 장소·혼잡·도로·주차·지하철 등 block. `AREA_NM`, `AREA_CD`, `ROAD_TRAFFIC_*`, `PRK_*`, `SUB_*` 등 | 한 번에 한 장소만 호출. 샘플 키는 광화문·덕수궁만 가능. 장소 목록 변경 이력 존재 | 조건부 후보 |

## API별 세부 확인

### 도로 소통 `TrafficInfo`

- 데이터셋: [OA-13291](https://data.seoul.go.kr/dataList/OA-13291/A/1/datasetView.do)
- 명세: [OA-13291 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-13291&srvType=A)
- 샘플: `http://openapi.seoul.go.kr:8088/sample/xml/TrafficInfo/1/5/1220003800`
- 공식 명세는 `TYPE=xml`만 제시한다. JSON을 당연히 지원한다고 가정하지 않는다.
- link id별로 조회하므로 `표준링크 매핑정보`, `소통 돌발 링크` 등 연관 데이터와
  함께 link registry를 관리해야 한다.

### 지하철 도착·위치

- 도착 데이터셋: [OA-12764](https://data.seoul.go.kr/dataList/OA-12764/A/1/datasetView.do)
- 도착 명세: [OA-12764 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-12764&srvType=A)
- 위치 데이터셋: [OA-12601](https://data.seoul.go.kr/dataList/OA-12601/A/1/datasetView.do)
- 위치 명세: [OA-12601 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-12601&srvType=A)
- 일괄 데이터셋: [OA-15799](https://data.seoul.go.kr/dataList/OA-15799/A/1/datasetView.do)
- 일괄 명세: [OA-15799 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-15799&srvType=A)
- 도착 API 공식 설명은 `recptnDt`를 데이터 생성 시각으로 설명하며 현재 시각과의
  차이를 고려해야 한다고 안내한다.
- 2026년 공지에는 서비스 일시 중단·정상화 안내가 있었으므로, provider는 일시적
  empty/error를 데이터 자체의 "열차 없음"과 구분해야 한다.
- 2026-09-19 공개 sample 기준 `realtimeStationArrival`은 `errorMessage`와
  `realtimeArrivalList`를 반환하고, `realtimePosition`은
  `realtimePositionList`를 반환했다. 두 envelope 모두 typed parser에서 지원한다.

### 주차 `GetParkingInfo` / `GetParkInfo`

- 실시간/시영: [OA-21709](https://data.seoul.go.kr/dataList/OA-21709/S/1/datasetView.do)
- 실시간 명세: [OA-21709 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-21709&srvType=A)
- 기준정보: [OA-13122](https://data.seoul.go.kr/dataList/OA-13122/S/1/datasetView.do)
- 기준정보 명세: [OA-13122 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-13122&srvType=A)
- 2026-09-19 sample 호출에서 `GetParkingInfo`는 JSON envelope와 주차장·운영·요금
  필드를 반환했지만, sample 응답과 현재 데이터셋 FAQ가 일부 다를 수 있다.
  `NOW_PRK_VHCL_CNT`를 필수 typed field로 고정하지 말고 optional/raw로 보존한다.
- OA-13122 공식 FAQ는 `cur_parking` 데이터가 삭제되었으며 추후 제공 예정이 없다고
  안내한다. 기준정보와 실시간 정보의 source identity를 분리한다.
- OA-21709 공식 설명은 실제 데이터와 5분 이상 차이가 날 수 있고, 실시간 과거
  데이터는 별도 제공하지 않는다고 안내한다.

### 실시간 도시데이터 `citydata`

- 데이터셋: [OA-21285](https://data.seoul.go.kr/dataList/OA-21285/A/1/datasetView.do)
- 명세: [OA-21285 OpenAPI 명세](https://data.seoul.go.kr/dataList/openApiView.do?infId=OA-21285&srvType=A)
- 공식 설명은 실시간 인구, 도로소통, 주차, 지하철 도착, 버스정류소, 사고통제,
  따릉이, 날씨·환경, 전기차충전소, 문화행사 등을 한 장소 기준으로 제공한다고
  설명한다.
- 2025-09 공지는 버스 도착 정보 삭제를 안내했다. 따라서 도시데이터 안에 버스
  arrival이 항상 있다고 가정하지 않는다.
- 공개 sample의 현재 응답은 `CITYDATA.AREA_NM`, `CITYDATA.AREA_CD`,
  `CITYDATA.ROAD_TRAFFIC_STTS`, `CITYDATA.PRK_STTS`, `CITYDATA.SUB_STTS`처럼
  block별 배열/객체를 섞어 반환한다. provider는 안정적인 장소·혼잡 필드만 typed로
  올리고 나머지는 raw block으로 보존한다.
- 공식 dataset 페이지에는 주요 장소 수 변경 공지가 누적되어 있고, 2026-03 공지는
  120곳에서 122곳으로 변경한다고 알린 반면 OpenAPI 명세 문구에는 120장소 표현이
  남아 있다. 구현 전 최신 장소 목록 파일과 실제 명세를 다시 대조해야 한다.

## 인증·신청·quota

### 확인된 사실

- [Open API 이용안내](https://data.seoul.go.kr/together/guide/useGuide.do)는 Open API
  사용 전에 인증키 발급이 필요하다고 안내한다.
- 같은 안내에는 실시간 지하철 Open API를 하루 최대 1,000건 요청할 수 있고, 한
  호출은 최대 1,000건이라고 적혀 있다. 일반 인증키와 실시간 지하철 인증키
  신청 경로가 별도로 표시된다.
- `sample` 키는 최초 5건 이내/일부 장소만 호출할 수 있으며, 명세 오류 코드에도
  `ERROR-335`가 있다.
- [이용약관의 Open API 제한 조항](https://data.seoul.go.kr/etc/accessTerms.do)은
  서비스별 이용 시간·횟수 제한, 트래픽에 따른 제한, 비정상 사용 시 key 정지
  가능성을 명시한다.

### 아직 확인되지 않은 사실

- `TrafficInfo`, `GetParkingInfo`, `GetParkInfo`, `citydata`, `realtimePosition`,
  `realtimeStationArrival/ALL`의 key별 일 quota
- 서비스별 초당/분당 rate limit, 동시성 limit, `Retry-After` 제공 여부
- quota reset 시각과 quota 초과 후 정확한 회복 시각
- 모든 API에서 HTTPS endpoint가 공식 지원되는지 여부
- OA-15799 일괄 endpoint의 정확한 start/end path와 최대 결과 건수

위 항목은 추정하지 않고 **신청 후 확인**으로 유지한다. 인증키 발급 후 작은
범위의 opt-in smoke test와 서울시 문의/Q&A 답변으로 확인한다.

## 오류·장애 처리 메모

- HTTP 200이어도 `RESULT.CODE`가 오류일 수 있으므로 application-level error를
  검사한다.
- `ERROR-500`/`ERROR-600`/`ERROR-601`은 즉시 무한 재시도하지 않고 bounded retry 후
  upstream incident로 기록한다.
- `INFO-200`은 정상 envelope 안의 no-data일 수 있으므로 빈 정상 결과와 장애를
  구분한다.
- 429 또는 quota 문구는 rate limiter의 cooldown으로 전환한다.
- `citydata`/실시간 API에서 오래된 `recptnDt`, `CUR_PRK_TIME` 등 source timestamp를
  수집 시각과 혼동하지 않는다.

## 형제 프로젝트 설정 확인

확인한 로컬 경로는 `F:\dev\kor-travel-map`이다. 비밀 파일과 값은 읽거나 복사하지
않았다. 확인된 환경변수 **이름만** 적는다.

```text
KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY=<placeholder>
DATA_GO_KR_SERVICE_KEY=<placeholder>
DATAGOKR_API_KEY=<placeholder>
PUBLIC_DATA_SERVICE_KEY=<placeholder>
SERVICE_KEY=<placeholder>
KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY=<placeholder>
```

`kor-travel-map`의 현재 provider source 설정에는 `data.seoul.go.kr` 전용 source
또는 서울 Open Data 전용 key 이름이 발견되지 않았다. 새 라이브러리의 계획상
canonical key는 `SEOUL_OPEN_DATA_API_KEY=<placeholder>`이며, 기존 공통
`DATA_GO_KR_SERVICE_KEY`를 자동 alias로 읽는 것은 key provenance 혼동을 막기 위해
구현 시작 전에 별도 승인·결정한다.
