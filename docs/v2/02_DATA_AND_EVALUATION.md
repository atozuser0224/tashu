# V2 데이터 계약 및 평가 계획

> 목적: 타슈캐스트가 **지금 가진 데이터로 말할 수 있는 것**과 **추가 데이터가 있어야만 말할 수 있는 것**을 분리하고, API·CSV·예측·정체신호의 검증 절차와 중단 기준을 구현 가능한 계약으로 고정한다.
>
> 이 문서의 기본 원칙은 다음 세 가지다.
>
> 1. 실제 응답이나 원본 파일을 보지 않은 카탈로그 문구는 런타임 사실로 승격하지 않는다.
> 2. 대여이력(trip events)만으로 과거 재고량이나 고장 여부를 재구성하지 않는다.
> 3. 평가 데이터가 없으면 제품 문구를 낮춘다. 데모 fixture를 실측 성능처럼 발표하지 않는다.

---

## 1. 용어와 주장 경계

### 1.1 시각과 식별자

- `collected_at`: 우리 수집기가 응답 본문을 받은 시각. 타슈 응답에 원천 시각이 없으면 이 값을 화면의 **수집 시각**으로 사용한다.
- `source_observed_at`: 원시 수집 계층의 예약 메타데이터. v2.2의 두 live 후보는 신뢰할 수 있는 원천 관측시각을 제공하지 않으므로 항상 `null`이며 추정해서 채우지 않는다.
- `observed_at`: 외부 계약에서 원본 수량과 함께 제공하는 기준시각. v2.2 성공 관측은 `collected_at`과 같은 값이고 `observed_at_basis="collected_at"`을 함께 반환한다. 신뢰할 수 있는 원천 시각을 쓰려면 다음 계약 버전에서 명시적으로 추가한다.
- `station_id`: 원천별 ID를 보존한다. 서로 다른 API의 ID가 같다는 것은 §3의 비교 게이트를 통과하기 전까지 가정하지 않는다.
- `parking_count`: API가 보고한 정류장 집계 대수. 정상 자전거 수, 실제 현장 대수, 대여 성공 대수와 동의어가 아니다.
- `bikes_available`: 저장소와 외부 OpenAPI에서 쓰는 정규화 필드명. 원천 `parking_count`를 보정 없이 그대로 옮긴 값이다.
- `snapshot`: 한 정류장의 `(station_id, collected_at, bikes_available)` 관측값. 아래 평가 수식의 `parking_count`는 이 값의 원천 의미를 명시하기 위한 표기다.
- `trip event`: 대여·반납 시각과 장소를 가진 이동 기록. snapshot이 아니다.

### 1.2 제품이 직접 주장하지 않는 것

- `parking_count`에서 임의의 고장 대수를 빼서 “실제 이용 가능 대수”를 만들지 않는다.
- `P(parking_count(t+15) >= 1)`을 “정상 자전거를 실제로 빌릴 확률”로 부르지 않는다.
- 정체신호를 “고장 탐지”, `normal`을 “자전거 정상 확인”으로 부르지 않는다.
- 현장·정비 라벨 없이 `confirmed`를 부여하지 않는다.

---

## 2. Fact ledger

### 2.1 증거 등급

| 등급 | 의미 | 승격 조건 |
|---|---|---|
| **확인** | 우리 팀이 원본 파일 또는 실제 HTTP 200 응답을 보존했고 재현 가능한 검사 결과가 있음. 또는 공개 원문에서 부재·정의를 직접 확인함 | fixture/원본 해시, 수집시각, 검사 코드·결과를 남김 |
| **카탈로그확인** | data.go.kr 등 카탈로그 페이지에 그렇게 적혀 있으나 실제 파일·200 응답으로는 확인하지 못함 | §3 또는 §5 게이트 통과 후 `확인`으로 승격 |
| **추정** | 관찰 사실로부터 합리적으로 도출했지만 직접 측정하지 않은 설계 가정 | 검증 방법과 폐기 조건을 함께 기록 |
| **미확인** | 근거가 없거나 출처끼리 충돌함 | 확인 전 기능·일정의 필수 전제로 사용 금지 |

등급은 문서 작성자의 확신도가 아니라 **증거의 종류**다. 모든 승격·강등은 날짜, 근거 artifact, 담당자를 ledger 변경 이력에 남긴다.

### 2.2 초기 사실 원장

| ID | 주장 | 현재 등급 | 근거/한계 | 확인 후 저장할 artifact |
|---|---|---|---|---|
| F-01 | 직접 타슈 API는 `GET https://bikeapp.tashu.or.kr:50041/v1/openapi/station`과 `api-token` 헤더를 사용함 | 확인 | 타슈 공식 설명서와 2026-07-21 무권한 `400/error_code=1001` 응답으로 경로·인증 요구를 확인. 승인 키의 200 응답은 아직 없음 | `fixtures/api/direct_tashu/200_01.redacted.json`, redacted headers |
| F-02 | 직접 API 공식 계약은 `id,name,name_en,name_cn,x_pos,y_pos,address,parking_count`를 제시함 | 확인 | 공식 설명서의 공개 예시로 필드 정의를 확인. 실제 타입·nullability·페이지네이션·추가 필드는 승인 키 200 전까지 미확인 | 실제 200 응답 schema report |
| F-03 | 직접 API 공개 계약에는 개별 자전거 ID·고장 상태·총 용량·원천 관측시각이 없음 | 확인 | 공개 원문의 필드 집합에서 부재를 확인했지만 실제 200 응답의 미문서 필드 존재 가능성은 별도 검사 | 실제 200 응답의 키 집합 |
| F-04 | 직접 API 설명서에서 `x_pos`는 위도, `y_pos`는 경도로 정의함 | 확인 | 공식 공개 정의 기준. 실제 200 좌표 범위와 지도 표본 대조는 아직 필요 | 실제 200 fixture의 좌표 범위·지도 표본 대조 결과 |
| F-05 | data.go.kr 15109253은 **현재 재고 API가 아니라 정적 대여소·거치대 메타데이터 계약**임 | 확인 | 공식 내장 Swagger의 item은 `kioskNo,year,signgu,lcNm,lcDc,adres,dfrCo,kioskId,commWire,wireNo,loCrdnt,laCrdnt`이며 현재 대여가능 수 필드가 없음. 카탈로그 본문의 “이용 가능 수량” 문구와 충돌함 | Swagger 원문 해시, 실제 200 schema report |
| F-06 | 전국 통합 API 15126639은 대전 코드 `3000000000`과 현재 대여소 수량 후보 `bcyclTpkctNocs`를 공개 계약에 포함함 | 확인 | 공식 Swagger의 `/inf_101_00010002_v2` 기준. 자동승인·개발 5,000회/일은 카탈로그확인이고, 실제 의미·지연·페이지 최대크기·200 응답은 미확인 | `fixtures/api/national_integrated/200_01.redacted.json`, response metadata |
| F-07 | 직접 API와 전국 통합 API가 같은 시점·같은 의미·같은 정류장 ID의 재고를 제공함 | 미확인 | 둘 다 원천 관측시각이 없고 통합 API가 직접 API를 지연 재배포할 가능성도 있음 | §3의 7일 동시 수집 비교 보고서 |
| F-08 | 공식 대여이력 ZIP은 20개 월별 CSV, 19열, 원본 합계 9,320,018행을 포함함 | 확인 | 2026-07-21 원본 직접 다운로드·strict decode·streaming profile. 포털 표기 4,168,667행과 불일치 | SHA-256 `B43E78C373050D0AAE2208DB037538187066C565B7D5833F462B2EA94D42560B`, `csv_profile.json` |
| F-09 | 원본 이벤트 범위는 대여 `2024-08-01 05:00:05`~`2026-03-31 23:59:55`, 반납은 `2026-04-01 09:27:00`까지임 | 확인 | 파일명상 20개월과 실제 min/max를 분리해 확인. 연 1회 갱신은 카탈로그 정책일 뿐 각 파일이 1년치라는 뜻이 아님 | 월별 행수·min/max profile |
| F-10 | trip events만으로 과거 절대 `parking_count` 또는 `y_stockout`을 재구성할 수 없음 | 확인 | 초기 재고, 재배치·정비 이동, API 누락·지연과 구간 내 사건 순서를 알 수 없기 때문 | 해당 없음(데이터 구조상 한계) |
| F-11 | 충분한 기간·해상도의 station snapshot을 소급 확보할 수 있음 | 미확인 | 두 재고 후보 모두 과거 snapshot 조회 계약이 없으므로 지금부터 직접 수집해야 함 | snapshot 기간·간격·결측 보고서 |
| F-12 | `parking_count`에 잡힌 자전거가 실제로 대여 불가한 사례가 반복됨 | 추정 | API값·현장 상태·실제 대여 시도를 같은 시각에 결합한 독립 표본이 없음 | 블라인드 현장 점검 라벨 |
| F-13 | KMA API Hub는 발행시각 `tmfc/baseDate+baseTime`과 유효시각 `tmef/fcstDate+fcstTime`을 분리한 단기·초단기 예보 계약을 제공함 | 확인 | 공식 계약상 5km 격자, 단기예보 보유기간 2008-10-30 17 KST 이후·일 8회 발표·유효값 1시간 간격, 초단기예보 10분 발표·6시간 범위. 무키 호출은 401; 승인 키로 과거 vintage 실제 조회·대전 격자 매핑은 미확인 | `fixtures/context/weather_forecast/200_01.redacted.json`, grid/version report |
| F-14 | ASOS 시간자료 API는 대전 지점 `133`의 시간별 기온·강수·습도·풍향·풍속과 QC 필드를 제공하는 계약임 | 확인 | 공식 계약상 자동승인·개발 10,000회/일, D-1까지 조회. 실제 키 응답·availability delay는 미확인 | `fixtures/context/weather_observation/200_01.redacted.json`, availability report |
| F-15 | 한국천문연구원 특일 API는 `locdate,dateKind,isHoliday,dateName`을 제공하지만 공표시각·revision 필드가 없음 | 확인 | 공식 계약과 무키 401을 확인. 자동승인·개발 10,000회/일은 카탈로그확인; 과거 개정 이력 재현 가능성은 미확인 | `fixtures/context/calendar/200_01.redacted.xml`, first-seen/version report |
| F-16 | 에어코리아 대기오염정보 API가 대기질 후보 원천으로 존재함 | 카탈로그확인 | Core 필수 입력이 아니며 실제 응답·측정소 매핑·증분 성능은 미검증 | `fixtures/context/air_quality/200_01.redacted.json`, optional ablation report |
| F-17 | 대전 행사 일정의 발행·수정·취소 이력을 point-in-time으로 재현할 단일 원천이 있음 | 미확인 | 현재 공식 원천·과거 revision·장소 좌표·예상 규모의 이용 가능성을 확정하지 못함 | source decision record, versioned event fixtures |

