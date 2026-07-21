# 타슈 진짜재고 — 데이터/모델 파이프라인 (ML·STGNN 파트)

충남대 인근 40개 대여소의 재배치 의사결정을 돕는 관제 대시보드의 데이터·모델 파트.
전처리 → 고장판별(규칙) → STGNN 수요예측 → 시점 기반 JSON 스냅샷까지 담당.

## 무엇을 내놓는가

`snapshot_engine.py`의 `compute_snapshot(date, round_id)`가 최종 산출물이다.
특정 시점(날짜+회차)을 받아, 그 시점 기준으로 계산한 대시보드용 JSON을 반환한다.
- `stations[]`: 대여소별 예측 수급·고장·날씨 (지도 히트맵용)
- `priority_bikes[]`: 고장/방치 의심 자전거 Top 10 (사이드바용)

이 JSON을 LLM(브리핑 생성)과 프론트(히트맵 렌더링)가 받아 쓴다.

## 핵심 설계 결정 (배경)

- **B2G 관제용**: 시민이 아니라 운영팀 대상. AI 예측 오차의 민원 리스크 회피.
- **회차 단위**: 하루를 4회차(A 07:00 / B 11:30 / C 16:00 / D 03:00)로 나눠 재배치 시점마다 브리핑.
- **STGNN은 3분류(부족/정상/과잉) 예측기**: 회차 net_flow 회귀는 본질적 변동성으로 한계가
  있어(체계적 실험으로 규명), 문제 정의에 맞는 분류로 전환. 재배치는 "남는 곳에서 걷어
  부족한 곳에 채우는" 양방향 작업이라 3분류가 필수. 클래스 가중치 p=0.3으로 편향 억제.
- **MTGNN(학습 인접행렬 + Dilated TCN)**: 방향 A3TGCN을 넘어, 노드 임베딩 유사도로
  인접행렬 자체를 학습하는 MTGNN 아키텍처 채택. 손으로 만든 OD 관계 외에 "숨은 수요
  유사성"(직접 왕래 없어도 시간 패턴 비슷한 대여소)을 데이터가 찾음. 정적 방향 그래프와
  결합해 두 정보원(물리적 이동 + 수요 유사성) 모두 활용. 균형정확도 +10.2%p 도약.
- **방향(비대칭) 인접행렬 + 양방향 GCN**: 출근/퇴근의 이동 방향 경향(어디서 어디로)을
  살리기 위해 대칭화를 제거하고 A(나감)/Aᵀ(들어옴) 양방향 전파. MTGNN에 정적 그래프로 결합.
- **고장판별은 규칙 기반 스코어**: 고장 정답 라벨이 없어 지도학습(LightGBM 등) 대신
  도메인 규칙(방치일수·이동거리0·짧은이용·저이용) 가중합으로 해석 가능한 스코어 산출.
- **데모/실시간 모드 공유**: 두 모드는 기준 시점(ref_time)만 다르고 계산 로직은 동일.
  실시간 API는 미확보 상태로, 현재는 과거 데이터 재생(데모)만 동작. 실시간은 추후 확장.
- **가용대수는 시연용 더미**: 실시간 재고 API가 없어 flow 예측과 정합되는 baseline 값 사용.

## 실행 순서 (사전 준비, 시연 전 1회)

원본 대여이력 CSV(20개월)와 기상청 날씨 CSV(대전)를 준비한 뒤:

```bash
# 0) (선택) 반경별 대여소 개수 확인해서 RADIUS 정하기
python scan_radius.py

# 1) 전처리: netflow, station_master, od_matrix
python preprocess.py

# 2) 인접행렬: 방향(비대칭) 행렬 - 이동 방향 경향 반영
python build_adjacency.py            # node_index + 대칭 행렬(호환용)
python build_adjacency_directed.py   # adjacency_directed.npy <- 모델이 쓰는 것

# 3) 날씨: 회차별 집계
python weather.py

# 4) 텐서 격자 + 마스크
python build_tensor.py

# 5) 피처 + 대여소별 표준화 (X_node 15채널)
python build_tensor_stage2.py

# 6) 슬라이딩 윈도우 학습셋
python build_windows.py

# 7) STGNN 분류 학습 (MTGNN: 학습 인접행렬 + Dilated TCN + 정적 방향 그래프) -> mtgnn.pt
python train_mtgnn.py

# 7-1) (선택) 혼동행렬로 치명적 오류율 확인
python eval_mtgnn.py

# 8) 자전거 단위 집계 미리 저장 (고장판별 속도 최적화)
python precompute_bikes.py
```

모든 산출물은 `processed/` 폴더에 저장된다.

## 경로 설정 (실행 전 수정 필요)

- `preprocess.py` 상단: `DATA_GLOB`(대여이력 CSV 경로), `CNU_LAT/LNG`, `RADIUS_KM=1.0`
- `weather.py` 하단: `load_weather('...weather*.csv')` 경로
- `precompute_bikes.py` 하단: `main('...대여이력*.csv')` 경로

인코딩(cp949/utf-8), 구분자(탭/콤마), 날짜 포맷은 자동 감지된다.

## 스냅샷 생성 / 저장

```bash
# 단일 회차 저장
python snapshot_engine.py 2026-03-17 C     -> processed/snapshot_2026-03-17_C.json

# 하루 전체(A/B/C/D) 시나리오 저장 (시연 재생용)
python snapshot_engine.py 2026-03-17       -> processed/scenario_2026-03-17.json
```

## 백엔드 연동 (FastAPI 담당에게)

