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
- **회차 단위**: 서비스일을 4회차(A 07:00 / B 11:30 / C 16:00 / D 익일 03:00)로 나눠 재배치 시점마다 브리핑.
- **STGNN은 "수급 경향" 예측기**: 회차 net_flow는 본질적 변동성이 커서, 정밀 예측이 아니라
  대여소별·시간대별 평균 수급 경향을 예측한다. `predicted_net_flow`는 경향값으로 해석할 것.
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

# 2) 인접행렬: adjacency, node_index
python build_adjacency.py

# 3) 날씨: 회차별 집계
python weather.py

# 4) 텐서 격자 + 마스크
python build_tensor.py

# 5) 피처 + 대여소별 표준화 (X_node 15채널)
python build_tensor_stage2.py

# 6) 슬라이딩 윈도우 학습셋
python build_windows.py

# 7) STGNN 학습 -> a3tgcn_v2.pt
python train.py

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
- 필요한 `processed/` 파일: `adjacency.npy`, `node_index.csv`, `norm_stats.json`,
  `a3tgcn_v2.pt`, `X_node.npy`, `X_global.npy`, `flow_mean_n.npy`, `flow_std_n.npy`,
  `timeline.csv`, `station_master.csv`, `weather_rounds.parquet`, `bike_features.parquet`

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
| `model.py` | A3TGCN (순수 PyTorch, CPU/XPU 호환) |
| `train.py` | STGNN 학습 (Huber 손실, 마스크 적용) |
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
      "stgnn_prediction": { "predicted_net_flow": -0.9, "shortage_pressure": 0.04 } }
  ]
}
```
