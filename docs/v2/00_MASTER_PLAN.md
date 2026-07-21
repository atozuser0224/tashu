# 타슈캐스트 통합 마스터 플랜 v2.2

> 상태: **제품·데이터·모델 기획의 단일 진입점(Canonical Planning Entry)**
> 기준일: 2026-07-21
> 적용 범위: 대전 타슈의 정확히 15분 뒤 공식 재고 소진 위험 예측, 가까운 대안 정류장 제시, 제한적 현장 신고
> 기계 판독 API 계약: [`contracts/openapi.yaml`](./contracts/openapi.yaml) v2.2.0 — 재고 원천 enum은 `direct_tashu | national_integrated | demo`다.

이 문서는 제품을 왜 만드는지, 지금 실제로 가진 데이터가 무엇인지, 어떤 데이터를 더 모아야 하는지, 어떤 모델을 어떤 증거로 선택할지, 실패할 때 무엇으로 강등할지를 한 흐름으로 설명한다. 세부 구현자는 이 문서에서 시작하고, 필드 수준 계약과 검증 절차는 링크된 상세 문서를 따른다.

---

## 1. 결론부터: 지금 할 수 있는 것과 아직 할 수 없는 것

현재 다운로드해 확인한 대여이력은 약 932만 행이지만 **대여·반납 event**이지 정류장 재고 snapshot이 아니다. 따라서 이 데이터만으로 `15분 뒤 공식 재고가 0대인가`를 학습하거나 검증할 수 없다. 지금 즉시 만들 수 있는 학습 산출물은 과거 대여량을 요약한 `historical_demand` 기반 수요 압력뿐이며, 이를 현재 재고 소진 확률 또는 AI 상황 예측이라고 부르면 안 된다.

진짜 Core를 만들려면 오늘부터 다음을 함께 보존해야 한다.

1. 타슈 공식 재고 snapshot
2. 예측 당시 실제로 발행돼 있던 기상청 예보 vintage
3. 당시 공표돼 있던 휴일·행사 revision
4. 예측 시점 이하의 주변 정류장 재고와 버전이 고정된 공간 graph

첫 모델은 복잡한 딥러닝이 아니다. `현재값 유지 → 역사 버킷 → 재고·시간 logistic → 투명한 맥락 logistic → CatBoost/LightGBM`을 같은 미래 holdout에서 비교한다. 현시점의 첫 비선형 후보는 CatBoost이지만, 미래 데이터에서 단순 모델보다 확실히 낫다는 증거가 없으면 배포하지 않는다.

---

## 2. 문제와 사용자 가치

### 2.1 사용자가 겪는 문제

사용자는 약 15분 뒤 자전거가 필요할 때 현재 표시된 재고만 보고 정류장으로 이동했다가 도착 시 0대를 만날 수 있다. 같은 현재 재고라도 최근 감소 흐름, 출퇴근 시간, 당시 예보된 강수, 휴일, 행사, 주변 정류장 흐름에 따라 15분 뒤 결과는 달라질 수 있다.

### 2.2 제품이 해결할 일

> 사용자가 30초 안에 공식 현재 재고, 검증된 15분 소진 위험, 가까운 대안을 구분해 보고 허탕칠 가능성이 낮은 정류장을 선택하게 한다.

제품 가치는 긴 AI 설명이 아니라 다음 행동에서 나온다.

- 공식 현재 재고와 조회 시각 확인
- `15분 후 재고 소진 위험: 낮음/보통/높음` 확인
- 도보 가능한 대안 최대 3개 비교
- 한 번의 CTA로 길찾기 시작
- 현장에서 실패했다면 공식 상태와 분리된 커뮤니티 신호 기록

### 2.3 성공을 판단하는 두 층

모델 성공과 제품 성공을 분리한다.

| 층 | 핵심 질문 | 대표 지표 |
|---|---|---|
| 모델 | 확률이 미래 공식 snapshot과 맞고 단순 기준선보다 나은가 | Brier, log loss, calibration, 동일 coverage false-go |
| 제품 | 사용자가 더 빨리 정류장을 고르고 첫 방문 실패를 줄였는가 | 결정시간, 대안 CTA, 첫 방문 대여 결과, 신호 이해율 |

좋은 오프라인 점수만으로 사용자 가치가 증명되지 않고, 클릭 증가만으로 예측 정확도가 증명되지 않는다.

---

## 3. 예측 계약: 정확히 무엇을 맞히는가

### 3.1 고정 타깃

정류장 `s`, 예측 cutoff `t`에 대해 다음 하나만 Core 타깃으로 사용한다.

```text
y_stockout(s,t) = 1[bikes_available(s, t+15분) < 1]
p_stockout_15m  = P(y_stockout=1 | t 시점까지 실제로 이용 가능했던 정보)
```

