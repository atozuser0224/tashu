# 타슈 해커톤 제품 MVP 명세 v2

> 상태: 구현 기준안  
> 범위: 해커톤 데모 및 소규모 사용자 검증  
> 제품 원칙: **공식 재고, 예측, 커뮤니티 현장 정보를 합치거나 서로의 대체값으로 쓰지 않는다.**

## 0. 한 줄 결정

이 MVP는 고장을 자동 판정하거나 실제 이용가능 대수를 새로 계산하지 않는다. 예측 시점까지 확인된 타슈 공식 재고와 날씨 예보·시간·휴일·행사 일정·주변 정류장 흐름을 point-in-time으로 결합해 **정확히 15분 후 공식 재고가 1대 미만일 위험**을 보여주고, 사용자가 즉시 선택할 수 있는 대안 정류장과 짧은 현장 신고를 제공한다.

---

## 1. 핵심 JTBD와 가설

### 1.1 하나의 핵심 JTBD

> 약 15분 뒤 타슈를 타야 할 때, 허탕칠 가능성이 낮은 정류장을 빠르게 골라 바로 이동하고 싶다.

이 JTBD의 성공은 사용자가 AI 설명을 읽는 것이 아니라, **30초 안에 정류장을 결정하고 첫 방문에서 자전거를 빌리는 것**이다.

### 1.2 핵심 사용자

- 출발 직전 또는 정류장으로 걸어가는 중인 타슈 이용자
- 현재 위치에서 도보 15분 거리 안에 둘 이상의 정류장을 선택할 수 있는 사람
- 연령·숙련도·언어와 무관하게 “지금 탈 수 있는 곳”을 빠르게 판단하려는 사람

초기 사용자 모집은 출퇴근 시간대의 이용 빈도가 높은 정류장 주변에서 하되, “20~40대 출퇴근자”처럼 검증되지 않은 인구통계로 제품 사용자를 제한하지 않는다.

### 1.3 문제·가치 가설

아래는 사실이 아니라 검증할 가설이다.

| ID | 가설 | 반증 조건 |
|---|---|---|
| H1 문제 | 같은 현재 재고라도 출퇴근 시간, 휴일, 당시 발표된 날씨 예보·행사 일정, 주변 정류장 흐름에 따라 15분 뒤 결과가 달라져 사용자가 첫 정류장에서 허탕친다. | 사용자 인터뷰·현장 관찰에서 재고 소진이 주요 실패 원인이 아니거나 맥락 변화가 정류장 선택에 영향을 주지 않는다. |
| H2 가치 | contextual ML의 15분 소진 위험과 공간적으로 독립적인 가까운 대안을 함께 제시하면 current-stock·시간 버킷·재고와 시간만 쓰는 `inventory_temporal` 기준보다 첫 방문 대여 성공률을 높이고 false-safe를 줄인다. | 같은 coverage의 current-stock·시간 버킷·`inventory_temporal` 대비 예측·행동 지표와 첫 방문 결과가 개선되지 않는다. 복잡한 M1이 투명한 B3를 이기지 못하면 M1의 추가 가치는 반증된다. |
| H3 기여 | 대상이 미리 선택된 15초 내 현장 신고와 공식 신고 연결을 제공하면 사용자가 실패 정보를 남긴다. | 신고 시작 대비 완료율이 낮거나 공식 신고 전환으로 이어지지 않는다. |
| H4 운영 | 집계된 재고 소진 신호와 현장 신고가 운영기관의 점검 우선순위 판단 시간을 줄인다. | 운영 담당자가 현재 업무보다 신뢰할 수 없거나 조치 불가능하다고 판단한다. |
| H5 이해 | 모델 판단에 실제로 반영된 맥락을 출처·기준시각과 함께 최대 두 개만 보여주면 30초 결정시간을 해치지 않고 사용자가 관측·예측·원인을 구분한다. | 사용자가 맥락 신호를 인과적 원인으로 오해하거나 결정시간·과업 성공률이 악화된다. |

---

## 2. 제품 원칙

1. **행동 우선**: 긴 AI 설명보다 “이 정류장으로 이동”과 “다른 정류장 보기”를 먼저 제공한다.
2. **출처 분리**: 타슈 API 값은 `공식 재고`, 모델 출력은 `재고 소진 위험`, 이용자 입력은 `커뮤니티 현장 정보`로 각각 표시한다.
3. **숫자 불변**: 커뮤니티 신고나 예측 결과로 공식 재고를 차감하지 않는다. `보정 대수`, `실제 대수` 필드를 만들지 않는다.
4. **확실성 과장 금지**: `이용가능`, `정상`, `고장 확정`, `수리 완료`처럼 현장 또는 운영기관 확인을 전제하는 표현을 자동으로 만들지 않는다.
5. **최신성 노출**: 모든 공식 재고와 예측에는 기준 시각을 표시한다. `null`, 결측, 지연을 `0대`로 바꾸지 않는다.
6. **런타임 강등**: 데이터·모델 품질이 기준을 벗어나면 승인된 더 단순한 prediction basis 또는 더 낮은 기능명·문구로 즉시 강등한다.
7. **공식 조치 연결**: 커뮤니티 신고가 공식 고장 신고를 대신하지 않는다고 제출 전후에 알리고 공식 채널 CTA를 제공한다.
8. **접근 가능한 목록 우선**: 지도는 보조 시각화다. 같은 정보와 기능을 갖춘 목록이 항상 존재해야 한다.
9. **point-in-time 맥락**: 예측 시점에 알 수 있었던 날씨 예보·휴일·행사 일정과 공식 재고만 사용한다. 미래 실측 날씨, 사후 수정된 행사 정보, 목표시점 이후 주변 재고를 사용하지 않는다.
10. **근거는 최대 두 개**: 사용자에게는 모델 판단에 실제로 반영된 구조화 근거를 출처·발행 또는 갱신 시각과 함께 최대 두 개만 보여준다. contextual이면 외부 맥락, temporal이면 공식 재고 근거만 허용하며 인과 표현과 raw SHAP 값은 노출하지 않는다.
11. **개인 입력 격리**: 사용자의 현재 위치는 도보시간 계산에만 사용하고, 위치·검색어·커뮤니티 신고·자유 메모는 예측 feature나 모델 정답으로 사용하지 않는다.

---

## 3. 해커톤 MVP 범위

### 3.1 Core — 15분 후 재고 소진 위험

> 해커톤에서는 live L3를 활성화하지 않는다. 이 Core의 L3 화면은 `data_source=demo` 워터마크 아래에서만 시연하고, 실데이터는 L1 `current_stock` 또는 L2 `demand_pressure`로 강등해 표시한다.

#### 사용자 가치

현재 몇 대가 있는지만 보여주는 대신, 최근 공식 재고 흐름과 예측 시점에 알 수 있었던 시공간 맥락의 상호작용을 학습한 contextual ML로 **정확히 t+15분 시점에 API상 재고가 1대 미만일 위험**을 `stockout_risk_grade`의 `low/medium/high`로 제공한다. 사용자 문구는 항상 `소진 위험 낮음/보통/높음`으로 써서 “가용성 높음”과 방향이 뒤집히지 않게 한다.

#### 예측 대상

- 내부 가용성 타깃: `y_available = 1[parking_count(t+15분) >= 1]`
- 외부 소진 위험: `p_stockout_15m = 1 - P(y_available=1)`. 즉 소진 사건은 `parking_count(t+15분) < 1`
- 중간에 0대가 되었다가 t+15분에 다시 1대 이상이 된 경우는 소진 타깃이 아니다.
- 재고 입력: 타슈 공식 API의 대상 정류장과 주변 정류장 `parking_count` 중 예측 시점 `t`까지 관측된 값만 사용
- 시간·휴일 입력: 서버 기준 KST 시각과 예측 시점에 공표돼 있던 공식 휴일 달력만 사용
- 날씨 입력: `t` 이전에 발행되어 `t+15분`에 유효한 예보만 사용하며, 사후 실측 날씨를 당시 예보처럼 사용하지 않음
- 행사 입력: `t`까지 공개된 일정·장소·시작/종료·수정/취소 상태만 사용하며, 확인되지 않은 참석자 수를 사실처럼 채우지 않음
- 공간 입력: 버전이 고정된 station graph와 `t`까지의 주변 공식 재고 흐름만 사용. 사용자의 현재 위치는 graph feature가 아니라 도보 policy 입력으로만 사용
- 비맥락 폴백 입력: `inventory_temporal`은 대상 정류장의 `t`까지 공식 재고 lag·rolling 통계와 서버 KST 시간 feature만 사용하며 contextual ML과 별도로 학습·보정·승인
- 입력 금지: 커뮤니티 신고, 자유 메모, 사용자 위치·검색어·이동경로, 목표시점 이후 값
- 출력: 보정된 `stockout_probability`, 위험 등급과 `prediction_basis`; `contextual_ml`은 사용한 외부 맥락 근거, `inventory_temporal`은 사용한 공식 재고 근거를 각각 1~2개와 출처·발행/갱신 시각으로 제공. 확률은 API 계약과 평가 로그에 제공하되 기본 UI는 이해 검증 전 등급을 우선한다.
- 출력 금지: 예상 실제 대수, 고장 대수, 개별 자전거 상태, 고장 원인, 대여 보장 확률, 인과 단정, raw SHAP 값

