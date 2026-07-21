# 실행 로드맵 v2.2

이 로드맵은 “많이 구현하기”가 아니라 **예측 시점에 알 수 있었던 재고·날씨·시간·휴일·행사·공간 맥락으로 검증 가능한 수직 슬라이스를 완성하고, 강한 기준선보다 좋아질 때만 AI 예측을 승격하는 것**을 목표로 한다.

## 1. 해커톤 수직 슬라이스

### 단계 A — 데이터 게이트

산출물:

- `fixtures/api/national_integrated/200_01.redacted.json`: 전국 공공자전거 실시간 통합 API의 대전 응답
- `fixtures/api/direct_tashu/200_01.redacted.json`: 타슈 직접 OpenAPI 응답
- `fixtures/api/static_metadata_15109253/200_01.redacted.json`: 재고가 아닌 정류장·거치대 메타데이터 응답
- `profiles/inventory_source_dual_run.md`: 두 재고 후보를 같은 시각에 수집한 7일 비교 결과
- `fixtures/demo/stations.json`
- `fixtures/context/weather_forecast/*.redacted.json`: `issued_at`, `valid_at`, 제공자 버전이 남은 예보 vintage
- `fixtures/context/calendar/*.json`: 공휴일·학사일정 등 사전에 확정된 일정의 버전
- `fixtures/context/events/*.redacted.json`: 당시 공개된 행사 시작·종료·장소·수정·취소 snapshot
- `fixtures/context/station_graph.json`: 정류장 인접 관계와 정적 공간 특징 버전
- 응답 필드·타입·nullable·페이지네이션·좌표 의미 비교표
- CSV 전체 프로파일: 파일별 인코딩, 실제 날짜 범위, 중복·결측·이상 파일, station ID·이름·좌표 버전
- context source별 `event_time`, `available_at`, `ingested_at`, `source_version`, 갱신주기·실패 정책 표

완료 조건:

- 두 재고 후보 각각에 대해 API 키와 개인정보를 제거한 성공 응답이 저장돼 있다.
- 한 번의 호출이 전체 정류장을 주는지, 페이지 크기·누락·중복이 어떤지 확인했다.
- 전국 통합 API의 `bcyclTpkctNocs`와 직접 API의 `parking_count`를 같은 정류장·시각에 비교해 둘 다 현재 재고를 뜻하는지 확인했다.
- 7일 이중 수집으로 station ID 매핑률, 수량 일치율, 실질 갱신주기, 결측률을 산출하고 주 원천·폴백 원천을 명시적으로 승인했다. 두 API가 독립 센서를 쓴다고 가정하지 않는다.
- 두 후보 모두 원천 관측시각을 주지 않는 경우 요청 시작시각·수집 완료시각·HTTP `Date`·응답 해시를 보존하고, 사용자에게 수집시각 기준임을 표시한다.
- 실패 응답과 stale 판정 기준을 fixture로 보유한다.
- 날씨·행사 fixture가 사후 최종값이 아니라 해당 예측 시점에 실제로 알 수 있었던 snapshot임을 재현한다.
- context 결측과 실제 `강수 없음`·`행사 없음`이 schema와 fixture에서 구분된다.
- 정류장 좌표를 기상 격자·행사·인접 graph에 연결한 방법과 버전을 고정한다.

현재 확인된 과거 이력의 출발점:

- 공식 대여 이력 ZIP은 20개 월별 CSV, 실제 9,320,018행이며 대여시각 범위는 2024-08-01 05:00:05~2026-03-31 23:59:55다. 포털 행 수 메타데이터 대신 파일을 직접 프로파일한다.
- 파일 인코딩은 CP949와 UTF-8 BOM이 섞여 있다. 2025-12 파일은 실제로 2025-01 키를 담으므로 제외하고, 2025-02-26 15:27~2025-03-04 11:02 시스템 공백과 2025-03 시각 형식 변형을 품질 플래그로 보존한다.
- 관제센터를 거친 약 5.28%의 행, 동일 대여·반납 정류장, 0 이하 이동거리는 별도 slice로 격리한다. 정류장 이름·좌표 문자열 변화는 곧바로 이전으로 단정하지 않고 버전 매핑 대상으로 둔다.
- 이 이력만으로는 초기 재고·재배치·정비를 알 수 없어 15분 후 재고 소진 라벨을 만들 수 없다. 재고 snapshot 수집 전에는 수요 기준선만 학습한다.

