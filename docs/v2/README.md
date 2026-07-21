# 타슈캐스트 V2 문서 기준

> 상태: **현재 구현 기준(Canonical)**
> 버전: 2.2
> 기준일: 2026-07-21

이 폴더는 기존 기획·리서치에서 발견된 데이터 과장, 상태 혼합, LLM 의사결정, 보안 누락과 문서 드리프트를 보완한 단일 기준 문서 묶음이다. **처음에는 [`00_MASTER_PLAN.md`](./00_MASTER_PLAN.md)를 읽는다.** 이 문서가 실제 데이터 조사, 제품 가치, 모델 선택, 폴백, 구현 게이트를 잇는 단일 기획 진입점이며, 나머지 문서는 분야별 상세 계약이다. 기존 `docs/PLAN.md`, `docs/PLAN_AI.md`, `docs/TEAM_GUIDE.md`, `docs/research/`는 의사결정의 배경과 과거 초안으로 보존한다.

## 1. 한 줄 제품 정의

타슈캐스트는 **예측 시점에 확인 가능했던 공식 재고와 날씨 예보·시간·휴일·행사 일정·주변 정류장 흐름을 결합해 정확히 15분 뒤 공식 재고 소진 위험과 가까운 대안을 보여주고, 현장에서 확인한 이용 불가 경험은 별도의 커뮤니티 신호로 기록하는 비공식 의사결정 보조 서비스**다.

다음 표현은 검증 전까지 사용하지 않는다.

- 고장 자전거 자동 탐지
- 보정된 실제 이용 가능 대수
- 고장까지 반영한 정확한 이용 가능성
- 공식 정비 접수·처리 상태
- 과거 데이터로 검증된 15분 재고 예측
- 실제 발행 이력이 없는 날씨 예보·행사 일정을 사용한 live 상황 반영 예측
- `비 때문에 소진된다`, `행사 때문에 자전거가 없다`처럼 맥락 신호를 원인으로 확정하는 표현
- raw SHAP 값·feature weight를 사용자 설명처럼 노출하는 표현
- 사용자의 현재 위치·검색어·이동경로·커뮤니티 신고를 모델 입력 또는 정답으로 사용하는 기능

## 2. 문서 지도

| 문서 | 역할 | 변경 시 함께 확인할 것 |
|---|---|---|
| [00_MASTER_PLAN.md](./00_MASTER_PLAN.md) | 전체 기획 진입점 — 실제 데이터 진실, 제품·모델 결정, 단계·게이트 | 아래 모든 상세 문서와 `contracts/` |
| [01_PRODUCT_MVP.md](./01_PRODUCT_MVP.md) | 사용자 문제, MVP 범위, 화면, 제품 KPI | `contracts/enums.json`, OpenAPI 응답 |
| [02_DATA_AND_EVALUATION.md](./02_DATA_AND_EVALUATION.md) | 사실 대장, 데이터 검증 게이트, 모델 타깃·평가 | fixture, 모델/데이터 버전 |
| [03_ARCHITECTURE_SECURITY.md](./03_ARCHITECTURE_SECURITY.md) | 시스템 경계, 상태 축, 보안·개인정보, 운영 | `contracts/openapi.yaml`, invariants |
| [04_EXECUTION_ROADMAP.md](./04_EXECUTION_ROADMAP.md) | 해커톤 수직 슬라이스와 이후 승격 순서 | 모든 DoD와 차단 조건 |
| [05_OPERATING_MODEL.md](./05_OPERATING_MODEL.md) | 사람×AI 페어 3트랙 운영 — 분담, 지시 프로토콜, 검증, 페어 간 연결 | `contracts/` 전체, 게이트 판정 절차 |
| [contracts/openapi.yaml](./contracts/openapi.yaml) | HTTP API의 기계 판독 기준 | 프론트·백엔드·mock·계약 테스트 |
| [contracts/enums.json](./contracts/enums.json) | 코드값과 한국어 UI 라벨 | UI, DB, 분석 이벤트 |
| [contracts/invariants.md](./contracts/invariants.md) | 어떤 구현도 깨면 안 되는 불변 규칙 | 모든 PR |
| [prompts/README.md](./prompts/README.md) | 재현이 필요한 사람→AI 지시 기록 형식 | 계약 버전, 입력 문서, 검증 로그 |