#### 사용자 노출 등급

| `stockout_risk_grade` | 의미 | 기본 문구 |
|---|---|---|
| `high` | 검증된 임계값상 15분 후 공식 재고 소진 가능성이 큼 | **15분 후 재고 소진 위험: 높음** |
| `medium` | 소진 신호가 있으나 `high` 기준에는 미달 | **15분 후 재고 소진 위험: 보통** |
| `low` | 현재 모델 기준 소진 신호가 낮음 | **15분 후 재고 소진 위험: 낮음** |

모든 등급 아래에는 `prediction_basis`에 맞는 보조 문구 하나만 고정한다.

- `contextual_ml`: `타슈 공식 재고와 예측 시점에 확인된 상황을 반영한 전망이며 실제 대여 가능 여부를 보장하지 않아요.`
- `inventory_temporal`: `타슈 공식 재고·재고 흐름·시간대에 기반한 전망이며 날씨·휴일·행사 상황은 반영하지 않았고 실제 대여 가능 여부를 보장하지 않아요.`

#### Core 인수 조건

- 공식 재고 숫자와 예측 등급이 서로 다른 카드·접근성 그룹으로 렌더링된다.
- 프론트엔드는 예측을 계산하지 않고 서버가 전달한 `decision_signal.mode`, `stockout_risk_grade`, `generated_at`만 표시한다.
- `decision_signal.mode !== "stockout_risk"`이면 화면 어디에도 `15분 후 전망`, `재고 소진 위험 낮음/보통/높음` 문구가 나오지 않는다.
- `stockout_risk_grade`는 `low/medium/high` 또는 `null`만 허용한다. 데이터 부족을 네 번째 등급으로 만들지 않고 모드를 강등한다.
- UI는 서버 응답의 canonical `data_freshness=fresh|stale|unavailable`을 그대로 사용하고 재계산하지 않는다. `freshness_detail.stale_after_seconds`와 `unavailable_after_seconds`는 설명·진단용 metadata다.
- `data_freshness`가 `stale` 또는 `unavailable`이면 `stockout_risk_grade`를 숨긴다. `data_source=demo`의 서버 기본 threshold는 600초/1,800초다.
- 사용자에게 노출하는 근거는 서버가 반환한 구조화 evidence 중 실제 모델 판단에 반영된 최대 두 개로 제한한다. contextual이면 외부 맥락, temporal이면 공식 재고만 허용한다. 각 근거에는 유형, 출처, 발행 또는 갱신 시각이 있어야 하며, 근거가 원인임을 암시하거나 raw SHAP 수치를 보여주지 않는다.
- contextual ML 결과에는 model·feature contract·station graph·context snapshot 버전을 남긴다. 실제 archived context와 point-in-time 평가가 없으면 live L3가 아니라 `data_source=demo`로만 시연한다.
- 필요한 맥락이 결측·지연됐을 때 full-context 결과를 유지하거나 결측을 `비 없음/행사 없음`으로 바꾸지 않는다. fresh snapshot이면 별도 승인된 `inventory_temporal`, L1 `current_stock` 순으로 강등하고, snapshot이 stale/unavailable이면 검증된 L2 `demand_pressure`, L0 순으로 강등한다.
- `0`은 유효한 값이고 `null`은 결측이다. 두 상태가 UI·로그·API에서 구분된다.
- 모델·규칙 버전과 당시 입력 품질 상태를 분석 로그에 남겨 재현할 수 있다.

### 3.2 Supporting A — 대안 정류장

#### 동작

- 현재 정류장에서 예상 도보 15분 또는 1.2km 이내 후보를 최대 3개 보여준다. 두 값은 설정으로 변경할 수 있다.
- 공식 재고가 `0`이거나 `data_freshness=stale|unavailable`인 후보는 실제 이동 추천에서 제외한다. `data_source=demo` 후보는 워터마크와 함께 기능 시연에만 사용한다.
- `stockout_risk` 모드에서는 각 후보의 승인된 `prediction_basis`가 낸 소진 위험을 `low → medium → high` 순으로 묶는다. 같은 위험 그룹에서 예상 도보시간이 짧은 순, 공식 재고가 많은 순으로 정렬하며 사용자 위치는 이 도보 policy에만 사용한다. `inventory_temporal` 후보를 contextual 후보처럼 표시하지 않는다.
- `current_stock` 모드에서는 최신성이 확보된 후보를 우선하고, 도보시간이 짧은 순, 공식 재고가 많은 순으로 정렬한다.
- `demand_pressure` 모드는 현재 재고 스냅샷이 없다는 뜻이므로 정상 추천 후보 자격을 주지 않는다. 대안이 전부 이 모드라면 `현재 재고를 확인할 수 있는 대안이 없어요`라고 알리고 참고 목록으로만 보여준다.
- 커뮤니티 신고는 공식 재고를 차감하지 않는다. 최근 신고가 있는 후보에는 경고 문구만 병기한다.
- 각 후보에는 외부 지도 앱 또는 웹 길찾기로 연결되는 `이 정류장으로 이동` CTA를 제공한다.

#### 빈 상태

> 지금 신뢰할 수 있는 대안 정류장을 찾지 못했어요. 타슈 공식 앱에서 최신 정보를 다시 확인해 주세요.

#### Supporting A 인수 조건

- 위치 권한을 거부해도 정류장명·주소 검색으로 동일 기능을 사용할 수 있다.
- 추천마다 `예상 도보시간`, `공식 재고`, `조회 시각`, 현재 허용된 신호명만 보인다.
- 목록 API에는 `query`를 사용하고, 도보시간이 필요할 때만 단일 `origin=lat,lon`을 보낸다. `walk_minutes=null`이면 임의 추정값을 만들지 않고 거리 문구를 숨긴다.
- 대안이 없을 때 오래된 후보를 정상 후보처럼 채워 넣지 않는다.

### 3.3 Supporting B — 현장 신고

#### 입력

정류장 상세에서 진입하므로 정류장은 미리 선택한다. 해커톤 MVP는 계정, QR 해석, 사진 업로드를 요구하지 않는다.

문제 유형은 [`contracts/enums.json`](./contracts/enums.json)의 `report_category` 여섯 코드와 1:1로 고정한다. API에는 표시문구가 아니라 코드값을 전송한다.

| 순서 | `report_category` | 사용자 문구 | 즉시 행동 |
|---:|---|---|---|
| 1 | `count_mismatch` | 표시 수량 불일치 | 커뮤니티 신고 접수 |
| 2 | `unlock_failure` | 잠금 불가 | 공식 신고 CTA 제공 |
| 3 | `battery_or_power` | 배터리·전원 문제 | 공식 신고 CTA 제공 |
| 4 | `safety_risk` | 안전 위험 | **이 자전거를 이용하지 마세요** + 공식 신고 CTA 최상단 |
| 5 | `physical_damage` | 외관·기계 파손 | 공식 신고 CTA 제공 |
| 6 | `other` | 기타 | 200자 메모 입력 권장 |

선택 입력은 200자 이내 `description`과 40자 이내 nullable `bike_reference`다. `ReportCreateRequest`는 `station_id`, `category`, `privacy_notice_version`을 필수로 보내고 두 선택 필드는 값이 있을 때만 보낸다. `bike_reference`는 사용자가 보거나 스캔한 참조 문자열일 뿐 검증된 자전거 ID, 사용자·기기 ID 또는 공식 확인 근거가 아니다.

#### 제출 정책