### 2.3 근거 링크와 조사 이력

- [타슈 OpenAPI 공식 설명서](https://bike.tashu.or.kr/noticeDetail.do?seq=28)
- [공공데이터포털 직접 타슈 API 등록 15119663](https://www.data.go.kr/data/15119663/openapi.do)
- [공공데이터포털 대전광역시 타슈정보 15109253](https://www.data.go.kr/data/15109253/openapi.do)
- [공공데이터포털 전국 공영자전거 실시간 통합 API 15126639](https://www.data.go.kr/data/15126639/openapi.do)
- [공공데이터포털 타슈 대여이력 15137219](https://www.data.go.kr/data/15137219/fileData.do)
- [기상청 API Hub 동네예보 계약](https://apihub.kma.go.kr/apiList.do?seqApi=10&seqApiSub=286)
- [기상청 ASOS 시간자료 조회서비스](https://www.data.go.kr/data/15057210/openapi.do)
- [한국천문연구원 특일 정보](https://www.data.go.kr/data/15012690/openapi.do)
- [한국환경공단 에어코리아 대기오염정보](https://www.data.go.kr/data/15073861/openapi.do)
- [기존 API 조사 기록](../research/R1_타슈API분석.md)

공식 페이지의 카탈로그 문구도 실제 승인 키의 응답 또는 다운로드 원본보다 높은 증거로 취급하지 않는다. 기존 조사 기록은 출처 탐색용이며, 이 문서의 등급을 자동으로 `확인`으로 올리지 않는다.

---

## 3. 실제 HTTP 200 응답 검증 게이트

### 3.1 공통 수집 규칙

1. 직접 API와 전국 통합 API 키는 정식 발급 경로로만 얻고 저장소에 커밋하지 않는다. 15109253은 정적 메타데이터 수집기로 분리하며 재고 poller에 연결하지 않는다.
2. 키 발급 직후 페이지 최대크기·응답 지연·호출한도를 측정해 **1분 raw snapshot 수집 가능성**을 먼저 검증한다. 가능하면 매분 원본을 불변 저장하고, 학습·서빙 feature는 매 5분 정각 cutoff에서 `cutoff` 이전 최신 raw만 선택한 **5분 canonical grid**로 만든다. raw를 5분 평균하거나 미래 raw로 보간하지 않는다.
3. 직접 API와 전국 통합 API를 같은 네트워크에서 **연속 7일** 동시 수집한다. 같은 비교쌍의 요청 시작시각 차이는 목표 30초, 최대 60초로 기록한다. 한도·페이지네이션 때문에 1분이 불가능하면 가능한 최단 간격과 손실을 보고하고, 5분보다 느리면 15분 라벨 운영 후보로 승인하지 않는다.
4. 본문 원본, HTTP 상태, `Content-Type`, 요청 시작·응답 완료시각, 응답 바이트 수, 페이지 관련 메타데이터와 raw SHA-256을 보존한다. 키·쿠키·개인정보는 fixture 생성 전에 제거한다.
5. raw 응답과 정규화 결과를 분리한다. 벌크 응답 전체를 정류장 행마다 중복 저장하지 않는다.
6. 200 외에도 무권한, 잘못된 파라미터, rate limit, timeout fixture를 가능한 범위에서 확보한다. 고의로 한도를 소진하지 않는다.

권장 artifact 구조:

```text
fixtures/api/
  direct_tashu/200_01.redacted.json
  national_integrated/200_01.redacted.json
  static_metadata_15109253/200_01.redacted.json
  errors/unauthorized.redacted.json
reports/
  api_schema_comparison.json
  api_schema_comparison.md
  dual_source_7d.json
  api_fixture_manifest.json
```

manifest에는 파일별 SHA-256, 수집시각, 원천, HTTP 상태, redaction 규칙 버전을 기록한다.

### 3.2 정규화 스키마

원천 응답은 어댑터를 거쳐 아래 형태로만 애플리케이션에 전달한다. 바깥 객체를 내부 `StationObservationBatch`, `stations[]`의 각 항목을 `StationObservation` 계약으로 부르며 live와 demo adapter가 같은 구조를 구현한다.

```json
{
  "data_source": "direct_tashu|national_integrated|demo",
  "collected_at": "2026-07-21T14:05:00+09:00",
  "source_observed_at": null,
  "observed_at": "2026-07-21T14:05:00+09:00",
  "observed_at_basis": "collected_at",
  "poll_id": "uuid",
  "stations": [
    {
      "source_station_id": "ST0003",
      "station_id": "ST0003",
      "name": "탄방동 한사랑병원",
      "address": "대전광역시 ...",
      "lat": 36.348446,
      "lon": 127.390052,
      "bikes_available": 0,
      "capacity": null,
      "capacity_source": null
    }
  ]
}
```

출처 이름은 계층별로 다음처럼 고정한다. 외부 응답과 adapter 계약에는 canonical `data_source`만 노출하고, 수집 저장소의 `source`·`mode`는 운영 메타데이터로만 사용한다.

| 외부/adapter `data_source` | `ingestion_run.source` | `ingestion_run.mode` |
|---|---|---|
| `national_integrated` | `national_integrated_inventory` | `live` |
| `direct_tashu` | `tashu_direct_inventory` | `live` |
| `demo` | `fixture` | `demo` |

15109253의 정적 행은 `station_metadata.source="daejeon_static_15109253"`로만 저장하며 `StationObservationBatch.data_source` 값이 될 수 없다.

source가 바뀌면 같은 연속 시계열로 조용히 이어 붙이지 않고 전환 이벤트와 별도 품질 구간을 기록한다.

검증 규칙:

- `station_id`, `name`, `lat`, `lon`, `bikes_available`는 정상 행에서 필수다.
- 직접 원천 `parking_count` 또는 전국 통합 원천 `bcyclTpkctNocs`를 `bikes_available`로 이름만 정규화하며 차감·보정하지 않는다. 값은 정수이며 `>= 0`이어야 한다. 통합 필드가 실제 대여가능 수와 같은 의미라는 것은 §3.3 게이트 전에는 확정하지 않으며, 원천이 문자열이면 어댑터가 명시적으로 변환하고 원본 타입을 보고서에 남긴다.
- 대전 운영 범위를 넉넉히 포함하는 `35 <= lat <= 38`, `125 <= lon <= 130`을 벗어나면 격리한다.
- 한 poll 안에서 `source_station_id`는 유일해야 한다.
- API 전체 실패는 station 행에 마지막 값을 forward-fill하지 않는다. `ingestion_run` 실패로 기록한다.
- 특정 station만 누락·오류인 경우 `bikes_available=null`, `is_missing=true`를 허용하는 별도 ingestion 계약을 사용하되 정상 `station_snapshot` 행으로 저장하지 않는다.
- 15109253의 `dfrCo`를 `capacity` 후보로 조인하더라도 ID·좌표 매핑, `capacity >= bikes_available`, 시간상 안정성과 적용시점을 확인하기 전에는 `capacity_source='daejeon_static_15109253'`로 승격하지 않는다.

### 3.3 두 경로 비교표

7일 동시 수집의 각 비교쌍과 일별 집계에서 다음을 계산한다.

| 비교 항목 | 산출값 |
|---|---|
| 응답 envelope | 배열/`results`/페이지네이션 구조, next 처리 방식 |
| 필드 계약 | 키 집합, 타입, null 비율, 추가·누락 필드 |
| 정류장 집합 | 건수, ID Jaccard, 한쪽에만 있는 ID 목록 |
| 메타데이터 | 이름·주소·좌표 불일치율 |
| 동시성 | 경로 간 수집시각 차이 |
| 현재 대수 | 동일 ID의 exact match율, 절대차 중앙값/P95 |
| 용량 | 존재율, `capacity < parking_count` 위반율, 3회 호출 간 변화 여부 |

두 경로를 “동일 데이터의 대체 경로”로 취급하려면 7일 전체와 각 일자에서 다음을 만족해야 한다.

- ID Jaccard `>= 0.99`
- 좌표 허용오차 `<= 0.0001°` 내 일치율 `>= 0.99`
- 호출 시각 차이 60초 이하인 쌍에서 정규화 `bikes_available` exact match율 `>= 0.95` 또는 불일치가 측정된 갱신 지연으로 설명됨
- 필수 필드 타입·nullability가 정규화 어댑터로 손실 없이 변환됨

추가로 source별 freshness를 직접 관측할 수 없으므로 동일 정류장의 변화 감지시각 차이 분포와 교차상관 최대 lag를 보고한다. 두 경로가 함께 변하는 것은 독립성의 증거가 아니다. 통합 API가 직접 API를 지연 재배포하는 것으로 보이면 장애 이중화가 아니라 접근 경로 이중화로만 분류한다.

하나라도 실패하면 두 경로는 별도 source로 운영한다. 자동 failover 시 기존 source와 섞어 하나의 연속 시계열로 만들지 않고, UI에 source 전환·데이터 지연을 표시한다.

### 3.4 사용 승인 게이트

다음 조건을 모두 충족해야 해당 경로를 실시간 주 경로로 사용한다.

- 유효한 200 fixture 3개와 schema report가 있음
- 연속 7일 dual-source 보고서가 있고 주 원천·보조 원천·전환 규칙이 승인됨
- 전체 페이지를 끝까지 읽는 방식이 검증됨
- 필수 필드 파싱 성공률 100%, 중복 station ID 0건, 음수 `parking_count` 0건
- 인증 실패·timeout·부분 누락이 `is_missing` 또는 poll 실패로 기록되고 고장/정체신호를 만들지 않는 contract test 통과
- UI의 `observed_at`과 `observed_at_basis`가 함께 검증되어 원천 관측시각인지 수집시각인지 구분됨

게이트 실패 시 저장 fixture 기반 `demo` source만 허용하며 “실시간”이라고 표시하지 않는다.

---

## 4. Fixture 및 schema contract test

### 4.1 필수 fixture 세트

- direct 200 최소 3개, 전국 통합 200 최소 3개, 15109253 정적 metadata 200 최소 1개
- direct·전국 통합의 7일 동시 raw snapshot과 source별 5분 canonical grid 표본
- 빈 결과, 필드 누락, null 좌표, 문자열 `parking_count`, 중복 ID
- HTTP 400/401, 429(실제 응답을 안전하게 얻을 수 있을 때만), 500, timeout
- source 전환과 전체 poll 실패
- 기상 예보 동일 `valid_at`의 서로 다른 `issued_at` vintage, 발행 지연·결측·stale 응답
- 공휴일 calendar version과 행사 생성·수정·취소 snapshot, `available_at`이 없는 격리 표본
- 정류장 graph version, 인접 정류장 결측·시간 비동기 표본
- 데모용 정상 변화·재고 소진·정체신호 시나리오. 데모 fixture에는 `synthetic: true`를 넣는다.

### 4.2 자동 검증

- 원천 fixture → 정규화 fixture golden test
- JSON Schema/Pydantic validation
- `x_pos/y_pos` 변환 및 좌표 범위 test
- 페이지네이션 종료·중복 제거 test
- 실패 시 last value를 새 관측처럼 기록하지 않는 test
- schema drift test: 알 수 없는 필드는 raw에 보존하되 제품 모델에 자동 승격하지 않음
- 예측 cutoff보다 늦은 weather/event/calendar/neighbor 행을 point-in-time join이 거부하는 test
- 실제 `강수 없음`·`행사 없음`과 source 결측을 서로 다른 값으로 보존하는 test
- 전체 feature provenance에서 `uses_synthetic_context=true`가 계산되고 최종 API `response_mode=demo`가 되는 contract test. 공개용 evidence에 선택되지 않은 합성 feature도 포함한다.

fixture 변경은 manifest 해시와 schema diff가 함께 변경될 때만 승인한다.

---

## 5. 대여이력 CSV 품질 게이트

### 5.1 2026-07-21 확인 원본 프로파일

직접 다운로드한 공식 ZIP을 strict decode와 streaming scan으로 검사한 결과는 다음과 같다. 이는 카탈로그 예상값이 아니라 원본 검사값이다.

| 항목 | 확인값 | 처리 원칙 |
|---|---|---|
| 원본 | ZIP 493,887,524 bytes, 해제 합계 2,523,171,244 bytes, 월별 CSV 20개 | SHA-256 `B43E78C373050D0AAE2208DB037538187066C565B7D5833F462B2EA94D42560B`를 canonical artifact ID로 사용 |
| 스키마 | 20개 파일 모두 같은 19열 header, CSV malformed row 0건 | 카탈로그 설명보다 실제 header 우선 |
| 인코딩 | CP949 9개, UTF-8 BOM 11개 | ZIP 전체에 단일 인코딩을 강제하지 않고 member별 BOM/strict decode |
| 원본 행수 | 9,320,018행 | 포털 표시 4,168,667행과 불일치. 원인을 확인하기 전 어느 쪽도 “연간 이용량”으로 인용 금지 |
| 실제 시각 범위 | 대여 `2024-08-01 05:00:05`~`2026-03-31 23:59:55`, 반납은 `2026-04-01 09:27:00`까지 | 파일명 대신 파싱한 min/max 사용 |
| 2025-12 파일 | 행수 203,545건이며 2025-01 구간의 trip 자연키와 대여시각을 담고 있음 | 공급자 정정 전 파일 전체 격리. 단순 중복제거 후 “2025-12 데이터”로 사용 금지 |
| 장애 공백 | 2025-02-26 15:27 이후 중단, 2025-03-04 11:02 재개. 2025-02-27~03-03은 대여 0건 | 0수요가 아닌 source outage로 마스킹하고 train/calibration/test에서 제외 |
| 시각 정밀도 | 2025-03은 초가 없고 일부 시각은 한 자리 hour | 포맷별 명시 파서와 원본 정밀도 flag 사용 |
| 정류장 | 전체 고유 대여 ID 1,425개, 반납 ID 1,417개. 월별 고유 대여 정류장은 약 1,190개에서 약 1,380개로 증가 | 고정 station universe를 과거에 소급하지 않고 `station_active_from/to`를 fold별 생성 |
| 정류장 메타 변화 | 대여 정류장 ID 중 804개는 둘 이상의 명칭 문자열, 470개는 둘 이상의 좌표 문자열을 가짐 | 실제 이전으로 단정하지 않고 명칭 정규화·좌표 정밀도·버전 변경을 분리한 mapping table 생성 |
| 관제센터 | raw 기준 대여측 명칭 269,653행, 반납측 명칭 288,216행에 `관제센터` 포함하며 둘 중 하나라도 해당하는 행은 491,951건(약 5.28%) | 포털 유의사항상 관리자 강제처리 가능성이 있으므로 일반 이용 수요와 별도 flag·ablation |
| 이동 품질 slice | 대여·반납 정류장이 같은 행은 약 9.27%, 거리 0 이하 행은 약 6.1% | 자동 삭제하지 않고 이용 패턴·측정오류·운영성 행을 구분해 포함/제외 민감도 보고 |
| 15분 수요 희소성 | 월별 station×15분 grid에서 대여 1건 이상인 bin은 약 4.5~11.8% | **trip 수요 이벤트 희소성** 참고치일 뿐 `y_stockout` 양성률이 아님. 0건 bin을 stockout/재고 0으로 라벨링 금지 |

월별 정류장 수와 15분 양성 bin 비율은 원본에 대한 임시 탐색 집계의 근사 범위다. 해당 집계 코드를 아직 versioned artifact로 보존하지 않았으므로 모델 승인·논문형 수치에는 쓰지 않는다. `csv_profile.json`과 재현 스크립트를 원본 SHA-256에 연결해 다시 산출한 뒤 exact 값으로 승격한다. 반면 ZIP 크기·hash·파일 수·전체 행수·시각 범위·2025-12 자연키 중복·장애 구간·인코딩은 재현 가능한 원본 검사값이다.

이 프로파일은 trip event 품질을 설명할 뿐 과거 `parking_count`를 제공하지 않는다. 특히 15분 bin의 대여·반납 순유입에 임의 초기값을 더하거나 0건 bin을 재고 소진으로 바꿔 `y_stockout`을 만들지 않는다.

### 5.2 원본 보존과 파싱

1. 다운로드 시각, 원본 파일명, byte size, SHA-256을 기록하고 원본은 불변으로 보존한다.
2. `cp949`, `euc-kr`, `utf-8-sig` 순서의 추측 파싱에 의존하지 않는다. 후보별 strict decode 결과를 기록하고 실패 바이트가 없는 인코딩을 채택한다.
3. 필요한 열만 `chunksize`로 읽어 메모리 사용을 제한하고, 정규화 결과는 typed Parquet로 저장한다.
4. 헤더를 카탈로그 예상값과 비교하되 실제 헤더를 우선한다. 행수 차이는 삭제·중복제거로 숨기지 않고 원본/유효/격리 건수를 나눠 보고한다.

### 5.3 행 단위 검사

| 검사 | 규칙 | 초기 승인 기준 |
|---|---|---|
| 필수 열 | 자전거번호, 대여·반납 시각, 대여·반납 장소를 식별할 열 | 100% 존재, 아니면 중단 |
| 시각 파싱 | KST로 명시적 파싱, timezone-naive 원본 여부 기록 | 성공률 `>= 99.9%` |
| 시간 순서 | `return_at >= rental_at` | 위반 `<= 0.1%`, 위반행 격리 |
| 이용시간 | 제공 이용시간과 계산값 차이 분포 | P99 차이 보고, 체계적 단위 오류 시 중단 |
| 거리 | 음수 금지, 극단값 별도 격리 | 음수 0건(정제 결과 기준) |
| 좌표 | §3 좌표 범위, 위경도 뒤바뀜 탐지 | 유효율 `>= 99.0%` |
| 중복 | `(bike_id,rental_at,return_at,rental_station,return_station)` 자연키 | 중복률 보고, `>0.5%`면 원인 확인 전 중단 |
| 결측 | 열별·월별·정류장별 null 비율 | 필수 식별/시각 결측행 격리 |

임계 미달 파일은 자동으로 억지 정제해 학습에 넣지 않는다. 원인을 확인해 규칙을 버전업하거나 해당 기간을 평가 대상에서 제외한다.

확인된 원본에는 다음 선행 quarantine을 적용한다.

- 2025-12 member 전체: 2025-01 trip 자연키 중복·월 오표기
- 2025-02-26 15:27 이후~2025-03-04 11:02 이전: 시스템 장애 구간
- 관제센터가 대여 또는 반납 대여소인 행: 일반 수요 모델과 분리하고 포함/제외 ablation으로만 검토
- 2025-03 시각: 초 정밀도를 임의 생성하지 않고 분 정밀도임을 보존

### 5.4 기간·누수·정류장 매핑 검사

- 실제 `min(rental_at)`, `max(return_at)`과 월별 행수를 보고한다. 행수만으로 “연간 이용량”이라 부르지 않는다.
- 최신 8주와 이전 기간의 정류장 수·대여량 분포를 비교해 서비스 개편·코로나·계절 변화 같은 구조적 단절을 표시한다.
- 같은 자전거가 겹치는 시간대에 두 번 대여된 기록, 비정상적으로 긴 이용, 대규모 동일 timestamp를 탐지한다.
- 현재 API station과 CSV station의 ID exact match율을 먼저 계산한다. 이름 정규화+좌표 근접 매핑은 보조 수단이며 1:N/N:1 충돌은 자동 병합하지 않는다.
- 해커톤 대상 5~10개 정류장은 매핑률 100%가 아니면 해당 정류장을 예측 대상에서 제외한다. 전체 서비스 학습은 현행 활성 정류장 기준 매핑률 `>= 95%`를 1차 승인 기준으로 둔다.
- 시간 분할 이후의 통계·정류장 목록·임계값을 과거 fold에 주입하지 않는다.

필수 산출물은 `csv_profile.json`, `csv_quarantine.parquet`, `station_mapping.csv`, `station_mapping_conflicts.csv`다.

---

## 6. 어떤 데이터로 무엇을 검증할 수 있는가

| 질문/산출물 | trip events만으로 검증 | station snapshots 필요 | 현장/정비 라벨 필요 |
|---|---:|---:|---:|
| 정류장·요일·시간대별 대여 건수 | 가능 | 아니오 | 아니오 |
| 반납 건수와 순유입(`returns-rentals`) | 가능 | 아니오 | 아니오 |
| 역사적 수요 압력 등급 | 가능 | 아니오 | 아니오 |
| 15분 순유입 예측 오차 | 가능 | 아니오 | 아니오 |
| 과거 시점의 절대 `parking_count` | 불가 | **필수** | 아니오 |
| `P(parking_count(t+15)>=1)` | 불가 | **필수** | 아니오 |
| 실제 대여 성공 확률 | 불가 | 불충분 | **대여 시도/현장 라벨 필수** |
| 정체 지속시간과 인접 정류장 변화 | 불가 | **필수** | 아니오 |
| 정체가 실제 고장이었는지 | 불가 | 불충분 | **필수** |
| 고장 자전거 대수·보정 이용가능 대수 | 불가 | 불가 | 자전거 단위 공식/현장 데이터 필요 |

trip events의 누적 순유입은 초기 재고, 운영자 재배치, 정비 회수, 누락 이벤트를 모르므로 절대 재고가 아니다. 이 값에 임의 상수를 더해 과거 snapshot처럼 사용하지 않는다.

날씨·휴일·행사·공간 맥락의 추가 가치는 trip events만으로 검증할 수 없다. 고정 타깃을 만드는 station snapshot과 §7.2의 revision 이력이 있는 외부 데이터가 함께 있어야 하며, 현재값만 남아 과거 vintage를 복원할 수 없는 원천은 contextual 운영 후보 평가에서 제외한다.

---

## 7. 맥락 기반 15분 재고 소진 위험 모델 계약

이 절에서 말하는 AI는 날씨·달력·행사·공간 맥락과 재고 시계열을 학습하는 **지도학습 확률 모델**이다. LLM은 타깃, feature, 등급, 대안 정류장 또는 행동을 계산하지 않는다. 표현 문구를 생성하더라도 모델이 산출한 구조화 결과만 설명하며 수치나 인과를 추가하지 않는다.

### 7.1 고정 타깃과 주장 경계

검증된 station snapshot이 확보된 경우에만 다음 이진 타깃을 만든다.

```text
y_stockout(s,t) = 1[bikes_available(s, t+15분) < 1]
p_stockout_15m  = P(y_stockout=1 | t 시점까지 사용 가능했던 정보)
p_available_15m = 1 - p_stockout_15m
```

승인된 `stockout_risk` API는 보정 후 `p_stockout_15m`을 `stockout_probability`로 반환한다. 다른 mode에서는 이 필드가 null이며, 어떤 화면·로그·발표에서도 실제 대여 성공·정상 자전거·고장 확률로 바꾸어 부르지 않는다.

- horizon은 정확히 `15분`으로 고정한다. 모델별로 더 잘 나온 horizon을 사후 선택하지 않는다.
- 학습 cutoff는 KST 5분 canonical grid로 고정한다. 각 grid 시각에는 그 시각 **이전**의 최신 raw snapshot만 붙이고 age를 기록한다. 1분 raw 수집이 가능하면 기본 freshness 상한은 90초이며, 더 느린 수집에서는 사전등록한 최대 2분 30초를 넘으면 표본을 버린다. 미래 쪽 nearest snapshot을 붙이지 않는다.
- 기준 grid `t`와 목표 grid `t+15분` 모두에 위 조건의 snapshot이 있어야 표본으로 채택한다. `target_snapshot_age_seconds`를 저장하며 source별 age 분포를 함께 보고한다.
- 두 시각 사이에 source 전환, 전체 poll 실패, station 비활성화가 있으면 제외한다.
- 타깃은 공식 API 집계의 `bikes_available`이다. 실제 현장 대수, 정상 자전거 수, 대여 성공 여부 또는 고장 여부를 뜻하지 않는다.
- 원천 관측시각이 없으면 `collected_at`을 사용하고 `observed_at_basis="collected_at"` 한계를 평가 보고서와 응답에 남긴다.
- 목표 시점의 API 수량을 보정하거나 trip event로 재구성하지 않는다.
- 전체 test와 별도로 `bikes_available(t)>0`인 표본의 Brier·log loss·calibration·false-go를 필수 보고한다. 현재 이미 0대인 쉬운 표본이 전체 점수를 지배하면 “곧 소진될 재고를 예측했다”고 주장하지 않는다. 학습 포함 여부는 사전등록하되 이 조건부 평가는 생략할 수 없다.

외부 등급 필드명은 **`stockout_risk_grade`**로 고정한다.

```text
stockout_risk_grade = low | medium | high
```

- `low`: **재고 소진 위험이 낮음** — 15분 뒤 API 재고가 1대 이상일 가능성이 상대적으로 높다.
- `medium`: **재고 소진 위험이 중간** — 다른 정류장·출발 시각과 함께 비교한다.
- `high`: **재고 소진 위험이 높음** — 15분 뒤 API 재고가 0대일 가능성이 상대적으로 높다.

검증된 snapshot·최신 원천·평가 근거가 부족하면 `decision_signal.mode="unavailable"` 또는 §8의 강등 모드를 사용하고 `stockout_risk_grade=null`로 둔다. 데이터 부족을 네 번째 위험 등급으로 만들지 않는다. 등급은 **소진 위험의 방향**이므로 `high`를 “대여 가능성 높음”으로 렌더링하면 contract 위반이다. 응답에는 `grade_direction="higher_means_higher_stockout_risk"`, `horizon_minutes=15`, 기준시각, 모델·feature·임계값 버전을 함께 넣는다.

### 7.2 외부 데이터 시점 계약과 point-in-time join

snapshot, 날씨, 휴일, 행사, 공간 데이터 등 모델에 들어가는 **모든 외부 원천 행**은 다음 필드를 가진다.

| 필드 | 의미 | 규칙 |
|---|---|---|
| `event_time` | 행이 설명하는 관측·발효·예보 유효 시각 | timezone을 포함한다. 날씨 예보는 예보가 유효한 시각, 정적 데이터는 `effective_from`에 해당한다. |
| `available_at` | 해당 값 또는 그 revision을 외부에서 처음 알 수 있었던 시각 | 파일 수정시각을 추측해 채우지 않는다. 입증할 메타데이터가 없으면 행을 격리하거나 보수적 공개시각을 쓴다. |
| `ingested_at` | 우리 시스템이 그 revision을 처음 원본 그대로 저장한 시각 | backfill로 과거 시각을 덮어쓰지 않는다. 재수집도 새 revision 행으로 남긴다. |
| `source_version` | 공급자·dataset·schema·revision을 재현할 식별자 | URL만 쓰지 않고 원본 해시 또는 공급자 revision을 manifest에 연결한다. |

필요하면 `forecast_issued_at`, `valid_from`, `valid_to`, `revision_id`를 추가하지만 위 네 필드를 대체하지 않는다. 학습 표본 `(station_id=s, cutoff=t)`은 다음 **as-of join**만 허용한다.

```text
effective_available_at = max(available_at, ingested_at)
채택 가능 조건          = effective_available_at <= t
선택                    = 같은 자연키 중 t 이전에 사용 가능했던 최신 revision
```

- 정류장 재고는 `event_time <= t`인 마지막 유효 snapshot만 쓴다. source 전환·결측 구간을 보간하거나 미래 snapshot에서 역산하지 않는다.
- 날씨는 `t` 이전에 발행·수집되어 있었고 `t+15`를 유효 구간에 포함하는 **예보 vintage**를 선택한다. 여러 vintage가 있으면 `effective_available_at <= t`인 최신본만 쓴다.
- 행사·휴일·공간 데이터의 정정도 동일한 revision 규칙을 따른다. 나중에 수정된 현재 테이블을 과거 모든 행에 덮어씌우지 않는다.
- offline feature store는 각 feature 값의 원천 행 ID와 네 시각·버전을 추적할 수 있어야 한다. join 후 `effective_available_at > cutoff`인 행이 1건이라도 나오면 해당 dataset build를 실패시킨다.
- 연구용으로 `available_at <= t`만 적용한 oracle 결과를 만들 수는 있으나 운영 후보 평가·승격에는 사용하지 않고 명확히 `oracle_only=true`로 분리한다.

공식 맥락 원천의 현재 확인 범위와 추가 게이트는 다음과 같다.

| 원천 | 공개 계약에서 확인한 시점·스키마 | 아직 미확인인 것 | 운영 저장 규칙 |
|---|---|---|---|
| KMA 단기예보 | 5km 격자, 공식 보유기간 2008-10-30 17 KST 이후, `tmfc` 또는 `baseDate/baseTime` 발표시각, `tmef` 또는 `fcstDate/fcstTime` 유효시각, 일 8회 발표·유효값 1시간 간격. `TMP,PTY,POP,PCP,REH,WSD` 등 | 승인 키 200, 과거 vintage 실제 조회, 대전 station→grid 매핑, 정정 revision과 실제 availability delay | 발표본별 raw와 hash를 보존하고 `issued_at<=t`, `valid_at`이 `t+15`를 포함하는 최신 vintage만 선택 |
| KMA 초단기예보·실황 | 초단기예보 10분 발표·6시간 범위, 실황은 2024-03-04 이후 10분 발표. `T1H,PTY,RN1,REH,WSD` 등 | 과거 전 기간의 실제 조회 가능성·지연·결측 | 실황은 `observed_at`뿐 아니라 최초 수신 `available_at`을 보존. `t` 이후 실황은 feature 금지 |
| ASOS 시간자료 | 대전 지점 `133`, 시간별 `tm,ta,rn,hm,wd,ws`와 QC field, 포털 계약상 D-1까지 | 승인 키 200과 실제 공표 지연 | 과거 학습·QC용. `t+15` 실제 관측값은 사후 평가에는 쓸 수 있지만 예보 feature 대체 금지 |
| KASI 특일 | `locdate,dateKind,isHoliday,dateName`; 공표시각·revision 필드 없음 | 지원 연도, 개정 이력, 임시·대체공휴일의 당시 공표시각 | 최초 수신시각·raw hash를 자체 보존. 현재 응답을 과거 fold 전체에 소급 적용하지 않음 |

초단기예보의 강수확률 `POP`처럼 제공 시작일이 바뀌는 변수는 전체 기간에 조용히 backfill하지 않는다. 공식 계약상 초단기 `POP`는 2026-06-23 12 KST 이후 제공되므로 초기 공통 feature에서 제외하거나 `feature_available`과 source contract version을 함께 두고 별도 ablation한다.

### 7.3 허용 feature 집합

| 그룹 | 허용 feature 예시 | 시점·품질 제약 |
|---|---|---|
| 재고 이력 | 현재값, 5·10·15·30·60분 lag, 5·15·30분 변화량·기울기, rolling 변동성, 연속 0대 시간, 결측 indicator | 모두 `event_time <= t`. 미래값 보간 금지. source별 계산 후 전환 구간 제외 |
| 날씨 예보 | `t+15`의 강수 확률·형태·강도, 기온·체감온도, 습도, 풍속, 적설 및 forecast lead time | `t` 이전 사용 가능 vintage만 허용. 같은 시각의 미래 **실제 관측 날씨**로 교체 금지 |
| 시간·휴일 | 시각의 주기형 encoding, 요일, 출퇴근대, 주말, 법정공휴일·대체공휴일 | 달력 revision이 `t`에 알려져 있어야 함. 휴일 feature 정의와 timezone 고정 |
| 행사 snapshot | 당시 공개된 시작·종료, 유형, 장소, 예상 규모 구간, 정류장까지 거리, `t` 시점의 취소 상태 | `t` 이후 발표된 취소·실제 관객 수·사후 결과 금지. 행사 공지 snapshot과 revision 보존 |
| 주변 정류장 | 사전 정의된 이웃의 `t` 이하 재고 lag·변화, 가중 합계, 이웃 결측률 | 이웃 그래프 버전 고정. 이웃의 `t+15` 타깃 또는 미래 변화 금지 |
| 정적 공간 특성 | 정류장·환승시설·대학·상업지·공원까지 거리, 토지이용·POI 밀도, 사전 정의된 공간 cluster | `source_version`과 발효시각 고정. 평가 대상 이후 정보로 POI를 보강하지 않음 |

feature 계산 코드는 이름, 단위, null 처리, lookback, source version을 `feature_registry`에 버전으로 등록한다. 결측을 0으로 조용히 바꾸지 않으며 그룹별 freshness와 missing indicator를 보존한다.

다음 정보는 모델 입력과 파생 feature에서 **금지**한다.

- `t+15`의 실제 날씨 관측값, 목표 구간 trip event, 목표 snapshot, 이웃 정류장의 미래값
- `t` 이후 알려진 행사 취소·장소 변경·관객 수·결과 또는 현재 페이지로 과거를 덮어쓴 행사 정보
- 사용자의 현재·과거 위치, 검색 좌표·검색어, 이동 경로, 개인 식별자나 세션 행동
- 커뮤니티 신고, 공식 정비 상태, 피드백 정답, 신고·정비·설명 텍스트 및 그 임베딩
- LLM이 추론하거나 보완한 날씨·행사·재고·고장 feature

사용자 위치는 가까운 정류장 조회와 화면 정렬에만 사용할 수 있고 모델 확률에는 영향을 주지 않는다. 신고·정비 상태는 독립 상태축으로만 표시하며 재고 소진 확률의 ground truth나 feature로 혼합하지 않는다.

### 7.4 기준선과 후보 모델

모든 outer test fold에서 다음을 같은 표본·같은 cutoff로 함께 평가한다.

1. **B0 재고-only 기준선 묶음**: B0-a persistence는 `bikes_available(t)>=1`이면 `p_available=1-ε`, 아니면 `p_available=ε`, `ε=0.001`로 둔다. B0-b 경험적 전이는 train 안에서만 `P(y_stockout=1 | current_count_bucket)`을 추정한다. 평가·승격에서는 둘 중 더 강한 기준선을 B0으로 사용한다.
2. **B1 역사 버킷**: 학습 구간에서만 계산한 `P(y_stockout=1 | station, day_of_week, hour, current_count_bucket)`에 Laplace smoothing을 적용한다. 표본이 부족하면 station을 제거한 전역 버킷으로 backoff한다.
3. **B2 재고·시간 logistic**: §7.3의 재고 이력과 시간 feature만 사용하는 elastic-net logistic regression. station 효과 사용 여부, regularization과 class weight는 calibration 이전에 고정한다.
4. **B3 투명한 맥락 logistic**: B2에 같은 point-in-time 날씨·휴일·행사·주변 집계·정적 공간 feature를 더한 elastic-net logistic regression. 변환·bin·상호작용은 사전등록하고 계수 방향·결측 경로를 감사 가능하게 남긴다. 복잡한 M1이 아니라 단순한 맥락 결합만으로 얻는 이득을 분리한다. 자체 contextual 게이트를 통과하면 가장 단순한 `contextual_ml` 후보가 될 수 있다.
5. **M1-CB contextual CatBoost**: B3와 같은 point-in-time 입력을 쓰는 CatBoost. categorical·missing 처리, depth, learning rate, iteration과 seed 범위를 사전등록한다.
6. **M1-LGBM contextual LightGBM**: B3와 같은 입력을 쓰는 LightGBM. category encoding, leaves/depth, learning rate, min-data와 seed 범위를 사전등록한다. CatBoost보다 나중에 실행했다는 이유로 더 좋은 모델로 간주하지 않는다.
7. **M2 고급 공간 모델**: temporal graph/attention 등 고급 공간 구조는 선택된 M1 tabular 후보의 맥락 uplift가 미래 holdout에서 승인된 뒤에만 연구한다. M2 착수·복잡성 자체를 성능 근거로 발표하지 않는다.

비교 사다리는 **B3 logistic → M1-CB CatBoost → M1-LGBM LightGBM** 순서로 같은 split·feature contract에서 실행한다. 두 tree 모델에는 동등한 사전등록 tuning budget을 주고, inner train/calibration만으로 family와 hyperparameter를 선택한다. outer fold는 이 선택 절차의 오차를 추정하며, untouched final holdout을 본 뒤 CatBoost와 LightGBM 사이를 바꾸지 않는다. 비선택 family 점수는 `research_comparator=true`, `selection_eligible=false`로 남길 수 있다.

B3와 두 M1은 B0/B1뿐 아니라 B2와 **동시에 비교**한다. 어느 contextual 후보도 B2를 이기지 못하면 맥락 추가 가치가 없으므로 “날씨·행사·공간 맥락을 고려해 더 정확한 AI”라고 주장하지 않고 B2 또는 §8 fallback으로 강등한다. B3가 B2를 이겼지만 선택된 M1이 B3를 이기지 못하면 더 복잡한 M1을 배포하지 않고 B3를 `contextual_ml` 후보로 쓴다. 후보 선택 규칙은 final test 전에 고정하며 모델 종류가 아니라 point-in-time 데이터와 미래 holdout의 추가 성능이 AI 기능의 근거다.

### 7.5 사전등록 ablation과 맥락 slice

비선형 모델 자체의 효과와 맥락 데이터의 효과를 분리하기 위해 `T ∈ {CB, LGBM}`에 대해 같은 split·feature contract와 family별 고정 hyperparameter budget으로 다음 중첩 실험을 사전등록한다.

```text
T-I      = 재고 + 시간
T-IW     = T-I + 날씨 예보
T-IWH    = T-IW + 휴일
T-IWHE   = T-IWH + 행사
T-FULL   = T-IWHE + 주변 정류장 + 정적 공간
```

- `B2 vs B3`는 투명한 맥락의 추가 가치, `B3 vs T-FULL`은 비선형 contextual 모델의 추가 가치, `B2 vs T-I`는 맥락 없는 model family 효과, `T-I vs T-FULL`은 같은 family에서의 전체 맥락 추가 가치를 본다.
- 전체 중첩 경로는 두 family 모두 산출한다. 순서 의존성을 확인하는 leave-one-group-out은 inner selection으로 선택된 `T-FULL`에서 날씨·휴일·행사·주변/공간 그룹을 하나씩 제거해 보고한다.
- full 결과가 나쁜 그룹만 사후 제거해 같은 holdout 점수를 “최종 성능”으로 다시 쓰지 않는다. feature 변경은 새 모델 버전과 새 미래 holdout을 요구한다.
- 각 비교는 Brier·log loss·false-go와 §7.6의 paired station-day/date block bootstrap 95% CI를 함께 보고한다. 표본 수와 CI 없이 작은 차이를 uplift로 부르지 않는다.

전체 지표와 별도로 다음 slice를 사전등록하고 표본 수, 양성률, calibration, false-go를 보고한다.

| 축 | 최소 slice 예시 |
|---|---|
| 날씨 | 건조, 강수 시작 예보, 강수 지속, 눈, 강풍, 기온 구간 |
| 휴일 | 평일, 주말, 법정·대체공휴일, 휴일 전후 |
| 행사 | 행사 없음, 시작 전, 진행 중, 종료 직후, 학습에서 보지 않은 행사 |
| 공간 | 중심/외곽, 환승 인접/비인접, POI 밀도 구간, 학습에서 보지 않은 정류장 |
| 재고·시간 | 전체와 **현재 `>0` 조건부**, 현재 0·1·2·3대 이상, 출퇴근/비출퇴근, 결측률 구간 |

slice별 최소 표본·최소 사건 수는 결과를 보기 전에 평가 등록부에 고정한다. 미달 slice는 합쳐서 성능을 만들지 않고 `insufficient_evidence`로 표시한다. “비 오는 날 개선”, “행사 때 강함” 같은 문구는 해당 slice가 독립 holdout과 등록 기준을 통과할 때만 허용한다.

### 7.6 시간·정류장·행사 holdout

- **시간 outer split**: 시간 순서를 보존한 expanding-window를 사용한다. test 뒤의 데이터로 imputation, category dictionary, scaler, target encoding, 이웃 그래프 또는 임계값을 만들지 않는다.
- **15분 purge**: train→calibration, calibration→test, outer test→다음 구간의 모든 경계에서 라벨 구간 `[t,t+15분]`이 경계를 넘는 표본을 앞 구간에서 제거한다. 최소 15분 purge가 split manifest에 명시되지 않으면 평가를 실패시킨다. feature lookback이 split 뒤 값을 읽지 않는 것은 별도 as-of contract로 검증한다.
- **calibration split**: 각 outer train 끝의 연속 미래 구간을 calibration으로 떼고 Platt/isotonic과 행동 임계값 `τ`를 여기서만 정한다.
- **정류장 holdout**: 지정된 정류장 전체를 train·calibration에서 제거해 unseen-station 일반화를 별도 평가한다. 이 결과 없이 신규 정류장 일반화를 주장하지 않는다.
- **행사 holdout**: 같은 행사 ID 또는 동일 행사 instance의 행이 train과 test에 동시에 들어가지 않도록 event-group split한다. 가능하면 행사장 단위 holdout도 별도 보고한다.
- **최종 holdout**: 모델·feature·slice·임계값 선택에 사용하지 않는다. 한 번 열어 기준을 바꾸면 폐기하고 더 뒤의 미래 구간을 새 holdout으로 지정한다.

station 랜덤 행 분할, 동일 행사의 시간대별 랜덤 분할, 현재 정적 테이블을 과거 fold 전체에 적용하는 방식을 금지한다. 모든 split manifest에는 station/event exclusion 목록, feature cutoff, source version과 기간을 남긴다.

모델 차이의 신뢰구간은 같은 재표본을 모든 후보에 적용하는 **paired block bootstrap**으로 계산한다.

- 1차 CI는 날짜를 block으로 재표본해 같은 날의 전 정류장·날씨·휴일 상관을 보존한다.
- 민감도 CI는 `(station_id, KST date)` station-day block을 재표본해 정류장 내 시계열 상관을 보존한다.
- 행사 slice는 event instance를 추가 group으로 묶어 같은 행사가 양쪽 표본에 쪼개지지 않게 한다.
- iid row bootstrap과 임의 station-row bootstrap만으로 CI를 좁혀 보고하지 않는다.
- 전체와 `bikes_available(t)>0` 조건부 표본 모두에 Brier/log loss/false-go의 paired 차이와 95% CI를 낸다.

### 7.7 지표, 보정과 행동 평가

| 범주 | 지표 | 사용법 |
|---|---|---|
| 주 지표 | **Brier score** | B0/B1/B2/B3 대비 상대 개선율과 paired date·station-day block bootstrap 95% CI 보고 |
| 보조 확률 지표 | **Log loss** | `ε=0.001` clipping 후 보고. 과신 패널티 확인 |
| 보정 | calibration curve, ECE, calibration intercept/slope | calibration fold에서만 Platt/isotonic 적합, test에 고정 적용 |
| 분류 참고 | AUROC, AUPRC | 클래스 비율과 함께 보고하며 단독 성공 기준으로 쓰지 않음 |
| 행동 지표 | GO precision·coverage, false-go rate | B0/B1/B2/B3와 **동일 GO coverage**에서 비교 |

행동 정책:

```text
GO       : p_available_15m >= τ 이고 데이터가 최신이며 정체신호가 없음
CAUTION  : p_available_15m >= τ 이지만 정체신호가 있거나 calibration 범위를 벗어남
NO-GO    : p_available_15m < τ
UNKNOWN  : 데이터 지연·결측·미검증 source
```

`τ`는 calibration 구간의 사전등록 decision loss로 선택하고 test에서는 고정한다. `false-go` 비용을 `false-no-go`의 3배로 두는 값은 현재 **권고 기본값**이지 실측으로 승인된 보편 비용이 아니다. 실제 서비스 비용비·최소 GO coverage는 제품 책임자가 평가 전에 versioned gate에 승인한다. coverage를 줄여 false-go만 낮추는 편법을 막기 위해 동일 coverage 비교와 원래 coverage를 모두 보고한다.

희소 양성을 늘리기 위한 SMOTE는 시계열·정류장 상관과 확률 보정을 훼손할 수 있어 기본 경로에서 사용하지 않는다. class weight나 다른 resampling을 challenger로 쓰면 원래 분포를 유지한 연속 미래 calibration 구간에서 다시 보정하고, 미사용 모델과 함께 Brier·calibration을 비교한다.

보정은 전체 test뿐 아니라 날씨·휴일·행사·공간 slice에서 확인한다. 특정 regime에서 calibration 범위를 벗어나거나 표본이 부족하면 그 regime에 확률을 외삽하지 않고 `current_stock` 또는 §8 fallback으로 강등한다.

### 7.8 관측 기간, regime coverage와 주장 수준

28일·42일은 수집·join·학습 파이프라인을 검증하기 위한 **예비 구간**일 뿐, 날씨·행사·계절 일반화의 충분조건이 아니다.

| 단계 | 기간 권고 | 할 수 있는 일 | 금지되는 주장 |
|---|---:|---|---|
| 파이프라인 점검 | 연속 28일 | snapshot 정합성, as-of join, 누수 test, 1회 train/calibration/test 실행 | AI 성능·날씨 효과·공개 확률 주장 |
| 예비 비교 | 최소 42일 | B0/B1/B2/B3/M1-CB/M1-LGBM 예비 비교, calibration·slice 결측 발견 | 일반화된 contextual uplift 또는 공개 성능 보장 |
| 제한 파일럿 | **연속 12주 권고** | 사전등록 regime coverage와 시간·정류장·행사 holdout을 충족한 범위에서 제한 사용자 검증 | 관측되지 않은 날씨·행사·지역·계절로 확대 |
| 계절 일반화 | **최소 12개월 권고** | 사계절과 주요 기상 regime가 실제 포함된 경우 계절 간 안정성 검토 | 12개월 경과만으로 자동 승인 또는 전국 일반화 |

12주와 12개월은 설계 권고값이며 시간이 지났다는 이유만으로 승인되지 않는다. 비·눈·폭염·한파·휴일·행사·무행사·unseen station 등 **사전등록한 regime coverage matrix**가 비어 있으면 기간을 연장하거나 주장을 해당 범위로 제한한다. 반대로 더 짧은 데이터로 공개 contextual 주장을 허용하려면 누락 regime, 위험과 적용 범위를 명시한 별도 예외 승인이 필요하며 이를 기본 경로로 삼지 않는다.

실제 승격 여부는 test 결과를 보기 전에 고정한 versioned `evaluation_gate` artifact가 결정한다. 이 artifact에는 다음이 있어야 한다.

- 주장 범위와 대상 정류장, 모델·feature·source version
- 기간이 아닌 필수 regime와 slice별 최소 표본·사건 수
- B0/B1/B2/B3 대비 Brier/log loss, calibration, 동일 coverage false-go의 통과 기준
- 시간·정류장·행사 holdout 구성과 bootstrap 단위
- 승인자, 승인시각, 만료·재검토 조건과 실패 시 강등 모드

현재 문서의 초기 **권고 기준**은 모든 시간 test fold에서 B0 대비 Brier 개선, B1 대비 비열화 없음, 사전 선택된 contextual 후보(B3, M1-CB 또는 M1-LGBM)의 B2 대비 uplift에 대한 paired date-block bootstrap 95% CI 하한 `> 0`, ECE `<= 0.10`, B2와 동일 GO coverage에서 false-go 비열화 없음이다. M1을 선택하려면 B3 대비 추가 가치도 별도로 보고하고, M1 family 선택이 inner split에서 끝났음을 증명한다. 이 수치를 그대로 운영 승인으로 간주하지 않는다. `evaluation_gate`는 최소한 `inventory_temporal`과 `contextual_ml` basis별로 따로 채택·서명한다. 승인된 contextual 후보가 없으면 별도 게이트를 통과한 B2 계열 모델을 `decision_signal.mode="stockout_risk"`, `prediction_basis="inventory_temporal"`로 사용한다.

승인된 `inventory_temporal` 게이트마저 없거나 미달하면 재고 소진 확률을 숨긴다. 최신 현재 snapshot을 신뢰할 수 있으면 `current_stock`으로, 그렇지 않고 §8의 과거 대여 표본 게이트만 통과하면 `demand_pressure`로 강등한다.

---

## 8. 예측 이력·게이트가 부족할 때의 강등 모드

다음 중 하나면 확률·재고 예측을 노출하지 않는다.

- 검증된 station snapshot이 없음
- 연속 수집 28일 미만
- API source가 §3 게이트를 통과하지 못함
- 대상 정류장의 CSV 매핑 또는 snapshot 완전성이 기준 미달
- §7.2 point-in-time join 검증이 실패했고 해당 결측 경로에 승인된 별도 모델이 없음
- §7.8의 `inventory_temporal`용 versioned `evaluation_gate`가 미승인·미통과

강등 순서는 다음과 같다.

1. 최신 현재 snapshot이 있고 사전 선택된 contextual 후보(B3, M1-CB 또는 M1-LGBM)의 게이트를 통과하면 `stockout_risk/contextual_ml`을 제공한다.
2. 최신 현재 snapshot이 있고 승인된 contextual 후보는 없지만 별도 검증된 B2 계열 게이트를 통과하면 `stockout_risk/inventory_temporal`로 강등한다. 결측 context를 0으로 바꾸지 않고 `context_status=partial|unavailable`을 그대로 반환한다.
3. 위 두 예측 basis를 모두 사용할 수 없지만 최신 현재 snapshot은 신뢰할 수 있으면 `decision_signal.mode="current_stock"`으로 두고 공식 현재 재고만 제공한다.
4. 최신 현재 snapshot은 없지만 검증된 trip events와 아래 표본 게이트가 있으면 **“역사적 대여 수요 압력”**만 제공한다.
5. 어느 근거도 없으면 `decision_signal.mode="unavailable"`로 둔다.

네 번째 경우 계약 필드는 `decision_signal.mode="demand_pressure"`, `stockout_risk_grade=null`로 두고, 별도 출력 필드 **`demand_pressure_grade`**에만 아래 등급을 기록한다. 검증된 재고 확률을 제공할 때는 `decision_signal.mode="stockout_risk"`이며 `prediction_basis`로 contextual과 재고·시간 폴백을 구분한다.

```text
demand_pressure_grade = low | medium | high
```

응답에는 `grade_direction="higher_means_higher_demand_pressure"`와 수요 압력 경계의 `threshold_version`을 함께 넣는다.

```text
입력: station × day_of_week × hour의 과거 15분 환산 대여 건수
낮음: 해당 station·요일의 50 percentile 미만
보통: 50 percentile 이상 80 percentile 미만
높음: 80 percentile 이상
```

- 버킷에 서로 다른 날짜 표본이 8개 미만이면 `decision_signal.mode="unavailable"`, `demand_pressure_grade=null`인 `데이터 부족` 상태다.
- 화면에는 데이터 기간·마지막 갱신일을 함께 표시한다.
- 과거 대여 수요 압력은 현재 `parking_count`와 결합해 확률처럼 표현하지 않는다. 현재 snapshot을 신뢰할 수 있다면 이 절의 L2 대신 `current_stock` 모드를 사용한다.
- “높음”은 대여 수요가 높다는 뜻이지 자전거가 없거나 고장이라는 뜻이 아니다.
- `demand_pressure`는 B0/B1/B2/B3/M1-CB/M1-LGBM과 별개의 fallback baseline이다. 날씨·행사·공간 feature를 섞어 “AI 예측”으로 부르거나 `stockout_risk` 성능과 한 표에서 같은 타깃처럼 비교하지 않는다.

---

## 9. 이상탐지 대신 “재고 정체신호” 평가

### 9.1 명명과 범위

station 합계 시계열로 산출하는 기능명은 **재고 정체신호**로 고정한다.

- 허용 문구: “재고 변화가 평소보다 오래 멈춰 확인이 필요합니다.”
- 금지 문구: “고장을 탐지했습니다”, “잠금 오류가 확실합니다”, “N대가 고장입니다.”
- `is_missing`, source 전환, stale snapshot은 정체신호 계산에서 제외한다.
- 자동신호는 독립 상태축 `inventory_signal=stagnant|under_review`로만 기록한다. 이를 공식 고장 상태로 승격하지 않으며, 고장 확인은 독립 현장·정비 라벨과 별도 공식 상태 계약이 필요하다.

### 9.2 Shadow 기간과 독립 라벨

1. 검증된 snapshot 수집 후 **최소 2주** shadow mode로 초기 오류를 점검하고, 이용자 노출 승격은 최소 28일과 §9.4의 독립 라벨 게이트를 모두 충족한 뒤에만 검토한다. 라벨이 부족하면 상한 없이 shadow를 연장한다.
2. 알림은 이용자에게 보내지 않고 내부 검수 큐에만 기록한다.
3. 신호가 난 정류장과 같은 시간대의 무신호 control 정류장을 함께 현장 점검한다.
4. 현장 점검자는 가능하면 신호 여부·점수를 보지 않은 상태에서 다음을 기록한다.
   - 방문·관측 시각, 정류장, API 수량, 현장 자전거 수
   - 실제 대여 시도 성공/실패 여부(안전하고 허용된 범위)
   - 잠금·파손·전원 문제의 관찰 여부
   - 사진/메모, 점검자 ID, 모델 알림과의 시간차
5. 공식 정비 기록은 가장 강한 라벨이다. 독립 이용자 신고는 보조 라벨이며 동일 signed 익명 세션과 멱등 요청의 중복을 제거한다. 이를 서로 다른 실제 이용자 수의 증거로 과장하지 않는다.
6. 모델 문구를 보고 제출한 “정확한가요?” 투표는 독립 ground truth로 쓰지 않고 약라벨로 별도 집계한다.

### 9.3 이벤트 단위 평가

- 같은 정류장의 연속 신호는 새 snapshot마다 한 건으로 세지 않고, 마지막 신호 후 30분 동안 재발이 없을 때 하나의 episode로 닫는다.
- `Precision@k`, control 대비 양성률 lift, alerts/day, station/day 중복률, 신고 대비 lead time을 보고한다.
- 라벨 없음은 negative가 아니라 `unlabeled`다. 확인되지 않은 신호를 오탐으로 자동 처리하지 않는다.
- source 장애·결측 때문에 생긴 신호 수를 별도 안전 지표로 보고한다.

### 9.4 승격·유지·중단 기준

**이용자 화면의 “정체신호·확인 필요” 배지로 승격**하려면 모두 충족해야 한다.

- shadow 28일 완료
- 독립 현장 점검된 signal episode 30건 이상과 시간·지역을 맞춘 control 30건 이상
- 확인 가능한 positive episode 10건 이상. 부족하면 기간을 연장하고 승격하지 않음
- 상위 10건/일 정책의 event precision `>= 0.70`
- signal군의 현장 양성률이 control군보다 최소 2배
- 대상 5~10개 정류장 기준 alerts/day `<= 3`
- API 결측·source 전환이 원인인 신호 0건

승격 후에도 문구는 “확인 필요”이며 고장 확정으로 바꾸지 않는다.

**즉시 중단 또는 shadow 복귀** 조건:

- 결측·stale·source 전환이 신호를 만든 사례 1건 이상
- 독립 라벨 20건 이상 누적 후 precision `< 0.40`
- alert budget을 3일 연속 초과
- 특정 정류장·시간대가 전체 신호의 50%를 넘는데 데이터 품질 또는 운영 이벤트로 설명되지 않음
- 데이터 schema drift, 좌표/ID 매핑 변경, 모델 입력 분포의 중대한 변화

28일 시점에 최소 라벨 수를 못 채우면 실패가 아니라 **증거 부족**이다. 계속 shadow로 두며 성능 수치를 발표하지 않는다.

---

## 10. 데모 고정값과 운영 튜닝값 분리

데모의 재현성을 위한 값은 학습된 최적값이 아니다. 모든 데모 결과에 `synthetic: true`, `parameter_profile: demo-v1`을 기록한다.

### 10.1 `demo-v1` 고정값

| 항목 | 값 | 목적 |
|---|---:|---|
| poll 간격 | 5분 | fixture 시간축 고정 |
| 예측 horizon | 15분 | Core 시나리오 고정 |
| 목표 snapshot 허용오차 | ±2분 30초 | 5분 poll과 정렬 |
| `stockout_risk_grade` 경계 | `low: p_stockout<0.33`, `medium: 0.33<=p_stockout<0.67`, `high: p_stockout>=0.67` | 데모 출력 방향·경계 고정 |
| 정체 최소시간 | 30분 | 6개 연속 무변화 fixture |
| 정체 판정 현재 대수 | `parking_count >= 1` | 0대 소진을 정체신호에서 제외 |
| 인접 반경 | 700m | 기존 MVP 설계와 정렬 |
| 최소 인접 정류장 | 2개 | 단일 비교 오판 방지 |
| 인접 정상변화 | 최근 30분 중 1개 이상 station에서 1회 이상 수량 변화 | 데모용 국지성 조건 |
| 자동해제 | 3회 연속 유효 poll에서 변화 관측 | 상태 변화 시연 고정 |
| 수요 압력 경계 | P50/P80 | snapshot 부재 시 강등 모드 |

데모 fixture에는 조건을 정확히 만족하는 사례와 하나씩 깨뜨리는 반례(`is_missing`, 0대, 이웃 무변화)를 함께 둔다.

### 10.2 운영에서만 튜닝할 값

| 파라미터 | 후보/범위 | 선택 데이터 |
|---|---|---|
| 정체 percentile | P95, P97.5, P99 | train/calibration snapshot |
| 최소 정체시간 | 30, 60, 120분 | calibration 라벨 |
| 인접 반경 | 500, 700, 1,000m 또는 k-NN | calibration 라벨 |
| 최소 인접 수 | 2~5 | calibration 라벨 |
| 정체 episode merge gap | 30, 60분 | calibration 라벨 |
| 예측 GO threshold `τ` | 0.05 간격 탐색 후 연속 최적화 | calibration fold만 |
| `stockout_risk_grade` 경계 | 비용·calibration을 반영한 두 cut point | calibration fold만, `low<medium<high` 위험 방향 불변 |
| alert budget | 운영 점검 가능 건수 | 운영자와 사전 합의 |
| 신고 quorum `N` | abuse test·독립 라벨 기반 | 데모값을 운영에 복사 금지 |
| M1-CB/M1-LGBM family·hyperparameter budget | 사전등록한 동등 탐색 범위와 inner selection 규칙 | train/calibration만, final holdout 비교 선택 금지 |
| contextual feature 집합·lookback | §7.3 registry 후보 | point-in-time contract test와 calibration 이전에 고정 |
| regime별 노출 허용 | 날씨·휴일·행사·공간 slice | 승인된 `evaluation_gate`와 미래 holdout |

test/holdout을 본 뒤 파라미터를 바꾸면 해당 평가는 폐기하고 새 미래 구간에서 다시 평가한다.

---

## 11. 재현성 산출물과 완료 정의

### 11.1 매 평가 실행이 남길 것

- 데이터 manifest: source, 기간, 행수, SHA-256, schema version
- API schema comparison과 CSV quality report
- 제외·격리 행수 및 사유
- feature cutoff와 split 경계
- 외부 행의 `event_time`, `available_at`, `ingested_at`, `source_version` 및 point-in-time join 감사 결과
- feature registry, 날씨 예보·행사 vintage manifest, regime coverage matrix
- 모델/기준선 버전, parameter profile, random seed와 사전등록된 ablation 결과
- 전체·정류장·시간대·날씨·휴일·행사·공간 slice별 Brier/log loss/calibration/decision metric
- 정체 episode와 독립 라벨 매칭표
- 승격·유지·중단 판정 및 근거

### 11.2 이 문서의 DoD

- [ ] 직접 타슈 API와 전국 통합 API의 실제 200 fixture·schema 보고서가 있다. 15109253은 정적 metadata adapter로만 검증됐다.
- [ ] 1분 raw 수집 가능성, 5분 canonical grid 생성과 source별 age 분포를 검증했다.
- [ ] 연속 7일 dual-source 결과로 두 재고 경로를 동일/별개 및 주/보조로 판정했다.
- [ ] CSV 원본 hash `B43E78C...D42560B`에 연결된 재현 profile, 유효/격리 행수와 station mapping이 있다.
- [ ] KMA 예보 vintage·ASOS 관측·KASI 특일의 실제 응답 fixture와 first-seen/availability 보고서가 있다.
- [ ] trip-only 산출물과 snapshot-required 산출물이 코드·UI에서 분리됐다.
- [ ] `contextual_ml` 게이트 미통과·context 장애 시 별도 승인된 `inventory_temporal`로 강등되고, 그것도 미승인·미통과면 fresh 현재 snapshot은 `current_stock`, snapshot이 없고 trip 표본 게이트만 통과하면 `demand_pressure`, 어느 근거도 없으면 `unavailable`로 강등된다.
- [ ] 모든 외부 모델 행에 네 시점·버전 필드가 있고 `effective_available_at <= cutoff` 위반 시 dataset build가 실패한다.
- [ ] 미래 실제 날씨·사후 행사 정보·사용자 위치·신고·정비 상태가 feature에 들어가지 않는 contract test가 있다.
- [ ] B0/B1/B2/B3/M1-CB/M1-LGBM, 중첩·leave-one-group-out ablation, 15분 purge, 시간·정류장·행사 holdout과 Brier/log loss/calibration/동일 coverage false-go가 자동 산출된다.
- [ ] 전체와 현재 재고 `>0` 조건부 지표 및 paired date·station-day block bootstrap 95% CI가 함께 산출된다.
- [ ] 28일·42일 결과는 예비로만 표시되고, contextual 주장은 사전등록 regime coverage와 승인된 versioned `evaluation_gate` 범위 안에서만 노출된다.
- [ ] 정체신호가 최소 28일 shadow 및 독립 라벨 게이트를 통과하기 전 공개되지 않는다.
- [ ] demo-v1 값과 운영 튜닝값이 서로 다른 parameter profile로 저장된다.
- [ ] 모든 사용자 화면에서 관측값·예측·재고 정체 신호·커뮤니티 현장 신고·공식 정비 상태가 서로 다른 라벨로 표시된다.