차단 조건:

- 성공 응답을 얻지 못하면 live 경로 개발을 중단하고 `demo` adapter만 사용한다.
- station 스냅샷 이력이 없으면 발표에서 “검증된 재고 예측” 표현을 금지한다.
- 당시 예보·행사 snapshot을 보존하지 못하면 live `prediction_basis=contextual_ml`을 금지한다. 검증된 `inventory_temporal` 또는 `current_stock`으로 강등한다. 합성 context를 시연할 때는 공식 재고의 `data_source`를 그대로 보존하고 전체 provenance에 `uses_synthetic_context=true`, 응답 전체에 `response_mode=demo`를 적용한다.

### 단계 B — 계약과 골격

산출물:

- `contracts/openapi.yaml` 검증 통과
- OpenAPI에서 생성하거나 수동으로 맞춘 mock
- FastAPI와 프론트의 최소 골격
- `live`와 `demo`가 같은 내부 `StationObservationBatch`/`StationObservation` 계약을 구현
- weather/calendar/event/graph adapter가 같은 `ContextSnapshot` 메타데이터 계약을 구현
- point-in-time `FeatureVector`, `PredictionRecord`, model/calibration registry 계약
- 서버 서명 익명 세션과 `Idempotency-Key` 처리

완료 조건:

- 프론트가 백엔드 없이 mock으로 세 화면을 탐색할 수 있다.
- 백엔드 계약 테스트가 성공한다.
- 잘못된 enum, 누락 필드, 중복 신고가 예상한 오류 코드로 거절된다.
- 미래에 발행된 예보·사후 수정된 행사·`t` 이후 인접 재고가 feature join에서 거절된다.
- mock이 `context_status=complete|partial|unavailable`과 각 prediction basis의 허용 조합을 모두 재생한다.

### 단계 C — Core

구현 순서:

1. 정류장 목록과 데이터 최신성
2. 날씨·달력·행사·정류장 graph adapter와 versioned context snapshot
3. `available_at <= prediction_time`을 강제하는 point-in-time feature builder
4. B0/B1/B2 재고 기준선, B3 투명한 맥락 기준선, CatBoost contextual 후보와 동등 예산 LightGBM challenger 및 시간순 확률 보정
5. ETA 15분 조회와 `prediction_basis`, `context_status`, feature/calibration 버전 산출
6. 데이터 수준에 따른 `decision_signal.mode=stockout_risk|current_stock|demand_pressure|unavailable` 정책
7. 구조화된 context evidence를 사용하는 애플리케이션 템플릿 설명
8. contextual 소진 위험 우선, 도보시간 차순의 대안 정류장

고정 데모 규칙:

- `fresh`: 관측 후 10분 이내
- `stale`: 10분 초과 30분 이내
- `unavailable`: 마지막 성공 관측이 없거나 30분 초과. 최신 수집 실패는 `last_error_code`에 기록하되 마지막 성공 관측이 임계값 안이면 즉시 `unavailable`로 덮어쓰지 않음
- 대안은 현재 데이터가 `fresh`이고 현재 수량이 1대 이상인 후보만 사용
- `context_status=complete`이고 contextual 모델 게이트를 통과한 경우에만 `prediction_basis=contextual_ml`을 사용한다.
- context가 일부 또는 전부 없으면 결측을 0으로 대체하지 않는다. 해당 결측 패턴에서 별도로 검증된 `inventory_temporal` 모델이 있을 때만 그 basis로 강등하고, 없으면 fresh 현재 snapshot은 `current_stock`으로 표시한다.
- 현재 snapshot이 없고 검증된 trip 표본 게이트를 통과한 경우에만 `demand_pressure_grade`를 표시한다.
- 합성 날씨·행사·graph가 하나라도 섞인 예측은 공식 재고의 `data_source`와 무관하게 `uses_synthetic_context=true`, 전체 `response_mode=demo`이며 live 이동 추천과 KPI에서 제외한다.