- 기본 경로는 `유형 선택 → 제출` 두 단계이며 목표 완료시간은 중앙값 15초 이내다.
- 안전 문제를 고르면 제출 전 **“이 자전거를 이용하지 마세요”**를 표시하고 공식 신고 CTA를 최상단에 둔다.
- 성공 화면은 커뮤니티 접수와 공식 신고를 명시적으로 분리한다.
- 오프라인에서는 `전송 완료`라고 표시하지 않는다. 로컬 임시저장 후 재연결 시 사용자 확인을 받아 전송한다.
- rate limit, signed 익명 세션, idempotency, capability token 정책은 [`03_ARCHITECTURE_SECURITY.md`](./03_ARCHITECTURE_SECURITY.md)를 단일 기준으로 따른다. 원본 IP와 capability token을 제품 분석 로그에 넣지 않는다.
- 성공 응답의 `status`는 canonical `report_status=received`다. `capability_token`은 생성 및 동일 멱등 요청의 응답 재생에서만 받을 수 있고 이후 조회 API로 복구할 수 없다. URL·로그에 저장하지 않으며 신고 상세·취소 권한에만 사용한다.
- 해커톤 MVP에서 사진을 수집하지 않는다. 이후 추가하려면 EXIF 제거, 얼굴·번호판 처리, 보존기간, 삭제 요청 절차가 선행되어야 한다.

#### 활성·만료 표시

클라이언트는 유형별 TTL을 하드코딩하지 않고 서버의 `community_report_state`와 개별 `report_status`를 따른다. `expired`는 커뮤니티 표시 유효기간 종료일 뿐 문제 해결이나 수리 완료를 뜻하지 않는다.

#### 제출 완료 문구

> 커뮤니티 현장 정보로 접수했어요. 이 접수는 타슈 공식 고장 신고가 아니에요.

CTA:

- `타슈에 공식 신고하기`
- `정류장 상세로 돌아가기`

---

## 4. 명시적 제외 범위

해커톤 MVP에서는 다음을 구현하거나 사용자에게 암시하지 않는다.

- 사용자 노출용 자동 고장 판정 및 `고장 확정` 배지
- 공식 재고에서 AI·신고 대수를 차감한 `보정된 실제 이용가능 대수`
- 개별 자전거 고장·배터리·잠금 상태 자동 추론
- 정체 재고를 근거로 한 고장 원인 생성
- 운영기관 확인 없는 `정비중`, `수리완료`, `검증완료` 상태
- 운영기관 정비사 배정·출동·정비 티켓 연동
- 거치대 용량이 검증되기 전의 `만차`, `남은 거치대` 표시
- 실시간 개별 자전거 GPS 추적
- 공식 앱 대체, 결제·요금 분쟁 처리
- QR 형식과 사용 권한이 검증되기 전의 QR 자전거 식별
- 전국 확장, 계정·등급·리워드·소셜 랭킹
- 사용자의 현재 위치·검색어·이동경로·커뮤니티 신고를 예측 feature 또는 모델 정답으로 사용하는 기능
- 실제 발행 이력이 없는 날씨 예보·행사 일정이나 사후 실측값을 live 예측 근거처럼 사용하는 기능
- 맥락 근거를 소진의 원인으로 단정하거나 raw SHAP 값·feature weight를 사용자에게 노출하는 기능
- LLM이 구조화 계약에 없는 사실·원인·등급·대안·추천을 생성하는 기능

운영기관 연동이 생기더라도 공식 상태는 별도 네임스페이스와 출처로 추가하며, 기존 커뮤니티 상태를 공식 상태로 승격하지 않는다.

---

## 5. 데이터 검증과 기능명 강등 규칙

### 5.1 기능 등급

L0~L3는 데이터 가치의 단순 서열이 아니라 **현재 스냅샷 유무와 검증 상태에 따라 선택하는 표현 모드**다. 특히 L2는 L3의 낮은 정확도 버전이 아니라, 현재 스냅샷 없이 과거 패턴만 설명하는 별도 개념이다.

| 등급 | `decision_signal.mode` | 필요한 근거 | 계약 필드 | 허용 기능명·표현 | 금지 표현 |
|---|---|---|---|---|---|
| L3 | `stockout_risk` | fresh 현재 스냅샷과 동일 t+15 타깃의 승인된 예측 basis. `contextual_ml`은 point-in-time 맥락 archive·기준선 대비 증분 성능·맥락별 게이트, `inventory_temporal`은 별도 재고·시간 평가·보정 게이트를 통과 | `stockout_risk_grade=low/medium/high`, `prediction_basis=contextual_ml\|inventory_temporal`; evidence는 contextual이면 외부 맥락, temporal이면 공식 재고만 1~2개 | contextual: `상황 반영 15분 후…`; temporal: `재고·시간 기반 15분 후…` | 가용성 높음, 실제 이용가능, 대여 보장, temporal 결과의 외부 상황 반영 주장, 맥락이 원인이라는 단정 |
| L2 | `demand_pressure` | 현재 스냅샷은 없지만 과거 동요일·동시간대 표본과 등급 기준은 검증됨 | `stockout_risk_grade=null`, `demand_pressure_grade=low/medium/high`, `prediction_basis=historical_demand`, `context_evidence=[]` | `과거 같은 시간대 수요 압력: 낮음/보통/높음` | 현재 위험, 15분 후 전망, 현재 재고, 추천 가능 |
| L1 | `current_stock` | 현재 `parking_count`와 수집 시각만 신뢰 가능 | 두 grade 모두 `null` | `타슈 공식 재고`, `우리 서비스가 N분 전 조회` | 흐름, 전망, 예측, 실제 대수 |
| L0 | `unavailable` | 스키마 불명, 지연, 호출 실패, 시각 불명이며 검증된 과거 표본도 없음 | 두 grade 모두 `null` | `정보 지연`, `현재 정보를 확인할 수 없음` | 0대, 이용가능, 추천 |

`demand_pressure_grade`는 과거 같은 요일·시간대의 **역사적 대여 수요 압력**을 요약한 값이다. 산식은 `02_DATA_AND_EVALUATION.md` §8을 따르며 순재고 감소량으로 대체 계산하지 않는다. 현재 재고, 현재 수요, 15분 후 소진 위험을 뜻하지 않으며 `stockout_risk_grade`의 대체 입력으로 사용하지 않는다.

L2 표본·등급·강등 조건의 단일 출처는 [`02_DATA_AND_EVALUATION.md`](./02_DATA_AND_EVALUATION.md) **§8**이다. 이 문서에서 별도의 최소 날짜 수·관측 창 수·percentile을 정의하지 않는다. §8을 통과하지 못하면 `demand_pressure_grade`를 만들지 않고 L0로 내린다.

### 5.2 강등 정책

- 현재 스냅샷이 정상일 때 출시 기본값은 L1이다. L3 검증 문서와 승인 전에는 `stockout_risk_grade`를 만들지 않는다.
- 현재 스냅샷이 정상이고 contextual ML이 미승인·미달·오류이거나 필수 맥락이 결측·지연됐으면 full-context 결과와 상황 근거를 숨긴다. 동일 타깃으로 별도 승인된 `inventory_temporal`이 있으면 L3 `stockout_risk`를 유지하되 `재고·시간 기반`으로 표시하고, 없으면 L1 `타슈 공식 재고`로 강등한다.
- `inventory_temporal`은 맥락 결측을 보간하는 모델이 아니다. 날씨·휴일·행사·주변 흐름을 반영했다고 표시하거나 맥락 근거를 붙이지 않는다.
- 현재 스냅샷이 없고 L2 과거 표본 게이트를 통과하면 `과거 같은 시간대 수요 압력`만 표시한다. `demand_pressure_grade`를 `stockout_risk_grade`로 복사하거나 매핑하지 않는다.
- 현재 스냅샷과 검증된 과거 표본이 모두 없으면 L0로 강등한다. 데모 일정은 예외 사유가 아니다.
- freshness 판정은 서버의 canonical `data_freshness=fresh|stale|unavailable`을 따른다. UI는 `age_seconds`나 현재 시각으로 이를 재분류하지 않는다.
- `freshness_detail.stale_after_seconds`와 `unavailable_after_seconds`는 설명·진단용 metadata다. `data_source=demo`의 서버 기본값은 각각 600초와 1,800초이며 UI 로직에 하드코딩하지 않는다.
- `stale`에서는 현재 숫자에 오래된 정보임을 표시하고 L3를 숨긴다. `unavailable`에서는 현재 숫자와 L3를 모두 숨기고, 검증된 과거 표본이 있으면 L2, 없으면 L0로 내린다.
- `demo`는 freshness가 아니라 합성·고정·리플레이 데이터를 뜻하는 `data_source` 값이다. 모든 화면에 `데모 데이터 · 실제 현재 정보가 아님` 워터마크를 고정하고 실제 이동 추천, 현장 신고 전송, 제품 KPI 산정에 포함하지 않는다.
- live 공식 재고에 synthetic 날씨·행사·graph 맥락을 섞어 live 예측처럼 보이지 않는다. 맥락 입력 중 하나라도 합성이면 해당 contextual ML 결과와 대안은 전체를 demo로 취급한다.
- 캐시를 표시할 때는 `마지막 조회 N분 전`을 함께 읽어 주며, 캐시된 `stockout_risk_grade`는 유지하지 않는다. 별도 과거 표본 게이트를 통과한 경우에만 L2로 전환한다.
- API 필드 의미나 좌표 축이 바뀌면 fail-closed로 L0를 반환한다.
- 프론트엔드는 `mode`별 허용 문구 테이블을 사용한다. `stockout_risk_grade=high`는 반드시 `소진 위험 높음`, `demand_pressure_grade=high`는 반드시 `과거 수요 압력 높음`으로 읽고 “가용성 높음”으로 번역하지 않는다.
- 서버가 두 grade를 동시에 non-null로 보내거나 mode와 맞지 않는 grade를 보내면 계약 오류로 처리하고 L0 문구를 표시한다.
- 등급 상향은 제품 책임자와 데이터 검증 책임자가 증거 문서를 함께 승인한 뒤 기능 플래그로 적용한다.