### 권장 읽기 순서

1. `00_MASTER_PLAN.md`에서 전체 문제·데이터 현실·모델 ladder·실행 단계를 이해한다.
2. `contracts/invariants.md`, `contracts/openapi.yaml`, `contracts/enums.json`에서 구현이 지켜야 할 기계 계약을 확인한다.
3. 담당 분야에 따라 `01_PRODUCT_MVP.md` → `02_DATA_AND_EVALUATION.md` → `03_ARCHITECTURE_SECURITY.md` → `04_EXECUTION_ROADMAP.md`를 읽는다.
4. 사람×AI 작업 분담과 검토 절차가 필요하면 `05_OPERATING_MODEL.md`, 재현 가능한 지시 기록은 `prompts/README.md`를 따른다.

## 3. 권위 우선순위

충돌 시 다음 순서로 판단한다.

1. 관찰 사실은 보존된 원본, 승인 API 응답 fixture와 재현 가능한 테스트 결과
2. HTTP 필드·enum·불변조건은 `docs/v2/contracts/`의 기계 판독 계약
3. 제품·데이터·모델 의사결정은 `docs/v2/00_MASTER_PLAN.md`
4. 분야별 상세는 `docs/v2/01~05` 문서
5. 기존 `PLAN*`, `TEAM_GUIDE`, `research/R*`
6. 기존 `research/D*`, `V1` 초안

`prompts/`는 작업 재현을 위한 감사 기록이며 제품·계약 권위를 갖지 않는다.

실제 API 응답과 문서가 충돌하면 응답을 조용히 따라가지 않는다. fixture·스키마·영향 문서를 같은 변경으로 갱신하고 재검토한다.

## 4. 이번 개정의 핵심 결정

1. **제품 Core를 하나로 축소한다.** Core는 예측 시점까지 확인된 공식 재고와 시공간 맥락을 결합한 정확히 15분 뒤 공식 재고 소진 위험이다. 타깃과 horizon은 고정하며 자동 고장 판정은 MVP에서 사용자에게 노출하지 않는다.
2. **관측과 추론을 분리한다.** 원본 수량, 기준 시각, 예측 등급, 커뮤니티 신고, 공식 정비 상태는 서로 다른 필드와 UI로 표시한다.
3. **API 스키마 검증을 개발보다 앞에 둔다.** 재고 후보는 타슈 직접 API 15119663과 전국 공영자전거 통합 API 15126639이며, 승인된 `200` 응답과 동시 수집 대조 없이는 수량 의미·페이지네이션·갱신주기를 확정하지 않는다. 대전 타슈정보 15109253은 실제 Swagger에 현재 자전거 수가 없으므로 live 재고가 아니라 정적 대여소 metadata 후보로만 쓴다.
4. **맥락은 point-in-time 사실만 사용한다.** 날씨는 당시 발행돼 있던 예보, 행사는 당시 공개된 일정과 수정·취소 상태, 휴일은 당시 공표된 달력, 주변 흐름은 예측 시점까지의 공식 재고만 사용한다. 미래 실측값과 사후 수정 정보를 학습·평가 입력으로 섞지 않는다.
5. **평가 가능한 이름만 사용한다.** 사전 선택된 contextual 후보가 current-stock 유지, 동요일·시간 버킷과 재고·시간 이력 `inventory_temporal`을 이기고 맥락별 평가 게이트를 통과했을 때만 `상황 반영`을 붙인다. 투명한 맥락 모델 B3가 충분하면 B3를 쓰고, 복잡한 M1은 B3 대비 추가 가치가 있을 때만 쓴다. contextual 경로가 미달·오류이거나 필요한 맥락이 결측이면 fresh snapshot에서 별도 승인된 `inventory_temporal`, `current_stock` 순으로 강등하고, snapshot이 stale/unavailable이면 검증된 `historical_demand` 기반 `demand_pressure`, `unavailable` 순으로 강등한다.
6. **예측 ML과 생성형 LLM을 구분한다.** 등급·대안 순위·행동은 승인된 `contextual_ml` 또는 `inventory_temporal`과 결정적 policy가 정한다. `inventory_temporal`에는 외부 상황 반영 문구를 붙이지 않고 사용한 공식 재고 근거만 출처·시각과 함께 1~2개 표시한다. LLM은 이미 확정된 구조화 근거를 최대 두 개의 짧은 문장으로 표현할 수 있을 뿐 새 사실·원인·상태를 만들거나 raw SHAP 값을 노출하지 않는다.
7. **개인 입력을 모델에서 격리한다.** 사용자의 현재 위치는 도보시간과 대안 정렬 policy에만 사용한다. 위치·검색어·이동경로·커뮤니티 신고·자유 메모는 예측 feature나 모델 정답으로 사용하지 않는다.
8. **단일 상태머신을 폐기한다.** 예측, 재고 정체 신호, 커뮤니티 신고, 공식 정비, 데이터 최신성을 독립 축으로 관리한다. 맥락 가용성은 예측 근거 안에서 별도로 표시하고 공식 재고 최신성을 덮어쓰지 않는다.
9. **재고 출처와 실행 모드를 분리한다.** v2.2 `data_source`는 `direct_tashu|national_integrated|demo`로 공식 재고 원천을 정확히 식별하고, `response_mode=live|demo`는 전체 예측·추천을 실제 행동에 써도 되는지를 뜻한다. 전체 feature provenance에 합성 context가 하나라도 있으면 `uses_synthetic_context=true`, `response_mode=demo`다.
10. **익명은 무인증과 같지 않다.** 서버가 서명한 익명 세션, capability token, rate limit, idempotency와 삭제 정책을 적용한다.