- horizon은 정확히 15분이다.
- `bikes_available`은 타슈 공식 API의 `parking_count`를 보정 없이 정규화한 값이다.
- 타깃은 정확히 `t+15` 상태다. “향후 15분 안에 한 번이라도 0대”와 다른 문제다.
- 중간에 0대였다가 `t+15`에 다시 1대가 됐다면 이 타깃은 0이다.
- 실제 대여 성공, 정상 자전거 수, 잠금 성공, 고장 확률을 뜻하지 않는다.

### 3.2 표본 생성

기존 5분 cadence에서는 `t+15 ±2분 30초` 안의 목표 snapshot만 허용한다. 다만 원천에 관측시각이 없고 5분 poll은 라벨 오차와 중간 소진·재충전 누락을 키우므로, v2.2 수집 목표는 **가능하면 1분 poll**이다.

- API 한도와 페이지 수를 확인해 1분 poll이 가능하면 대상 정류장부터 적용한다.
- 1분 poll이면 목표 허용오차도 별도 evaluation profile로 더 좁힌다.
- source 전환, 전체 poll 실패, 정류장 비활성화가 `t`와 목표시각 사이에 있으면 제외한다.
- 5분 간격 표본의 15분 label은 중첩되므로 train/calibration/test 경계에 최소 15분 purge를 둔다.
- 전체 표본과 `bikes_available(t)>0`인 실제 고갈 위험 표본을 따로 평가한다. 이미 0대인 긴 구간이 성능을 부풀리지 않게 한다.
- 행 수 외에 독립 `zero 진입 episode`, station-day, 날짜 수를 유효 표본량으로 보고한다.

### 3.3 외부 응답 의미

승인된 `stockout_risk`만 `stockout_probability`를 반환한다. 기본 UI는 확률 숫자보다 등급을 먼저 보여주며, 이해도 검증 전에는 숫자를 전면 노출하지 않는다.

```text
stockout_risk_grade = low | medium | high
grade_direction     = higher_means_higher_stockout_risk
horizon_minutes     = 15
```

`high`는 대여 가능성이 높다는 뜻이 아니라 **공식 재고 소진 위험이 높다**는 뜻이다.

---

## 4. 현재 데이터의 진실

### 4.1 공식 대여이력 원본에서 확인한 사실