### 5.3 L3 예측 basis 데이터 게이트

L3 승격 조건의 단일 출처는 [`02_DATA_AND_EVALUATION.md`](./02_DATA_AND_EVALUATION.md) **§7.1~7.8**의 타깃·feature·기준선·contextual 평가 계약이다. 승인된 versioned `evaluation_gate`가 없으면 L3는 승인 불가다. 이 제품 문서에는 표본 수, 기간, 정밀도, 재현율, 등급 임계값을 중복 정의하지 않는다.

- 위 절에서 해당 basis의 데이터 품질·평가·보정·승인 조건을 통과하기 전 live 데이터에서 `decision_signal.mode=stockout_risk`를 반환하지 않는다.
- 학습·평가의 날씨는 당시 이용 가능했던 예보 archive, 행사는 당시 공개된 일정·수정·취소 snapshot, 주변 흐름은 fold 시점에 유효한 graph와 `t`까지의 공식 재고만 사용해야 한다.
- contextual ML은 current-stock/persistence, 기존 동요일·시간 버킷, 승인 후보 `inventory_temporal`, 동일 맥락을 쓰는 투명한 규칙 또는 단순 모델을 사전 정의된 동일 coverage 지표에서 모두 비교한다. 맥락의 증분 가치를 보이지 않으면 `prediction_basis=contextual_ml`로 승격하지 않는다.
- contextual 경로가 실패해도 재고 lag·rolling과 시간 feature만 쓰는 모델이 자체 평가·보정 게이트를 통과했으면 `prediction_basis=inventory_temporal`로 강등할 수 있다. 이 경우 evidence는 fresh 공식 재고 근거 1~2개로 제한하고 외부 상황 근거와 `상황 반영` 문구를 사용하지 않는다. 해당 basis도 미승인이면 L1로 내린다.
- 전체 평균뿐 아니라 강수 예보, 평일/휴일, 행사 전후, 신설 정류장, 공간 권역과 맥락 결측 slice의 calibration·false-safe·coverage를 보고한다. 고정 42일 기준만으로 드문 휴일·행사 성능을 주장하지 않는다.
- time/weather/holiday/event/spatial feature group별 ablation과 held-out event·시간·공간 평가를 남기고, 사용자에게 보이는 근거가 실제 입력·방향·출처·시각과 일치하는지 자동 검증한다.
- 사용자의 현재 위치·검색어·이동경로와 커뮤니티 신고가 feature manifest에 없음을 계약·정적 검사로 확인한다.
- 평가 문서가 없거나 결과가 미승인 상태이면 L3 기능 플래그의 기본값은 `off`다.
- **해커톤에서 허용되는 실데이터 모드는 L1 `current_stock`과 L2 `demand_pressure`뿐이다.**
- `data_source=demo`에서는 L3 UI를 시연할 수 있으나, 전 화면 워터마크를 유지하고 실제 길찾기·신고·KPI·검증 결과에서 제외한다.
- L3 승인 후에도 제품 문구와 계약 방향성은 이 문서의 `stockout_risk_grade` 규칙을 따른다.

---

## 6. 정보 구조: 정확히 3개 화면

### 화면 1. 주변 정류장

#### 목적

30초 안에 이동할 정류장을 고른다. 목록이 기본이고 지도는 같은 항목을 보조로 보여준다.

#### 구성

1. 현재 위치 또는 주소/정류장 검색
2. 데이터 기준 시각과 전체 지연 안내
3. 정류장 목록
4. 선택형 지도 보기

#### 정류장 행 정보 순서

1. 정류장명과 도보거리
2. `타슈 공식 재고 N대`
3. 현재 제품 모드에 허용된 신호 한 줄. L3 contextual이면 `상황 반영 15분 후 재고 소진 위험`, L3 temporal이면 `재고·시간 기반 15분 후 재고 소진 위험`, L2이면 `과거 같은 시간대 수요 압력`만 표시하고 두 grade를 동시에 노출하지 않음
4. `N분 전 조회`
5. 최근 커뮤니티 신고가 있을 때만 별도 한 줄

#### 예시 문구

해커톤 live 기본 L1:

```text
시청역 8번 출구 · 예상 도보 4분
타슈 공식 재고 3대 · 2분 전 관측
```

L3 승인 후 또는 `data_source=demo` 워터마크 상태:

```text
시청역 8번 출구 · 예상 도보 4분
타슈 공식 재고 3대 · 2분 전 조회
상황 반영 15분 후 재고 소진 위험: 보통
커뮤니티: 최근 신고 1건
```

현재 공식 재고 스냅샷이 없고 L2만 허용될 때는 같은 자리에 다음처럼 표시한다.

```text
타슈 공식 재고를 현재 확인할 수 없어요
과거 같은 시간대 수요 압력: 높음
현재 상태나 15분 후 소진 위험을 뜻하지 않아요
```

#### 상태

- 로딩: 행 높이를 유지한 스켈레톤과 “주변 정류장을 불러오는 중” 상태 알림
- 위치 거부: 검색 입력에 포커스하고 “위치 없이도 정류장을 검색할 수 있어요”
- 전체 지연: 상단 경고 후 예측 숨김
- 맥락 결측·지연: contextual ML 결과와 외부 맥락 근거를 숨기고 fresh snapshot이면 승인된 `inventory_temporal` 또는 L1, snapshot도 stale/unavailable이면 L2/L0 정책으로 강등
- 빈 결과: 검색 반경 확대와 공식 앱 확인 CTA
- 오류: 재시도 버튼, 오류 원인을 색만으로 표현하지 않음

### 화면 2. 정류장 상세·대안

#### 목적

한 정류장의 공식 재고, 재고 신호, 커뮤니티 정보를 구분해 확인하고 이동 또는 대안을 선택한다.

#### 카드 순서

1. **타슈 공식 재고**
2. basis에 맞는 **상황 반영 15분 후 재고 소진 위험**, **재고·시간 기반 15분 후 재고 소진 위험**, 또는 mode에 맞는 **과거 같은 시간대 수요 압력** 중 하나. 두 grade나 서로 다른 basis 제목을 동시에 표시하지 않음
3. **판단에 반영된 정보** — `contextual_ml`이면 외부 상황, `inventory_temporal`이면 공식 재고 근거만 최대 두 개. 각 항목에 출처와 발행·갱신 시각을 표시하며 원인으로 표현하지 않음
4. **가까운 대안 정류장** 최대 3개
5. **커뮤니티 현장 정보** — 활성 신고가 있을 때만
6. CTA `이 정류장으로 이동`, 보조 CTA `현장 상태 알리기`

#### 예시 문구

다음은 contextual L3 승인 후 또는 `data_source=demo` 워터마크 상태의 예시다. `inventory_temporal`이면 제목을 `재고·시간 기반 15분 후 재고 소진 위험`으로 바꾸고 근거에는 fresh 공식 재고·조회 시각만 1~2개 표시한다.