## 5. 시작 전 필수 게이트

| 게이트 | 통과 증거 | 실패 시 결정 |
|---|---|---|
| G0 API 실응답 | 타슈 직접 15119663과 전국 통합 15126639의 마스킹된 `200` fixture, 7일 동시 수집의 필드·ID·수량·지연·페이지네이션 비교표 | live 기능을 demo fixture로 제한하고 15109253을 재고 source로 사용하지 않음 |
| G0-C 맥락 실증 | 날씨 예보 발행 이력, 휴일 달력, 행사 일정·수정 이력, 공간 graph의 출처·이용조건·수집시각·fixture | 해당 맥락을 live 입력에서 제외하고 실제 archive가 없으면 demo로만 시연 |
| G1 데이터 결합 | CSV와 station ID 매칭률, 맥락별 point-in-time join 성공률, 날짜 범위, 중복·결측·source revision 보고서 | 대상 정류장·맥락 축소 또는 데이터 정제 선행 |
| G2 예측 가능성 | 과거 station snapshot과 당시 이용 가능했던 맥락으로 수행한 시간·행사·공간 순서 평가, current-stock·시간 버킷·`inventory_temporal` 대비 contextual 증분 성능, B3 대비 M1의 복잡도 증분과 ablation | contextual 경로만 실패하면 승인된 `inventory_temporal`, 그것도 실패하고 snapshot이 fresh면 `current_stock`, snapshot이 stale/unavailable이면 검증된 `historical_demand` 기반 `demand_pressure`, 그마저 없으면 `unavailable` |
| G3 사용자 안전 | 공식/커뮤니티 상태 분리, 안전결함 안내, 취소·삭제 경로 테스트 | 공개 배포 금지 |
| G4 계약 정합성 | OpenAPI 검증, mock·서버·클라이언트 계약 테스트 | 통합 금지 |

## 6. 변경 절차

1. 변경 제안에 사용자 가치와 측정 가능한 완료 기준을 적는다.
2. 먼저 `contracts/`를 변경하고 하위 호환성을 확인한다.
3. 제품·데이터·아키텍처 문서를 같은 변경 묶음에서 갱신한다.
4. fixture, 계약 테스트, 접근성 테스트, 오프라인 데모를 통과시킨다.
5. 사실 수준이 바뀌면 근거와 확인 날짜를 남긴다.

문서 추가 자체는 완료가 아니다. **fixture 또는 테스트로 재현되지 않는 주장은 항상 가설이다.**