`snapshot_engine.py`를 import해서 쓴다. 파일 저장 없이 JSON(dict)을 반환한다.

```python
from snapshot_engine import load_artifacts, compute_snapshot

# 서버 起動 시 1회: 모델·데이터를 메모리에 로드 (이후 요청서 재사용)
load_artifacts()

# 요청마다: 시점 받아 JSON 반환 (idle_days 재계산 + STGNN 추론, 1초 이내)
data = compute_snapshot(date="2026-03-17", round_id="C")   # 데모 모드
data = compute_snapshot(mode="realtime")                    # 실시간(현재는 폴백)
```

- **무거운 작업(전처리·학습)은 사전에 끝남.** 백엔드는 `processed/` 산출물만 있으면 된다.
- **起動 시 1회** `load_artifacts()` → 이후 요청은 가벼운 재계산만.
- 필요한 `processed/` 파일: `adjacency_directed.npy`, `node_index.csv`, `norm_stats.json`,
  `mtgnn.pt`, `X_node.npy`, `X_global.npy`, `flow_mean_n.npy`, `flow_std_n.npy`,
  `flow.npy`, `timeline.csv`, `station_master.csv`, `weather_rounds.parquet`, `bike_features.parquet`

## 파일 역할 요약

| 파일 | 역할 |
|---|---|
| `scan_radius.py` | 충남대 반경별 대여소 개수 스캔 (반경 결정용) |
| `preprocess.py` | 대여이력 → netflow/station_master/od_matrix |
| `build_adjacency.py` | OD → 정규화 인접행렬 A |
| `weather.py` | 기상청 시간별 → 회차별 날씨 |
| `build_tensor.py` | flow 격자 + 마스크 (신설 대여소·장애 마스킹) |
| `build_tensor_stage2.py` | 피처(추세·주기·거래량·요일·회차) + 대여소별 표준화 |
| `build_windows.py` | T=8 슬라이딩 윈도우 (train/test) |
| `model.py` | A3TGCN (회귀 회귀용, 초기 버전 - 참고용) |
| `model_cls.py` | A3TGCN 분류 버전 (대칭 그래프, 초기 분류 - 참고용) |
| `model_cls_directed.py` | A3TGCN 분류 + 양방향 GCN (방향 그래프용, 중간 버전 - 참고용) |
| `model_mtgnn.py` | **MTGNN (학습 인접행렬 + Dilated TCN) - 최종본 모델** |
| `train.py` | 회귀 학습 (Huber, 참고용) |
| `train_cls.py` | 분류 학습 대칭 (참고용) |
| `train_cls_directed.py` | 분류 학습 방향 (참고용) |
| `train_mtgnn.py` | **MTGNN 학습 - 최종본 사용** |
| `tune_weights.py` | 클래스 가중치 세기(p) 스윕 (튜닝 유틸) |
| `eval_confusion.py` / `eval_confusion_directed.py` / `eval_mtgnn.py` | 혼동행렬 분석 (각 모델별) |
| `precompute_bikes.py` | 자전거 단위 집계 저장 (고장판별 속도용) |
| `snapshot_engine.py` | **시점 → JSON 반환/저장 (최종 산출물)** |
| `util_check_lifespan.py` | (유틸) 대여소 신설/폐쇄 진단 |

## JSON 스키마 (compute_snapshot 반환)

```json
{
  "meta": { "date": "2026-03-17", "round_id": "C", "time": "16:00",
            "mode": "demo", "note": "predicted_net_flow는 수급 경향값" },
  "priority_bikes": [
    { "bike_id": "...", "station_id": "ST...", "idle_days": 23.5, "broken_score": 0.71 }
  ],
  "stations": [
    { "station_id": "ST...", "station_name": "...",
      "location": { "lat": 36.36, "lng": 127.34 },
      "current_weather": { "status": "약한 비", "precipitation_mm": 4.5, "temperature_c": 12.0 },
      "ml_correction": { "api_available": 7, "broken_suspected": 2, "real_available": 5 },
      "stgnn_prediction": {
        "class": "shortage",
        "probs": { "shortage": 0.62, "normal": 0.25, "surplus": 0.13 },
        "shortage_pressure": 0.62,
        "recommendation": {
          "action": "supply",
          "amount_hint": 4,
          "confidence": 0.62 } } }
  ]
}
```

`stgnn_prediction` 해석:
- `class`: 다음 회차 수급 예측 3분류 (shortage=부족 / normal=정상 / surplus=과잉) — 히트맵 3색
- `probs`: 클래스별 확률 — LLM 브리핑·불확실성 표시용
- `shortage_pressure`: 부족 확률(=probs.shortage) — 기존 프론트 호환 필드
- `recommendation`: 관제팀용 재배치 힌트 (정확한 정답 아님, 규모 참고값)
  - `action`: `collect`(걷어감) / `supply`(채움) / `hold`(유지)
  - `amount_hint`: 대략 몇 대 규모 (재구성 재고와 확률 결합, 리허설시 계수 조정 가능)
  - `confidence`: 예측 확률 최대값 — 얼마나 확신하는지

모델 성능 (test, 2026년 3월 홀드아웃, MTGNN + 방향 정적 그래프 결합):
- 균형정확도 **0.567** (무작위 0.333, 방향 A3TGCN 0.465 대비 +10.2%p 개선)
- 치명적 오류(부족<->과잉 혼동) **12.1%**
- 3-seed 재현성 확인 (평균 0.558, 표준편차 ±0.014)

확률 기반 보조지표로 설계, 최종 판단은 관제팀.