```text
타슈 공식 재고
현재 2대
우리 서비스가 3분 전 조회

상황 반영 15분 후 재고 소진 위험: 높음
판단에 반영된 상황
- 18시 퇴근 시간대 · 서버 KST 18:00 기준
- 20분 뒤 시청광장 행사 종료 예정 · 대전시 행사 일정 17:40 갱신
이 신호들은 모델 입력이며 재고 소진의 원인을 확정하지 않아요.
실제 대여 가능 여부를 보장하지 않아요.

가까운 대안
정부청사역 · 예상 도보 5분 · 공식 재고 6대 · 소진 위험 낮음
[이 정류장으로 이동]
```

L2 화면에서는 다음 문구만 허용한다.

```text
과거 같은 시간대 수요 압력: 높음
과거 동요일·동시간대에 대여 수요가 높았어요.
현재 재고나 15분 후 소진 위험을 뜻하지 않아요.
```

#### 금지 문구

- `실제 1대`
- `AI가 고장 1대를 발견했어요`
- `이용 가능 확정`
- `잠금장치 오류로 보입니다`
- `정비가 필요합니다`
- `비 때문에 자전거가 소진돼요`
- `행사 때문에 이 정류장에는 자전거가 없을 거예요`
- `SHAP +0.42`, `행사 가중치 31%`처럼 사용자가 검증할 수 없는 raw attribution

### 화면 3. 현장 신고

#### 목적

이미 선택된 정류장의 현장 문제를 최소 입력으로 남기고, 필요하면 공식 신고로 연결한다.

#### 구성

1. 정류장명과 `변경` 링크
2. 문제 유형 6개
3. 선택 입력: `자전거에 적힌 번호(선택)` 40자 이내(`bike_reference`), `추가 설명(선택)` 200자 이내(`description`)
4. `커뮤니티 현장 정보 보내기` CTA
5. “공식 신고가 아님” 고지와 개인정보 요약

#### 제출 상태

| 상태 | 문구 | 행동 |
|---|---|---|
| 입력 | **현장에서 본 상태를 알려주세요** | 유형 선택 후 제출 활성화 |
| 전송 중 | **현장 정보를 보내고 있어요** | 중복 제출 방지 |
| 성공 | **커뮤니티 현장 정보로 접수했어요** | 공식 신고·상세 복귀 CTA |
| 오프라인 | **아직 전송되지 않았어요** | 임시저장, 재연결 후 확인 요청 |
| 실패 | **전송하지 못했어요. 입력 내용은 이 기기에 남아 있어요** | 재시도·삭제 제공 |
| 제한 | **잠시 후 다시 시도해 주세요** | 남은 제한시간 제공 |

---

## 7. 공식 상태와 커뮤니티 상태 분리

### 7.1 공식 재고 상태

| UI 상태 / `data_freshness` | 조건 | 사용자 문구 |
|---|---|---|
| `loading` | 최초 요청 중 | 타슈 공식 재고를 불러오는 중 |
| `fresh` | 서버가 `data_freshness=fresh` 반환 | 타슈 공식 재고 N대 · N분 전 관측 |
| `stale` | 서버가 `data_freshness=stale` 반환 | 오래된 정보예요 · N분 전 관측 · 타슈 공식 앱에서 다시 확인해 주세요 |
| `unavailable` | 서버가 `data_freshness=unavailable` 반환 | 현재 공식 재고를 확인할 수 없어요 |

`loading`은 요청 UI 상태이며 `data_freshness` enum이 아니다. `freshness_detail.observed_at_basis=source_observed_at`이면 원천 관측시각을 기준으로 `N분 전 관측`, `observed_at_basis=collected_at`이면 `freshness_detail.collected_at`을 기준으로 **`우리 서비스가 N분 전 수집`**이라고 쓴다. `ingested_at`은 저장 진단값이며 사용자 기준시각으로 쓰지 않는다.

UI는 `data_freshness`를 재계산하지 않는다. `freshness_detail.age_seconds`, `stale_after_seconds`, `unavailable_after_seconds`는 상세 설명·진단에만 쓰며 상태를 덮어쓰지 않는다. `data_source=demo`의 기본 threshold metadata는 600초/1,800초다.

`data_source`는 `data_freshness`와 별도다.

| `data_source` | 의미 | UI 요구사항 |
|---|---|---|
| `live_datago` | 공공데이터포털 조회 경로 | 공식 재고 카드에 출처 표시 |
| `live_direct` | 타슈 직접 OpenAPI 조회 경로 | 공식 재고 카드에 출처 표시 |
| `demo` | 합성·고정·리플레이 데이터 | 전 화면 고정 워터마크 `데모 데이터 · 실제 현재 정보가 아님`, 실제 길찾기·신고 비활성화 |

### 7.2 커뮤니티 상태

상태값은 [`contracts/enums.json`](./contracts/enums.json)의 `community_report_state`만 사용한다. 안전 여부를 이 상태에 인코딩하지 않는다.

| `community_report_state` | 조건 | 사용자 문구 |
|---|---|---|
| `none` | 활성 신고 없음 | 기본적으로 카드 숨김. “문제 없음”으로 해석하지 않음 |
| `recent` | 유효기간 안의 커뮤니티 신고가 있음 | 최근 커뮤니티 신고 N건 |
| `corroborated` | 서로 다른 signed 익명 세션에서 같은 유형이 재확인됨 | 서로 다른 익명 세션에서 같은 유형이 재확인됐어요 |
| `expired` | 표시 기간 종료 | 사용자 기본 화면에서 숨김. `해결됨`으로 바꾸지 않음 |

화면 3에서 사용자가 `report_category=safety_risk`를 선택하면 state와 별개로 다음 경고를 최상단에 표시한다.

> 안전 위험 신고가 있어요. 해당 자전거를 이용하지 말고 상태를 직접 확인해 주세요.

signed 익명 세션은 실제 고유 인원을 증명하지 않는다. `corroborated`를 “서로 다른 이용자 N명”, 신원 확인, 현장 확인 또는 공식 고장 확인으로 표현하지 않는다.

현재 canonical `StationState.community_report_summary`에는 category 집계가 없다. 따라서 정류장 목록·상세에서 `community_report_state`만 보고 안전 신고 존재를 추론하지 않는다. 향후 OpenAPI에 별도 category 집계 필드가 추가된 경우에만 같은 경고를 정류장 화면에 표시한다.

### 7.3 공식 정비 상태

공식 정비 상태는 [`contracts/enums.json`](./contracts/enums.json)의 `official_maintenance_state`를 별도 필드로 사용한다.

| `official_maintenance_state` | 노출 조건 | 사용자 문구 |
|---|---|---|
| `unavailable` | 운영기관 연동 없음 | 공식 처리 상태 연동 안 됨 |
| `unknown` | 연동은 있으나 해당 신고 상태 미확인 | 공식 처리 상태 미확인 |
| `confirmed_fault` | 운영기관이 고장을 확인한 이벤트 수신 | 공식 고장 확인 |
| `under_repair` | 운영기관 정비 진행 이벤트 수신 | 공식 정비 중 |
| `resolved` | 운영기관 조치 완료 이벤트 수신 | 공식 조치 완료 |

해커톤과 제휴 전 기본값은 `unavailable`이다. 커뮤니티 신고, 신고 건수, 예측, 시간 만료로 이 값을 변경하지 않는다.

### 7.4 결합 금지 규칙

- 공식 재고 카드와 커뮤니티 카드는 다른 제목·테두리·접근성 그룹을 쓴다.
- 커뮤니티 신고 수는 공식 재고 수를 바꾸지 않는다.
- 활성 신고가 없다는 사실로 `정상`, `안전`, `고장 없음`을 표시하지 않는다.
- 커뮤니티 신고가 여러 건이어도 `고장 확정`으로 승격하지 않는다.
- `official_maintenance_state`는 운영기관 또는 승인된 연동 이벤트만 변경할 수 있다.
- 화면 전체를 대표하는 단일 `이용가능/고장` 배지는 만들지 않는다.

---

## 8. 최소 데이터 계약

기계 계약의 단일 출처는 [`contracts/openapi.yaml`](./contracts/openapi.yaml)이고, enum 표시명은 [`contracts/enums.json`](./contracts/enums.json)을 따른다. 아래 예시는 해커톤 live 기본 모드인 canonical `StationState` 한 건이다. 제품 문서만 보고 별도 응답 구조를 만들지 않는다.