2026-07-21에 공공데이터포털의 [타슈 대여이력 15137219](https://www.data.go.kr/data/15137219/fileData.do) 원본을 내려받아 프로파일링했다. 조사에 사용한 다운로드 ZIP의 SHA-256은 `B43E78C373050D0AAE2208DB037538187066C565B7D5833F462B2EA94D42560B`다.

| 항목 | 확인 결과 | 모델링 영향 |
|---|---|---|
| 파일 규모 | 월별 CSV 20개, 압축 493,887,524 bytes, 해제 약 2.52 GB | chunk/Parquet 변환 필요 |
| 실제 행 수 | **9,320,018행** | 카탈로그 4,168,667행과 불일치하므로 카탈로그 행 수를 근거로 사용 금지 |
| 스키마 | 19열: 자전거번호, 대여·반납 시각·대여소 ID/명칭/좌표/주소, 이용시간, 거리 등 | trip 수요 분석에는 유용 |
| 월 파일 문제 | `2025-12` 파일이 `2025-01` 구간의 trip key 203,545건을 담고 있음 | 원천 문제를 확인하기 전에는 12월 데이터로 사용할 수 없으며 event time 기준으로 격리·재검증 |
| 장애 공백 | 2025-02-26 15:27 이후부터 2025-03-04 11:02까지 공백 | 해당 구간 학습·평가 제외 또는 명시적 missing regime 처리 |
| 시각 품질 | 2025-03은 초 단위가 없고 한 자리 시간 표현도 존재 | strict parser와 원본 정밀도 flag 필요 |
| 인코딩 | CP949와 UTF-8 BOM 혼재 | 파일별 strict decode 결과 보존 |
| 운영성 행 | 관제센터 관련 행 존재 | 일반 사용자 수요와 운영자 강제처리 가능성을 분리 |

이 프로파일링 결과는 중요한 조사 증거지만, 현재 저장소에는 493 MB 원본이나 재현 스크립트·해시 보고서가 없다. 다음 단계에서 원본 SHA-256, 파일별 profile, 격리 규칙과 재현 코드를 artifact로 남겨야 `확인` 상태를 지속할 수 있다.

### 4.2 이 932만 행으로 할 수 있는 일

- 정류장·요일·시간대별 대여·반납 수요 분석
- 순유입과 이동 pair 분석
- 역사적 `demand_pressure` baseline
- station ID·명칭·좌표 매핑 후보 생성
- 출퇴근·휴일·기상 조건별 수요 변화 탐색

### 4.3 이 데이터만으로 할 수 없는 일

- 과거 절대 재고 복원
- `P(parking_count(t+15)<1)` 라벨 생성
- 운영자 재배치·정비 회수·누락 event 구분
- 실제 이용 가능한 정상 자전거 수 산출
- 재고 소진 모델의 calibration 또는 false-go 검증

초기재고, 운영자 이동, API snapshot, 같은 poll 구간 안의 사건 순서를 모르기 때문이다. 임의 초기값에 누적 순유입을 더해 재고처럼 만드는 방식을 금지한다.

---

## 5. 올바른 재고 원천 선택

### 5.1 원천별 판단

| 원천 | 확인된 계약 | 판단 |
|---|---|---|
| [타슈 직접 API / 포털 15119663](https://www.data.go.kr/data/15119663/openapi.do) | `GET https://bikeapp.tashu.or.kr:50041/v1/openapi/station`, `api-token`; `id,name,name_en,name_cn,x_pos,y_pos,address,parking_count`. 키는 앱 신청 후 수동 검토, 한도 비공개 | 가장 직접적인 재고 후보. 승인 키 200 응답·한도·갱신주기 검증 필요 |
| [전국 공영자전거 실시간 통합 API 15126639](https://www.data.go.kr/data/15126639/openapi.do) | 자동승인, 개발 5,000회/일, 대전 코드 `3000000000`; `/inf_101_00010002_v2`의 `rntstnId,rntstnNm,lat,lot,bcyclTpkctNocs` | 빠르게 시험할 후보. `bcyclTpkctNocs`가 실제 대여 가능 수인지 실응답·직접 API 대조 필요 |
| [대전광역시 타슈정보 15109253](https://www.data.go.kr/data/15109253/openapi.do) | 실제 Swagger item은 `kioskNo,year,signgu,lcNm,lcDc,adres,dfrCo,...`; `dfrCo`는 거치대 수 | **실시간 재고에서 제외**. 정적 정류장·거치대 metadata 후보 |
| 전국 통합 일별 대여·반납 | 일 단위 `crtrYmd,rntNocs,rtnNocs` | 15분 라벨·단기 feature로는 해상도 부족 |

카탈로그 설명보다 실제 Swagger와 승인된 200 응답을 우선한다. 특히 15109253의 카탈로그 문구에 “이용 가능한 자전거 수량”이 있더라도 실제 계약에 현재 재고 필드가 없으므로 재고 source로 사용하지 않는다.

### 5.2 즉시 실행할 source 검증

1. 전국 통합 API 키를 자동 발급한다.
2. 타슈 직접 API 키를 병행 신청한다.
3. 최소 7일간 같은 시각에 두 경로를 동시 poll한다.
4. 정류장 ID 대응률, 재고 exact match, 절대차, 결측률, 갱신 지연, pagination을 비교한다.
5. 주 원천과 보조 장애 감지 원천을 정한다.

두 경로가 같은 타슈 상위 시스템을 재배포할 수 있으므로 독립 센서 두 개로 간주하지 않는다. 둘 다 응답에 원천 관측시각이 없을 가능성이 있으므로 요청 시작시각, HTTP Date, 본문 수신시각, raw hash를 보존하고 `collected_at` 대용의 한계를 노출한다.

### 5.3 v2.2 재고 source 계약

v2.2는 원천을 모호한 운영 경로명이 아니라 실제 공급 계약으로 식별하는 breaking change다. canonical enum은 정확히 `direct_tashu|national_integrated|demo`다.

| 실제 원천 | v2.2 `data_source` | 규칙 |
|---|---|---|
| 타슈 직접 API 15119663 | `direct_tashu` | 승인 200·스키마 게이트 통과 후만 live |
| 전국 통합 API 15126639 | `national_integrated` | 재고 의미를 직접 API와 대조한 뒤만 live |
| 15109253 | 사용 금지 | inventory `data_source`가 아니라 정적 metadata source |
| fixture | `demo` | 전 화면 demo 표시 |

`fixture`는 구현 내부의 수집 source 이름일 수 있지만 외부 계약 enum은 `demo`다. `data_source`는 재고 원천이고 `response_mode=live|demo`는 전체 실행 모드다. 합성 날씨·행사·graph가 하나라도 들어가면 재고 source는 유지하되 `uses_synthetic_context=true`, `response_mode=demo`로 강등한다.

---

## 6. 날씨·달력·행사 맥락

### 6.1 날씨는 실측 미래값이 아니라 당시 예보를 쓴다

[기상청 동네예보 API](https://apihub.kma.go.kr/apiList.do?seqApi=10&seqApiSub=286)는 `tmfc` 발표시각과 `tmef` 유효시각으로 과거 예보 vintage를 조회할 수 있다.

- 5 km × 5 km 격자
- 단기예보 archive: 2008-10-30 17:00 KST 이후
- 발표: 02·05·08·11·14·17·20·23시
- 유효값: 1시간 간격
- 주요 변수: `TMP, UUU, VVV, VEC, WSD, SKY, PTY, POP, PCP, SNO, REH`

15분 타깃이라고 날씨를 가짜 15분 해상도로 만들지 않는다. `issued_at <= prediction_at`인 최신 예보 중 `t+15`가 속한 유효시간 값을 사용한다.

초기 feature는 다음으로 제한한다.

- `PTY` 강수 형태
- `PCP` 또는 초단기 `RN1` 강수량
- `TMP/T1H` 기온
- `REH` 습도
- `WSD` 풍속
- forecast lead time
- `t`까지 이용 가능했던 최근 실황 대비 예보 변화량

초단기 `POP`는 2026-06-23 12 KST 이후 추가돼 전체 과거 구간에 구조적 결측이 생기므로 초기 Core에서 제외하거나 availability flag를 둔 별도 ablation으로만 검증한다.

### 6.2 관측 날씨의 역할

ASOS 대전 지점은 `133`이다. 관측값은 다음처럼 구분한다.

- `t`까지 공개된 실황: feature 후보
- `t+15` 실제 관측: 사후 slice 분석·평가 후보
- `t+15` 실측을 당시 예보 대신 학습 입력으로 사용: 누수이므로 금지

### 6.3 휴일

한국천문연구원 특일 정보 API는 자동승인 후보지만 공식 응답에 `issued_at`이나 revision이 없다. 각 수집 때 다음을 자체 보존한다.

```text
holiday_date, date_name, is_holiday,
first_seen_at, retrieved_at, raw_response_hash
```

초기 feature는 `is_weekend`, `is_holiday`, `day_before_holiday`, `day_after_holiday` 정도로 제한한다. 뒤늦게 지정된 임시·대체공휴일을 현재 테이블에서 과거 전체로 소급하지 않는다.

### 6.4 행사와 공간

행사 일정의 생성·수정·취소를 과거 시점 기준으로 재현할 공식 단일 원천은 아직 미확정이다. 원천, 이용조건, 장소 좌표, 공개시각, revision archive가 확보되기 전에는 live contextual feature에서 제외한다. 합성 행사 fixture는 demo에서만 쓴다.

공간 feature는 versioned station graph와 정류장 자체 좌표·비식별 POI만 사용한다. 사용자 위치는 도보시간과 대안 정렬에만 사용하며 모델 feature가 아니다. 단순 거리 graph가 실제 자전거 이동 관계라는 가정은 검증하지 않은 채 확정하지 않는다.

### 6.5 공통 point-in-time 계약

모든 외부 행은 다음 네 필드를 가져야 한다.

```text
event_time, available_at, ingested_at, source_version
effective_available_at = max(available_at, ingested_at)
허용 조건 = effective_available_at <= prediction_at
```

날씨·행사의 나중 최종본, 미래 실제 날씨, 미래 이웃 재고, 현재 POI 테이블을 과거 표본에 덮어쓰지 않는다. 하나라도 cutoff를 넘으면 dataset build를 실패시킨다.

---

## 7. 필수 수집·저장 구조

최소 네 테이블을 append-only로 보존한다.

```text
inventory_snapshot(
  station_id, parking_count, source,
  request_started_at, collected_at, source_http_date, raw_hash
)

weather_forecast_vintage(
  grid_x, grid_y, category, value,
  issued_at, valid_at, retrieved_at, raw_hash
)

weather_observation(
  grid_or_station_id, observed_at, available_at,
  values, qc_flags
)

holiday_snapshot(
  holiday_date, name, is_holiday,
  first_seen_at, retrieved_at, raw_hash
)
```

행사와 공간 원천이 승인되면 `event_snapshot`, `station_graph_version`을 추가한다. 원문 payload, 정규화 행, ingestion run을 분리하고 실패 poll에 이전 재고를 새 snapshot처럼 forward-fill하지 않는다.

원천 약관이 허용하는 범위에서 inventory/context snapshot과 prediction provenance는 계절 재현을 위해 최소 400일 보존한다. 약관이 더 짧으면 그 원천을 장기 모델 feature에서 제외하거나 별도 법적 승인을 받는다.

---

## 8. Feature 계약

### 8.1 허용 feature

| 그룹 | 초기 feature |
|---|---|
| 재고 | 현재값, 5·10·15·30·60분 lag, 변화량·기울기, rolling 변동성, 연속 0대 시간, 결측 flag |
| 시간 | KST sin/cos, 요일, 출퇴근대, 주말 |
| 날씨 | 당시 예보의 강수 형태·양, 기온, 습도, 풍속, lead time, availability flag |
| 달력 | 휴일, 휴일 전후 |
| 행사 | 당시 공개된 일정·거리·규모 구간·취소 상태 — revision archive 통과 후 |
| 주변 | `t` 이하 이웃 재고 lag·변화·결측률 |
| 정적 공간 | 정류장 좌표, 환승·대학·상업·공원 거리, versioned POI/cluster |

### 8.2 금지 feature

- 미래 실제 날씨, 목표 snapshot, 목표 구간 trip event, 이웃 미래값
- 사후 행사 취소·장소 변경·실제 관객 수
- 사용자 현재·과거 위치, 검색어, 이동경로, 세션 행동
- 커뮤니티 신고, 공식 정비 상태, 자유문과 임베딩
- LLM이 추정한 값
- 현재 테이블로 과거를 덮어쓴 수정 정보

결측은 0이나 “비 없음/행사 없음”으로 바꾸지 않는다. 그룹별 missing flag와 freshness를 보존하고, 결측 패턴이 검증되지 않으면 별도 폴백 모델로 라우팅한다.

---

## 9. 모델 선택 전략

### 9.1 모델 ladder

| 단계 | 모델 | 목적 | 배포 판단 |
|---|---|---|---|
| B0 | current persistence + count-only empirical transition | 현재 재고만으로 얻는 두 최저 기준 | 둘 중 강한 기준을 항상 함께 평가 |
| B1 | 계층적 historical bucket + Laplace smoothing | station·요일·시간·현재 수량의 단순 경험 확률 | 필수 기준선 |
| B2 | regularized logistic | 재고 lag/rolling + 시간 | 첫 학습 모델, `inventory_temporal` 후보 |
| B3 | contextual logistic | B2 + 날씨·휴일·행사·주변·공간 | 맥락의 투명한 증분 측정, 통과 시 가장 단순한 `contextual_ml` |
| M1-a | CatBoost | 범주형 station, 결측, 비선형 상호작용 | 첫 비선형 후보 |
| M1-b | LightGBM | 큰 숫자형 tabular에서 효율적인 challenger | CatBoost와 동일 데이터·예산으로 비교 |
| M2 | RNN/TFT/GNN 등 | 장기 다중 horizon·검증된 graph 연구 | M1 잔여 오차와 충분한 장기 데이터가 있을 때만 |

### 9.2 CatBoost를 첫 후보로 두는 이유

- station ID처럼 고카디널리티 범주형 변수가 있다.
- 날씨·행사·공간과 재고 흐름의 비선형 상호작용 가능성이 있다.
- 맥락별 결측이 많을 가능성이 높다.
- 중간 규모 tabular 데이터에 적합하고 별도 딥러닝 인프라가 필요 없다.

그러나 CatBoost의 ordered boosting이 시간 누수를 자동으로 막아 주지는 않는다. 모든 category 처리·target statistic은 outer train 안에서만 적합하고, 확률은 미래 calibration 구간에서 sigmoid/Platt 또는 충분한 표본이 있을 때 isotonic으로 별도 보정한다.

신규 정류장 성능을 보기 위해 station ID를 넣은 모델과 뺀 모델을 함께 평가한다. CatBoost가 B3를 이기지 못하면 복잡성 때문에 선택하지 않는다. LightGBM은 같은 feature, 같은 탐색 예산, 같은 split에서 비교한다.

### 9.3 지금 선택하지 않는 모델

- Poisson 하나로 재고 count를 예측: 용량 상한, zero inflation, 재배치 때문에 Core 타깃을 직접 대체하기 어렵다. Poisson·negative-binomial·hurdle은 trip 수요량 보조 분석으로만 검토한다.
- survival/hazard: “언제 처음 0대가 되는가”는 정확히 `t+15` 상태와 다른 타깃
- RNN/DeepAR/TFT: 단일 15분 endpoint와 현재 데이터 규모에는 과설계
- GNN: 거리 graph가 실제 이동 graph라는 증거가 없고 운영비가 큼

이들은 tabular M1이 미래 holdout에서 승인된 뒤 남은 오류 구조가 명확할 때 challenger로 검토한다.

---

## 10. 평가 설계와 승격 게이트

### 10.1 분할

```text
과거 train → 연속 미래 calibration → 더 미래 test → 최종 미개봉 holdout
```

- expanding walk-forward outer split
- 각 경계 최소 15분 purge
- leave-stations-out 평가
- 같은 행사 instance 전체를 묶은 event holdout
- 시간 이후의 scaler, imputation, category dictionary, graph, 임계값 사용 금지
- 개별 행 bootstrap 대신 station-day/date 또는 event block bootstrap

### 10.2 비교와 ablation

모든 fold에서 B0/B1/B2/B3/M1을 같은 표본과 cutoff로 비교한다.

```text
M1-I      = 재고 + 시간
M1-IW     = M1-I + 날씨
M1-IWH    = M1-IW + 휴일
M1-IWHE   = M1-IWH + 행사
M1-FULL   = M1-IWHE + 주변 + 공간
```

날씨·휴일·행사·주변/공간·station ID를 하나씩 제거한 leave-one-group-out도 보고한다. full 결과를 본 뒤 나쁜 feature만 제거하고 같은 holdout을 최종 성능으로 재사용하지 않는다.

### 10.3 지표

- 주 지표: Brier score
- 확률 패널티: log loss
- 보정: reliability curve, ECE, calibration intercept/slope
- 불균형 참고: PR-AUC, 양성률과 함께 AUROC
- 행동: GO precision, coverage, false-go
- slice: 강수/건조, 평일/휴일, 행사/무행사, 재고 0·1·2·3+, 중심/외곽, seen/unseen station

SMOTE는 시계열·정류장 상관과 확률 보정을 훼손할 수 있어 기본 경로에서 사용하지 않는다. class weight나 다른 resampling을 challenger로 쓰면 untouched chronological calibration set에서 다시 보정한다.

### 10.4 현재 승인 규칙

contextual 후보를 승격하려면 최소한 다음을 모두 만족해야 한다.

1. 모든 시간 test fold에서 더 강한 B0보다 Brier가 개선된다.
2. B1보다 비열화하지 않는다.
3. B3 또는 사전 선택된 M1의 B2 대비 uplift에 대한 pooled block-bootstrap 95% CI 하한이 0보다 크다.
4. ECE가 현재 계약의 초기 상한 `0.10` 이하다.
5. B2와 같은 GO coverage에서 false-go가 악화하지 않는다.
6. M1은 B3보다 추가 가치가 있어야 한다.
7. 날씨·휴일·행사·신규 정류장 slice에 치명적 회귀가 없다.

구체적인 최소 uplift, 최소 coverage, false-go 비용비, slice별 최소 사건 수는 결과를 보기 전에 versioned `evaluation_gate`에 서명한다. 더 엄격한 ECE나 uplift 목표를 도입하려면 사전등록하고 기존 test를 재사용하지 않는다.

### 10.5 기간은 증거의 대용품이 아니다

| 단계 | 기간 권고 | 의미 |
|---|---:|---|
| 수집 안정성 | 최소 2주 | schema·poll·시각·결측 파이프라인 점검 |
| 파이프라인 평가 | 연속 28일 | label/as-of join/누수 test 1회, AI 성능 주장 금지 |
| 예비 모델 비교 | 최소 42일 | B0~M1 예비 비교와 빈 slice 발견 |
| 제한 파일럿 | 연속 **12주 권고** | 실제 포함된 regime와 대상 정류장 범위에서만 검토 |
| 계절 일반화 | 최소 **12개월 권고** | 사계절·주요 기상 regime가 실제 포함됐을 때 검토 |

12주와 12개월은 **권고 기간이며 자동 게이트가 아니다**. 비·눈·폭염·한파·휴일·행사·unseen station 등 사전등록 regime가 비어 있으면 기간이 지났어도 승인하지 않는다. 반대로 짧은 기간 예외는 누락 regime와 적용 범위를 명시한 별도 위험 승인이 필요하다.

---

## 11. 결정적 폴백

모든 요청은 다음 순서로 처리한다.

```text
contextual_ml
  → inventory_temporal
  → current_stock
  → historical_demand
  → unavailable
```

1. fresh 재고, complete context, 승인된 B3/M1과 calibration이 있으면 `stockout_risk/contextual_ml`.
2. 맥락이 누락·지연됐지만 fresh 재고와 별도 승인된 B2가 있으면 `stockout_risk/inventory_temporal`.
3. 예측 모델이 미승인·오류지만 fresh 재고가 있으면 `current_stock`.
4. fresh 재고는 없고 검증된 trip-history 버킷만 있으면 `demand_pressure/historical_demand`.
5. 어느 근거도 없으면 `unavailable`.

결측 날씨를 0으로 채워 contextual 모델을 억지 실행하지 않는다. stale 재고를 AI가 보정해 fresh처럼 만들지 않는다. `demand_pressure`는 15분 stockout 확률이 아니다.

---

## 12. UX 계약

### 12.1 한 화면에서 분리할 정보

1. 공식 재고: 원천, 대수, 기준시각, freshness
2. 예측: mode, basis, 15분 horizon, 위험 등급
3. 맥락 근거: 실제 사용한 구조화 evidence 최대 2개와 발행·유효시각
4. 재고 정체신호: 고장 확정이 아닌 별도 확인 필요 상태
5. 커뮤니티 신고와 공식 정비 상태: 서로 독립

### 12.2 핵심 화면

- 주변 정류장 목록: 공식 재고와 허용된 신호 한 줄
- 정류장 상세: 위험·근거·대안 최대 3개
- 길찾기 CTA: fresh 대안만 허용
- 현장 신고: 미리 선택된 정류장의 최소 입력, 공식 신고 연결

### 12.3 문구 원칙

- 허용: `15분 후 공식 재고 소진 위험: 높음`
- 허용: `당시 발표된 강수 예보와 퇴근 시간대를 반영한 전망`
- 금지: `비 때문에 자전거가 없어집니다`
- 금지: `실제 이용 가능한 자전거는 N대입니다`
- 금지: `AI가 고장 자전거를 탐지했습니다`

LLM은 이미 결정된 구조화 사실을 짧게 표현할 수 있을 뿐 확률, 등급, 대안, 원인, 행동을 정하지 않는다. LLM 장애 시 동일 mode·grade·action을 template로 반환한다.

`response_mode=demo`면 모든 화면에 워터마크를 고정하고 실제 이동 CTA, 현장 신고 전송, 제품 KPI에서 제외한다.

---

## 13. 아키텍처 흐름

```text
inventory/context sources
  → source adapters + ingestion runs
  → immutable raw payload
  → normalized inventory/context snapshots
  → point-in-time feature builder
  → B2/B3/M1 predictor + probability calibration
  → deterministic policy/router + fallback
  → FastAPI/OpenAPI
  → PWA list/detail/alternative/report
```

커뮤니티 신고·공식 정비·사용자 origin은 predictor 옆의 독립 경로다. feature builder와 prediction log로 들어가지 않는다.

초기 구현은 FastAPI 한 프로세스와 PostgreSQL 하나로 충분하다. Kafka, Kubernetes, 범용 feature store보다 append-only snapshot, as-of join 재현성, model/calibration/threshold version을 우선한다.

각 prediction에는 최소 다음 lineage를 남긴다.

```text
prediction_id, station_id, prediction_at, target_at,
inventory_snapshot_id, context_snapshot_ids,
feature_contract_version, model_version,
calibration_version, threshold_version,
prediction_basis, context_status,
raw_score, calibrated_probability, final_mode, final_grade
```

---

## 14. 실행 단계와 게이트

### Phase 0 — 사실·계약 정리

- 15109253을 live inventory 후보에서 제거
- 전국 통합과 직접 API 키 신청
- 현재 enum의 정확한 source mapping을 fixture로 고정
- 대여이력 원본 해시·파일별 품질 report·재현 script 생성
- 기상청 예보 vintage, 휴일 snapshot의 최소 fixture 생성

**종료:** 승인된 200 fixture, schema diff, 원천별 이용조건·보존조건이 있다.

### Phase 1 — 수집기와 데이터 기반

- 두 재고 후보를 7일 동시 poll
- 가능하면 1분 cadence, 불가능하면 제한 정류장/5분 profile을 명시
- 날씨 vintage와 휴일 snapshot을 같은 시각축으로 append
- 실패·중복·시간 역행·source 전환 contract test
- 28일 pipeline 구간 확보

**종료:** target 생성과 point-in-time join을 재현할 수 있다. 아직 live AI 성능을 주장하지 않는다.

### Phase 2 — 기준선과 모델 선택

- B0/B1/B2/B3 학습·보정
- CatBoost를 첫 M1, LightGBM을 동일 예산 challenger로 평가
- 15분 purge, 시간·station·event holdout, block bootstrap
- feature group ablation과 장애 simulation
- 42일 결과는 예비로 표시

**종료:** versioned evaluation report가 있고 가장 단순한 통과 모델을 선택한다.

### Phase 3 — shadow와 제한 canary

- 최소 4주 shadow에서 온라인/오프라인 feature 일치, fallback률, drift 확인
- 제품·데이터 책임자 교차 승인
- 통과 후 10~20개 정류장 canary
- feed 장애·false-go·distribution shift 시 즉시 강등

**종료:** 모델 게이트와 사용자 안전 게이트를 모두 통과한다.

### Phase 4 — 범위 확장

- 12주 권고 pilot에서 실제 regime coverage 확인
- 계절 주장은 최소 12개월 권고 데이터와 별도 holdout으로 검토
- 신규 정류장·지역 확장은 leave-station-out 근거가 있는 범위만 허용

기간 경과만으로 단계가 자동 승격되지 않는다.

---

## 15. MVP 제외 범위

- 실제 이용 가능한 정상 자전거 대수 보정
- 고장 자전거 자동 판정 또는 원인 추론
- 대여 성공·잠금 성공 보장
- 실제 revision archive가 없는 행사 맥락의 live 사용
- 미래 실제 날씨를 당시 예보처럼 사용
- 사용자 위치·검색·신고를 모델 feature나 정답으로 사용
- raw SHAP/feature weight를 인과 설명으로 노출
- LLM의 확률·등급·대안·행동 결정
- 승인 근거 없는 RNN/TFT/GNN 도입
- 12주·12개월 경과만으로 자동 승인
- 검증 전 전 정류장·전 계절 일반화 주장

---

## 16. 주요 리스크와 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| API count 의미 오류 | 잘못된 라벨 | 직접 API와 전국 통합 7일 대조, 15109253 배제 |
| 원천 관측시각 부재 | label 시각 오차 | 요청·HTTP Date·수신시각 보존, 1분 poll 우선, basis 노출 |
| 재고 archive 부재 | Core 학습 불가 | 즉시 snapshot 수집, 그 전에는 current stock/demand pressure만 제공 |
| 대여 CSV 중복·공백·인코딩 | 수요 편향 | 파일별 strict profile과 격리, 원본 hash 보존 |
| 미래 예보·행사 누수 | 과장된 오프라인 성능 | `available_at/ingested_at` as-of join을 build blocker로 적용 |
| 양성 희소·중복 label | 과신과 좁은 CI | zero episode/station-day 보고, block bootstrap, current>0 slice |
| 신규 정류장 | station ID 암기 | ID-free 모델과 leave-station-out 평가 |
| 운영자 재배치 | 비수요 변화 | 모델 한계로 기록, 급격한 regime slice와 이상치 분석 |
| 외부 feed 결측 | 잘못된 0 대체 | missing flag와 별도 `inventory_temporal` 폴백 |
| 행사 원천 미확정 | 재현 불가 | live 제외, demo synthetic 표시 |
| 보존 약관 | 계절 재현 불가 | source 승인 게이트에 재배포·보존 조건 포함 |
| 사용자의 인과 오해 | 잘못된 행동·신뢰 | 근거를 관찰 사실로 표시, 인과 문구 금지, 기본 UI는 등급 우선 |

---

## 17. 고정 결정과 열린 결정

### 고정

- 타깃은 정확히 `P(parking_count(t+15)<1)`다.
- 대여이력만으로 stockout 모델을 만들지 않는다.
- 15109253은 live inventory source가 아니다.
- 날씨는 당시 예보 vintage를 쓴다.
- 모델 선택은 B0/B1/B2/B3/M1 미래 holdout 비교로 한다.
- 현재 첫 비선형 후보는 CatBoost, LightGBM은 동등 예산 challenger다.
- contextual 맥락이 가치를 못 더하면 B2 또는 더 낮은 폴백을 쓴다.
- LLM과 개인 입력은 예측 결정에서 격리한다.
- 12주·12개월은 권고이지 자동 승인 조건이 아니다.

### 구현 전에 닫아야 할 결정

- 전국 통합 `bcyclTpkctNocs`의 실제 의미와 pagination
- 직접 API 승인 한도와 실제 갱신주기
- 1분 poll 대상 범위와 저장 비용
- 행사 공식 원천과 revision archive 가능성
- station graph/POI 원천과 이용조건
- slice별 최소 표본·최소 양성 episode
- 최소 GO coverage와 false-go 비용비
- CatBoost/LightGBM 탐색 예산, seed, calibration 선택 규칙
- breaking source enum에 맞춘 adapter·fixture·클라이언트의 동시 migration과 호환 종료 시점

---

## 18. 이 문서에서 상세 문서로 이동하기

1. 사용자 흐름·화면·KPI: [`01_PRODUCT_MVP.md`](./01_PRODUCT_MVP.md)
2. 사실 대장·데이터 품질·타깃·평가: [`02_DATA_AND_EVALUATION.md`](./02_DATA_AND_EVALUATION.md)
3. 저장 구조·상태 축·보안·운영: [`03_ARCHITECTURE_SECURITY.md`](./03_ARCHITECTURE_SECURITY.md)
4. 구현 순서·shadow·canary: [`04_EXECUTION_ROADMAP.md`](./04_EXECUTION_ROADMAP.md)
5. 사람×AI 작업·검토 책임: [`05_OPERATING_MODEL.md`](./05_OPERATING_MODEL.md)
6. HTTP 필드 계약: [`contracts/openapi.yaml`](./contracts/openapi.yaml)
7. 코드값·UI 라벨: [`contracts/enums.json`](./contracts/enums.json)
8. 불변 규칙: [`contracts/invariants.md`](./contracts/invariants.md)

문서가 실제 원본·fixture·테스트와 충돌하면 조용히 문구만 바꾸지 않는다. 원본과 조사 로그를 보존하고, 기계 계약·fixture·상세 문서·이 마스터 플랜을 하나의 검토 가능한 변경으로 갱신한다.