위 수치는 데모 기본값이며 운영 최적값이 아니다. 설정 파일에서 관리하고 평가 후 변경한다.

완료 조건:

- 지도 없이도 동일 기능을 제공하는 정렬 가능한 목록이 있다.
- 기준 시각, 데이터 출처, live/demo, 산출 종류가 화면에 표시된다.
- 맥락형 예측은 `prediction_basis`, `context_status`, feature/model/calibration 버전과 최대 2개의 비인과적 context evidence를 반환한다.
- 대안 없음·결측·콜드스타트 상태가 정상 렌더링된다.
- LLM 없이 전체 Core가 동작한다.
- 동일 현재 재고를 가진 정류장도 맥락이 다르면 위험과 순위가 달라질 수 있고, 그 결과가 고정 fixture로 재현된다.

### 단계 D — 현장 신고

구현 순서:

1. 정류장 자동 선택 또는 수동 선택
2. 구조화 유형 1개 선택
3. 선택적 200자 설명
4. 제출·취소·내 신고 조회
5. 최근 커뮤니티 신고를 공식 상태와 분리해 표시

완료 조건:

- 재시도해도 `Idempotency-Key` 기준 신고가 한 건만 생긴다.
- 신고자는 capability token으로 자기 신고만 상세 조회·취소할 수 있다.
- 안전결함은 “탑승하지 말고 타슈 공식 채널에 신고” 안내를 즉시 표시한다.
- 다른 클라이언트는 최대 30초 폴링 내 커뮤니티 신고 집계 변화를 확인한다.

### 단계 E — 데모·검수

90초 데모:

1. **0~15초:** 공식 재고가 같은 A/B 정류장과 각각의 기준 시각 확인
2. **15~40초:** B2 재고·시간 기준선과 contextual ML의 선택 차이 확인
3. **40~65초:** 강수 예보·퇴근 시간·행사 종료·인접 재고 감소 중 실제 반영된 상위 2개 신호와 출처·시각 확인
4. **65~80초:** held-out replay의 실제 `t+15` 공식 snapshot과 전체 평가표 확인
5. **80~90초:** weather/event feed를 끄고 `context_status` 변화와 `inventory_temporal` 또는 `current_stock` 강등 확인

현장 신고는 별도 보조 시나리오로 시연한다. 단일 성공 사례는 모델 성능 증거가 아니며, 같은 화면에 held-out 전체·강수·휴일·행사·공간 slice와 ablation 결과를 함께 제시한다.

필수 검수:

- 네트워크 차단 상태에서 로컬 fixture와 정적 지도/목록으로 완주
- 데이터 실패가 고장 신호로 변환되지 않음
- 화면 어디에도 보정 대수나 자동 고장 확정 표현이 없음
- 키보드, 스크린리더 이름, 200% 확대, 오류 메시지 검수
- 발표 화면에 `demo` 워터마크와 추정 한계 표시
- 실제 archived context가 없는 시나리오는 전부 `demo` 워터마크이며 평가·성능 주장에 포함하지 않음
- context evidence를 “원인”으로 표현하지 않고, 표시한 source·issued/valid 시각이 fixture와 일치함

## 2. 해커톤 이후 승격 단계

### S0 — 관측 수집

진입: API 게이트 통과.

종료 조건:

- API 제한과 실질 갱신주기가 허용하면 원시 재고를 1분 간격으로 수집하고, 그렇지 않으면 게이트에서 확인한 2~5분 간격을 사용한다. 학습·평가용 정규 격자는 원시값에서 5분 단위로 생성하며 원본을 덮어쓰지 않는다.
- 위 원시 재고와 5분 학습 격자를 대상 정류장에서 2주 이상 안정적으로 수집
- 날씨 예보 vintage, 달력, 행사 수정·취소 이력, 인접 정류장 context를 동일 기간 point-in-time 형태로 보존
- 수집 성공률 99% 이상
- 중복·시간 역행·음수 재고 자동 검사 통과
- context의 `event_time/available_at/ingested_at/source_version` 누락·역행 검사 통과
- 데이터 사전, feature contract, graph와 fixture 버전 고정

S0의 2주는 수집 파이프라인 안정성 확인 기준일 뿐 L3 예측 승인 기준이 아니다. 기존 28일·42일 평가는 파이프라인과 재고 기준선의 예비 결과일 뿐, 계절·날씨·휴일·행사 일반화 근거가 아니다. contextual ML 승격 기간과 regime coverage는 `02_DATA_AND_EVALUATION.md` §7의 별도 게이트를 따른다.

### S1 — contextual 재고 예측 평가

진입: S0 완료.

종료 조건:

- B0 persistence·경험적 전이, B1 정류장×요일×시간×재고 버킷, B2 elastic-net logistic 재고·시간 모델, B3 투명한 logistic 맥락 모델, M1 CatBoost와 동등 예산 LightGBM challenger를 동일 rolling-origin·동일 coverage로 비교
- `02_DATA_AND_EVALUATION.md` §7의 contextual 승인 기준을 모두 통과하고 사전 선택된 B3 또는 M1 후보가 B2 대비 Brier·calibration·false-go를 개선함. M1은 B3 대비 추가 가치가 있을 때만 선택
- 날씨·휴일·행사·공간 feature block을 하나씩 제거한 ablation과 강수/비강수·휴일/평일·행사/비행사·held-out 정류장 slice 공개
- B3와 M1 contextual 후보가 모두 B2보다 나아지지 않으면 `prediction_basis=contextual_ml` 승격을 중단하고 `inventory_temporal`만 유지. B3가 통과하고 M1이 B3를 이기지 못하면 B3를 사용
- 기간 자체를 자동 종료 조건으로 삼지 않는다. 제한 파일럿은 연속 12주를 권고하되, 실제 승격은 `02_DATA_AND_EVALUATION.md` §7의 사전등록 regime coverage와 versioned gate가 결정한다. 더 짧은 기간은 누락 regime·위험·적용 범위를 기록한 명시적 예외 승인이 있어야 하며, 계절 일반화 주장은 최소 12개월을 권고하면서 동등한 계절 holdout 증거와 별도 gate를 함께 요구한다.
- `stockout_risk_grade`가 `low → medium → high`로 갈수록 실제 소진율이 단조 증가
- 전체 표본과 `parking_count(t)>0`인 실제 소진 가능 표본을 함께 평가하고, 시간 fold 경계에는 최소 15분 purge를 둔다. 정류장·행사 holdout과 station-day/date block bootstrap 신뢰구간을 함께 공개한다.
- 정류장 그룹별 성능 편차와 콜드스타트 정책 공개
- feature lineage와 point-in-time join 재현율 100%, 미래 정보 누수 검사 통과

#### S1a — shadow

- 최소 4주 동안 live 응답에 노출하지 않고 contextual·inventory 모델을 병렬 기록한다.
- critical context 가용률, context freshness 위반, 모델별 disagreement와 fallback 비율을 관찰한다.
- model card, feature contract, calibration/threshold 버전을 제품 책임자와 데이터·모델 책임자가 교차 승인한다.

#### S1b — canary

- shadow 게이트 통과 후 10~20개 정류장에만 기능 플래그로 공개한다.
- context feed 장애, distribution shift, false-go 가드레일 위반 시 즉시 `inventory_temporal` 또는 `current_stock`으로 내린다.