```json
{
  "station_id": "ST0031",
  "name": "시청역 8번 출구",
  "address": "대전광역시 중구 중앙로 101",
  "lat": 36.3504,
  "lon": 127.3845,
  "walk_minutes": 4,
  "data_source": "live_datago",
  "inventory": {
    "bikes_available": 3,
    "observed_at": "2026-07-21T09:00:00+09:00"
  },
  "data_freshness": "fresh",
  "freshness_detail": {
    "observed_at": "2026-07-21T09:00:00+09:00",
    "collected_at": "2026-07-21T09:00:05+09:00",
    "observed_at_basis": "source_observed_at",
    "ingested_at": "2026-07-21T09:00:10+09:00",
    "age_seconds": 70,
    "stale_after_seconds": 600,
    "unavailable_after_seconds": 1800,
    "last_error_code": null
  },
  "decision_signal": {
    "mode": "current_stock",
    "stockout_probability": null,
    "stockout_risk_grade": null,
    "demand_pressure_grade": null,
    "prediction_basis": null,
    "context_status": "unavailable",
    "feature_contract_version": null,
    "calibration_version": null,
    "context_evidence": [],
    "generated_at": "2026-07-21T09:01:00+09:00",
    "valid_until": "2026-07-21T09:10:00+09:00",
    "model_version": "current-stock-v1"
  },
  "inventory_signal": "collecting",
  "inventory_signal_detail": {
    "signal_id": null,
    "evidence_codes": ["insufficient_history"],
    "disclaimer": "재고 정체 신호이며 개별 자전거 고장 확정이 아닙니다."
  },
  "community_report_state": "none",
  "community_report_summary": {
    "active_report_count": 0,
    "last_reported_at": null,
    "unverified": true
  },
  "official_maintenance_state": "unavailable",
  "official_maintenance_detail": {
    "verified": false,
    "updated_at": null,
    "source": null
  }
}
```

계약 규칙:

- `inventory=null`은 현재 공식 재고 결측이고 `inventory.bikes_available=0`은 유효한 0대다. 두 상태를 직렬화·UI·로그에서 구분한다.
- `data_freshness=fresh`이면 `inventory`는 반드시 non-null이다. 현재 재고 객체가 없는데 `fresh`로 표시하는 응답은 계약 오류다.
- `data_source`는 top-level `live_datago/live_direct/demo` 중 하나이며 `data_freshness`와 독립적으로 해석한다.
- UI는 서버의 `data_freshness`를 재계산하거나 덮어쓰지 않는다. `freshness_detail.age_seconds`, `stale_after_seconds`, `unavailable_after_seconds`는 설명·진단용 metadata다.
- `freshness_detail.observed_at`이 non-null이면 `observed_at_basis`도 non-null이어야 한다. `source_observed_at`은 원천 시각, `collected_at`은 우리 수집시각을 뜻한다.
- `observed_at_basis=collected_at`이면 `observed_at`과 `collected_at`은 같아야 한다. 성공 관측이 없는 `unavailable`에서는 `observed_at`, `collected_at`, `observed_at_basis`가 모두 null일 수 있다.
- `data_source=demo`이면 `data_freshness`와 관계없이 전 화면 워터마크를 표시하고 실제 이동·신고 CTA를 비활성화한다.
- `mode=stockout_risk`일 때만 `stockout_probability`와 `stockout_risk_grade`가 non-null이고, `mode=demand_pressure`일 때만 `demand_pressure_grade`가 non-null이다. 확률은 정확히 `P(parking_count(t+15분)<1)`이며 대여 성공·정상 자전거·고장 확률이 아니다.
- `mode=current_stock|demand_pressure|unavailable`에서는 `stockout_probability=null`이다. `current_stock|unavailable`에서는 두 grade도 모두 null이며 서로 다른 mode의 출력이 동시에 non-null이면 계약 오류로 처리한다.
- graded mode는 방향이 고정된 `grade_direction`과 경계의 `threshold_version`을 함께 가진다. 15분 horizon은 `ForecastResponse.eta_minutes=15`로 고정한다.
- L3 계약은 `prediction_basis`, `context_status`, feature contract·model·calibration·threshold version을 제공한다. `contextual_ml`은 실제 prediction provenance에서 고른 외부 맥락 근거 1~2개를, `inventory_temporal`은 fresh 공식 재고 근거 1~2개를 반환한다. L2 `demand_pressure`는 `prediction_basis=historical_demand`와 빈 근거 배열을 사용한다. graph·context snapshot 식별자는 내부 재현 로그에 남기며 공개 응답 필드는 OpenAPI를 따른다.
- 사용자 노출용 `context_evidence` 배열은 최대 2개이며 각 항목은 basis에 허용된 유형, 공개 출처, 발행 또는 갱신 시각, 모델에 반영된 방향을 가진다. 자유서술 원인과 raw attribution은 계약에 넣지 않는다.
- 공식 재고의 `data_source`·`data_freshness`와 맥락 source·freshness를 하나의 값으로 합치지 않는다. 필요한 맥락이 부분 결측이면 full-context 결과를 재사용하지 않는다.
- `data_freshness=fresh`에서는 `stockout_risk|current_stock`, `stale|unavailable`에서는 `demand_pressure|unavailable` mode만 허용한다.
- `stockout_risk_grade`의 `high`는 소진 위험이 높다는 뜻이고 `low`는 소진 위험이 낮다는 뜻이다. 가용성 등급으로 반전해 해석하지 않는다.
- `demand_pressure_grade`의 `high`는 과거 수요 압력이 높다는 뜻이다. 현재 소진 위험 또는 현재 재고 상태로 해석하지 않는다.
- `inventory_signal`은 재고 정체 신호일 뿐 고장 상태가 아니다. `inventory_signal_detail.disclaimer`를 함께 표시한다.
- `official_maintenance_state`는 운영기관 연동 전 `unavailable`이며 이때 detail은 `verified=false`, `updated_at=null`, `source=null`이다. 나머지 공식 상태는 인증된 source와 갱신시각이 있을 때만 허용하며 커뮤니티 신고·모델·시간 만료로 변경하지 않는다.
- `community_report_summary.unverified`는 항상 `true`다. `community_report_state`로 안전 category나 공식 확인을 추론하지 않는다.
- 신고 제출 API의 `category`는 canonical `report_category` 여섯 코드 중 하나여야 하며 알 수 없는 값은 `other`로 조용히 치환하지 않고 검증 오류로 반환한다.
- `bike_reference`는 최대 40자의 미검증 참조값이다. 개별 자전거 식별, 중복 이용자 판정, 공식 정비 상태 변경, 모델 정답에 사용하지 않는다.
- `corrected_count`, `actual_count`, `is_bike_usable`, `fault_cause` 필드는 만들지 않는다.
- 시간은 서버에서 ISO 8601로 전달하고 UI는 상대시간과 절대시간을 모두 접근 가능하게 제공한다.
- OpenAPI와 다른 필드가 필요하면 먼저 계약 버전·migration·mock을 갱신한다. 제품 문서만으로 필드를 추가하지 않는다.

### 8.1 분석 이벤트

최소 이벤트는 다음으로 제한한다.

| 이벤트 | 필수 속성 |
|---|---|
| `station_list_view` | decision_signal.mode, prediction_basis, context_status, data_source, fresh 정류장 수, 위치 사용 여부 |
| `station_detail_view` | station_id, data_source, data_freshness, decision_signal.mode, prediction_basis, context_status, context_evidence_kind 최대 2개, stockout_risk_grade, demand_pressure_grade |
| `alternative_route_click` | origin_station_id, destination_station_id, data_source, data_freshness, decision_signal.mode, prediction_basis, context_status, stockout_risk_grade, demand_pressure_grade, walk_minutes |
| `field_report_start` | station_id |
| `field_report_submit` | station_id, category, elapsed_seconds, online 여부 |
| `official_report_click` | station_id, category |
| `rental_outcome` | station_id, `success | unavailable | failed_unlock | skipped`, route 클릭 후 경과시간 |

정확한 사용자 위치, 원본 IP, 검색어, 이동경로, 행사명·자유서술 맥락, `description`, `bike_reference` 원문은 제품 분석 이벤트에 넣지 않는다. 분석에는 제한 enum인 맥락 유형과 version만 남기며 이를 사용자 프로필이나 모델 feature로 되돌려 쓰지 않는다.

---

## 9. 접근성 정량 Definition of Done

모든 항목을 통과해야 MVP 완료로 본다.

### 9.1 시각·레이아웃

- 일반 텍스트 대비는 최소 `4.5:1`, 큰 텍스트와 UI 경계·아이콘은 최소 `3:1`이다.
- 터치 대상은 최소 `44×44 CSS px`, 인접 대상 사이 간격은 최소 `8 CSS px`이다.
- 본문 기본 글자 크기는 최소 `16 CSS px`, 줄높이는 최소 `1.5`다.
- 브라우저 200% 확대에서 정보·기능 손실이 없고, 폭 `320 CSS px`에서 지도 외 가로 스크롤이 없다.
- 상태는 색만으로 구분하지 않고 텍스트와 아이콘을 함께 사용한다.
- `data_source=demo` 워터마크는 색·배경만이 아니라 `데모 데이터 · 실제 현재 정보가 아님` 텍스트로 항상 보인다.
- 시스템 `prefers-reduced-motion`에서 비필수 애니메이션을 제거한다.

### 9.2 키보드·보조기술

- 키보드만으로 검색, 정류장 선택, 대안 선택, 신고 제출, 재시도를 모두 수행할 수 있다.
- 포커스 표시선은 최소 `2 CSS px`, 주변 대비 `3:1`이며 화면에서 잘리지 않는다.
- 지도에 표시된 모든 정류장은 동일 순서·기능의 목록으로 접근 가능하다. 지도 조작이 핵심 과업의 필수 단계가 아니다.
- 정류장 행의 접근 가능한 이름에는 `정류장명, 예상 도보시간, 공식 재고, 조회 시각, 허용된 신호, 커뮤니티 신고`가 이 순서로 포함된다. 맥락 근거를 목록에 표시하는 경우 신호 뒤에 최대 두 개만 읽고 출처·시각은 상세 화면에서 확인할 수 있다고 알린다.
- 로딩, 지연, 제출 성공·실패는 `aria-live` 또는 플랫폼 동등 기능으로 한 번만 읽힌다.
- `data_source=demo`에서는 화면 제목 직후 워터마크를 한 번 읽고, 비활성화된 길찾기·신고 CTA에는 비활성 이유를 연결한다.
- 입력 오류는 해당 필드와 프로그램적으로 연결되고, 포커스가 첫 오류로 이동한다.
- 아이콘 버튼은 보이는 텍스트 또는 명확한 접근 가능한 이름을 갖는다.

### 9.3 권한·대체 경로

- 위치 권한 없이 주소·정류장 검색으로 전체 흐름을 완료할 수 있다.
- 카메라·GPS·사진은 해커톤 MVP 필수 권한이 아니다.
- 네트워크 오류 시 입력을 잃지 않으며, 실제 서버 접수 전에는 성공 상태를 알리지 않는다.
- 시간제한 상호작용과 자동으로 사라지는 핵심 알림을 사용하지 않는다.

### 9.4 검증 환경

- Android Chrome + TalkBack
- iOS Safari + VoiceOver
- Windows Chrome 키보드 전용
- 320 CSS px, 200% 확대
- 자동 검사에서 critical/serious 접근성 오류 0건
- 수동 검사에서 세 핵심 과업 성공률 100%

세 핵심 과업은 `정류장 선택`, `대안 길찾기 시작`, `현장 신고 제출`이다.

---

## 10. 제품 KPI

### 10.1 북극성 지표

**첫 시도 대여 성공률**

`대안 또는 선택 정류장 길찾기를 시작하고 도착 결과를 응답한 세션 중 “대여했어요” 비율`

이 지표는 자가응답 편향이 있으므로 독립 현장표본과 함께 해석한다. 응답 표본 수를 항상 병기하고 표본이 50건 미만이면 개선 효과를 대외 주장하지 않는다.

### 10.2 사용자 가치 지표

| 지표 | 정의 |
|---|---|
| 정류장 결정시간 | 첫 화면 표시부터 길찾기 클릭까지 중앙값·P90 |
| 대안 선택률 | 고위험 상세 조회 중 대안 길찾기를 선택한 비율 |
| 허탕 조우율 | 도착 결과 중 `unavailable/failed_unlock` 비율 |
| 맥락 상황 의사결정 개선 | 강수 예보·휴일·행사 전후·주변 급변 등 사전 정의한 맥락 slice에서 contextual ML과 current-stock·시간 버킷 대조 경험의 허탕 조우율·첫 시도 대여 성공률 차이 |
| 예측 이해율 | 사용자가 공식 재고·예측·커뮤니티를 정확히 구분한 비율 |
| 맥락 근거 이해율 | 사용자가 표시된 날씨·시간·휴일·행사·주변 흐름을 관측된 모델 입력으로 이해하고 재고 소진의 확정 원인으로 해석하지 않은 비율 |
| 신고 완료율 | 신고 시작 대비 성공 접수 비율 |
| 신고 완료시간 | 신고 시작부터 접수까지 중앙값·P90 |
| 공식 신고 전환율 | 커뮤니티 신고 완료 후 공식 신고 CTA 클릭 비율 |

### 10.3 데이터·모델 가드레일

모델·데이터 합격 임계값은 [`02_DATA_AND_EVALUATION.md`](./02_DATA_AND_EVALUATION.md) §7.1~7.8의 versioned `evaluation_gate`만을 단일 기준으로 사용한다. 해당 계약이 없으면 어느 prediction basis도 L3로 승인하지 않는다. 이 표는 제품이 반드시 관측할 지표와 불변 조건만 정의한다.

| 지표 | 제품 요구사항 |
|---|---|
| fresh 데이터 커버리지 | 서버의 canonical `data_freshness=fresh` 비율을 기록 |
| 최신성 | 서버의 `data_freshness` 분포와 `freshness_detail.age_seconds`를 기록 |
| point-in-time 맥락 커버리지 | 예측 시점에 유효한 날씨 예보·휴일·행사·graph·주변 재고 입력이 모두 provenance와 함께 준비된 L3 후보 비율을 맥락 유형별로 기록 |
| 기준선 대비 증분 성능 | 사전 선택된 contextual 후보가 current-stock/persistence, 동요일·시간 버킷, `inventory_temporal`보다 Brier·ECE·동일 coverage false-safe에서 개선되는지 기록. M1을 쓸 때는 투명한 B3 대비 추가 가치도 별도 기록 |
| 맥락 ablation | time/weather/holiday/event/spatial feature group을 제거했을 때의 성능·행동 변화와 held-out event·시간·공간 결과를 기록 |
| 저위험 오판율 | `stockout_risk_grade=low` 시 t+15분 재고가 1대 미만인 비율을 기록 |
| 고위험 정밀도 | `stockout_risk_grade=high` 시 t+15분 재고가 1대 미만인 비율을 기록 |
| 런타임 강등 성공 | stale 입력에서 L3 문구 노출 0건 |
| 맥락 강등 성공 | 필수 맥락 결측·지연·provenance 누락에서 full-context L3와 맥락 설명 노출 0건; 승인된 `inventory_temporal` 또는 L1로 결정적 강등 |
| 설명 충실성 | 노출된 근거가 실제 model input의 유형·방향·출처·시각과 일치하고 2개 이하이며 인과 문구·raw SHAP 노출 0건 |
| 공식 숫자 변조 | 신고·예측으로 `inventory.bikes_available`이 바뀐 사례 0건 |

### 10.4 운영기관 가치 지표

운영기관 협업 전에는 아래를 “추정 성과”로 발표하지 않고 검증 질문으로 취급한다.

- 운영자가 점검 우선순위를 정하는 데 걸리는 시간
- 제공 신호 중 실제 조치 대상으로 판단한 비율
- 중복 또는 조치 불가능 신고 비율
- 신고 인지부터 현장 확인까지 걸리는 시간
- 같은 커버리지를 확인하는 데 필요한 순회 거리·인시

---

## 11. 검증 게이트

### G0. 데이터·법적 사용 게이트 — 공개 전 필수

통과 조건:

- API 이용약관, 재배포, 출처 표기, 호출 한도를 원문 또는 운영기관 답변으로 보관한다.
- API 스키마·좌표·`parking_count` 의미를 표본 대조한다. 구체 데이터 합격 기준은 `02_DATA_AND_EVALUATION.md`를 따른다.
- 날씨 예보 archive, 공식 휴일 달력, 행사 일정·수정 이력, station graph의 이용조건·보존 가능성·발행/갱신 시각을 원문과 fixture로 확인한다.
- 실제 발행 이력을 확보하지 못한 맥락은 live 학습·평가·설명에서 제외하고 `data_source=demo` 시나리오로만 사용한다.
- 수집 시각과 원천 갱신 시각의 차이를 문서화한다.
- 실패·결측·0대가 서로 다른 테스트 케이스로 통과한다.
- 미통과 항목이 있으면 5장의 규칙과 `02_DATA_AND_EVALUATION.md`의 게이트에 따라 승인된 `inventory_temporal`, L1, 검증된 L2, L0 순의 허용 경로로 강등한다.

### G1. 사용자 문제·이해 게이트

대상 사용자 최소 10명에게 실제 또는 클릭 가능한 프로토타입으로 검증한다.

통과 조건:

- 8명 이상이 공식 재고, 상황 반영 15분 후 예측, 맥락 근거, 커뮤니티 신고의 출처 차이를 정확히 설명한다.
- 10명 중 0명이 날씨·휴일·행사·주변 흐름을 재고 소진의 확정 원인으로 해석하거나 raw 모델 수치를 요구 정보로 인식한다.
- 10명 중 0명이 `stockout_risk_grade=low`를 대여 보장 또는 정상 자전거 확인으로 해석한다.
- 9명 이상이 도움 없이 대안 정류장 길찾기를 시작한다.
- 정류장 결정시간 중앙값 30초 이하이다.
- 현장 신고 완료시간 중앙값 20초 이하, 완료율 80% 이상이다.
- 안전 문제 선택 시 10명 전원이 “타지 말고 공식 신고해야 함”을 이해한다.

실패 시 문구와 IA를 수정하고 다시 검증한다. 모델을 고도화해 이해 문제를 해결하려 하지 않는다.

### G2. contextual ML 재고 예측 게이트

`02_DATA_AND_EVALUATION.md` §7.1~7.8의 point-in-time join, 기준선 비교, 맥락별 calibration·false-safe, feature-group ablation, held-out event·시간·공간 조건을 모두 통과해야 live 데이터에 `prediction_basis=contextual_ml`과 `상황 반영` 문구를 사용할 수 있다. 실제 archived context가 없거나 사전 선택된 contextual 후보가 current-stock·시간 버킷·`inventory_temporal`보다 개선되지 않으면, fresh snapshot에서는 별도 승인된 `inventory_temporal` L3와 `재고·시간 기반` 문구, 이어서 L1 `타슈 공식 재고`로 강등한다. B3가 통과하고 M1이 B3를 이기지 못하면 B3를 contextual 후보로 유지한다. snapshot이 stale/unavailable이면 검증된 L2 `과거 같은 시간대 수요 압력`, 아니면 L0로 내린다. 해커톤에서는 live L3를 활성화하지 않는다.

### G3. 소규모 사용자 파일럿 게이트

권장 범위는 고수요 정류장 10~20개, 최소 1주다. 이 기간은 사용자 흐름과 안전 문제를 찾는 제품 파일럿이며 드문 휴일·행사·날씨 상황의 ML 성능 주장 근거가 아니다.

통과 조건:

- 길찾기 후 도착 결과 응답 50건 이상 확보
- 공식 재고만 보여주는 대조 경험과 비교 가능한 표본 확보
- 첫 시도 대여 성공률이 대조 경험보다 10%p 이상 높거나 허탕 조우율이 유의하게 낮음
- 개인정보·안전·오인 관련 중대 이슈 0건
- stale 상태에서 잘못된 예측 노출 0건
- 맥락 근거가 2개를 넘거나 출처·시각 없이 노출된 사례 0건, 인과 표현·raw SHAP 노출 0건

표본이나 대조군이 부족하면 결과를 학습 자료로만 사용하고 성과 주장과 기능 확대를 보류한다.

### G4. 운영기관 검증 게이트

정비·관제·민원 업무 관계자 최소 3명과 현재 워크플로를 검토한다.

통과 조건:

- 3명 중 2명 이상이 20개 샘플 신호 중 조치 가능한 항목과 이유를 일관되게 구분한다.
- 공식 신고 연결 경로와 명칭을 운영기관 또는 공개된 공식 안내로 확인한다.
- 커뮤니티 신고를 공식 티켓으로 오인하지 않는 데이터·화면 분리를 승인받는다.
- 기관이 원하는 최소 필드, 보존기간, 전달 방식, 응답 SLA를 문서화한다.

G4 통과 전에는 정비사 배정, 공식 처리 상태, 해결시간 KPI를 제품에 넣지 않는다.

---

## 12. 구현 순서

1. **데이터 어댑터와 강등 상태**: L0/L1을 먼저 완성하고 결측·지연 테스트를 작성한다.
2. **화면 1 목록**: 공식 재고와 조회 시각만으로 완전한 탐색 흐름을 만든다.
3. **화면 2 대안**: 길찾기와 후보 정렬을 구현한다.
4. **맥락 source와 point-in-time fixture**: 날씨 예보·휴일·행사·station graph·주변 재고의 provenance, 발행/갱신 시각, 결측·수정·취소 반례를 고정한다.
5. **기준선과 contextual ML**: current-stock/persistence, 시간 버킷, `inventory_temporal`, 투명한 맥락 B3와 비선형 M1을 같은 split에서 비교한다. B3를 기본 contextual 후보로 두고 M1은 B3 대비 추가 가치가 있을 때만 선택한다.
6. **L2 및 데모 신호 슬롯**: 서버 계약과 기능 플래그를 연결한다. live 기본값은 L1이며 live L3 플래그는 해커톤에서 끈다. archived context가 없으면 contextual L3 전체를 demo로만 재생한다.
7. **상황 근거와 fallback**: 최대 두 근거의 출처·시각·방향 검증, 맥락 결측 시 승인된 `inventory_temporal`→L1 강등, snapshot 지연 시 L2/L0 강등, basis별 template 설명을 구현한다.
8. **화면 3 신고**: 사진·QR 없이 유형 선택과 공식 신고 연결을 구현한다.
9. **분석 이벤트**: KPI에 필요한 제한 enum·version만 추가하고 위치·검색어·신고 원문이 feature로 되돌아가지 않게 한다.
10. **접근성 DoD**: 세 환경의 수동 테스트와 자동 검사를 통과한다.
11. **사용자 테스트**: G1 결과에 따라 문구·순서를 수정한다.

---

## 13. 출시 체크리스트

- [ ] 핵심 JTBD와 무관한 화면이 없다.
- [ ] 공식 재고, 예측, 커뮤니티 정보가 시각적·의미적으로 분리돼 있다.
- [ ] 공식 재고를 수정한 숫자나 `실제 이용가능 대수`가 없다.
- [ ] 예측이 고장·원인·개별 자전거 상태를 말하지 않는다.
- [ ] contextual ML의 모든 입력이 예측 시점에 이용 가능했고 source·발행/갱신 시각·version으로 재현된다.
- [ ] 맥락 근거는 최대 두 개이고 실제 model input과 일치하며 인과 표현·raw SHAP 값이 없다.
- [ ] 사용자 위치·검색어·이동경로·커뮤니티 신고가 모델 feature와 정답에 없다.
- [ ] 실제 archived context가 없는 날씨·행사 시나리오는 demo 표식 아래에만 있고 live 성능·현재 상황처럼 발표되지 않는다.
- [ ] 데이터 지연 시 기능명과 문구가 자동 강등된다.
- [ ] 필수 맥락 결측·지연 시 contextual L3와 상황 근거가 숨겨지고 승인된 `inventory_temporal` 또는 L1로 강등되며, stale/unavailable snapshot은 L2/L0 정책을 따른다.
- [ ] 모든 공식 재고에 출처와 조회 시각이 있다.
- [ ] 대안이 없을 때 오래된 데이터를 추천하지 않는다.
- [ ] 커뮤니티 신고 완료와 공식 신고 완료를 혼동하지 않는다.
- [ ] 안전 신고에 탑승 중지와 공식 신고 CTA가 있다.
- [ ] 위치 권한 없이 세 화면의 핵심 과업을 완료할 수 있다.
- [ ] 접근성 정량 DoD를 모두 통과했다.
- [ ] KPI 이벤트에 원본 위치·IP·검색어·이동경로·자유 메모·행사명 원문이 없다.
- [ ] G0 결과와 현재 제품 모드가 문서화돼 있다.