### S2 — 정체 신호 섀도 모드

진입: S0 완료. 사용자 노출 없음.

종료 조건:

- 최소 28일 섀도 로그
- 신고를 입력으로 사용하지 않은 독립 평가셋 확보
- 현장점검 또는 사후 확인 라벨로 Precision@k 측정
- 오탐 원인 분류와 중단 기준 통과

S2를 통과해도 기본 명칭은 `재고 정체 신호·확인 필요`다. `고장 의심`으로 바꾸려면 정체와 실제 고장 사이의 별도 인과 근거, 운영기관 검토, 제품·데이터 승인과 계약 변경이 추가로 필요하다.

### S3 — 제한 공개

진입: S1 제품 지표 또는 S2 안전 기준 통과.

종료 조건:

- 추천 정류장 방문 후 첫 대여 성공률 측정
- 정상/저위험 표시 후 이용불가 조우율 가드레일 충족
- 신고 완료율, 공식 신고 전환율, 7일 재사용률 측정
- 개인정보 삭제·보존·남용 대응 운영 테스트 통과

### S4 — 운영기관 제휴

진입: 시민 파일럿 트랙레코드와 독립 평가 결과 확보.

필요 증거:

- 불필요한 현장 순회 감소 가능성
- 고장 방치시간과 검증 티켓당 비용
- 데이터 품질 SLA
- 커뮤니티 신고가 공식 신고를 대체하지 않는 연계안

공식 정비 상태와 `confirmed_fault`는 제휴 데이터 계약이 생긴 이후에만 활성화한다.

## 3. 우선순위 백로그

### P0

- `national_integrated`·`direct_tashu` 성공 응답 fixture, 7일 비교 결과와 데이터 사전
- 날씨·달력·행사·graph adapter와 versioned context fixture
- point-in-time feature builder와 누수 방지 테스트
- B0/B1/B2 재고 기준선, B3 투명한 맥락 기준선, CatBoost contextual 후보와 동등 예산 LightGBM challenger, probability calibration
- OpenAPI 계약 테스트
- live/demo adapter
- 데이터 최신성·출처 표기
- prediction basis/context status/provenance를 포함한 Core 위험 산출과 대안
- 안전한 익명 신고·취소
- 정적 지도 또는 목록 오프라인 폴백

### P1

- station 스냅샷 수집·품질 모니터링
- context 가용률·freshness·schema drift 모니터링
- 시간·정류장·행사 holdout 평가와 nested ablation 파이프라인
- shadow/canary 및 model card 승인 절차
- 접근성 자동검사와 시각 회귀 테스트
- 독립 현장감사 표본 설계
- 운영기관 인터뷰와 ROI 지표

### P2

- 사용자 동의 기반 사진 신고
- 자유 텍스트 LLM 분류
- 정체 신호 섀도 모델
- 운영 브리핑
- 공식 정비 연동

## 4. 중단 규칙

- 실제 API가 안정적으로 제공되지 않으면 공개 live 서비스 개발을 중단한다.
- contextual 모델이 가장 강한 재고·시간 기준선보다 개선되지 않으면 복잡도와 무관하게 `contextual_ml`로 배포하지 않는다.
- 맥락 원천이 결측·지연됐을 때 이를 `비 없음`, `행사 없음`으로 바꾸거나 검증되지 않은 범용 결측 대체로 계속 예측하지 않는다.
- 당시 이용 가능했던 context를 재현하지 못하면 해당 표본을 contextual 성능 근거로 사용하지 않는다.
- 독립 라벨이 없는 이상탐지는 사용자에게 고장 신호로 노출하지 않는다.
- 신고 남용·개인정보 삭제를 운영할 수 없으면 공개 신고 기능을 닫는다.
- 제휴 전에는 커뮤니티 접수를 공식 처리 상태처럼 표현하지 않는다.
