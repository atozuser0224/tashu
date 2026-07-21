# 타슈 다중 기사 재배치 서버

Core 모델의 정류소별 `predicted_net_flow`를 받아 여러 기사에게 픽업·반납 동선을 배정하는 FastAPI 서버다. 양수 flow는 잉여, 음수 flow는 부족으로 해석한다. 실제 타슈 실시간 API의 `parking_count`가 있으면 반출 가능한 수량을 실제 재고로 제한하고, ML의 고장 의심 자전거와 정류소 안전 재고는 반출 대상에서 제외한다.

## 실행

```powershell
$env:TASHU_API_TOKEN="타슈 앱에서 발급받은 키"
$env:TMAP_APP_KEY="SK Open API에서 발급받은 TMAP 앱 키"
$env:AUTH_JWT_SECRET="충분히 긴 운영용 JWT 서명키"
$env:STATION_QR_ADMIN_KEY="QR 발급 관리자 키"
python -m uvicorn app.main:app --reload
```

- Swagger UI: `http://localhost:8000/docs`
- 테스트 패널: `http://localhost:8000/test-panel`
- 상태 확인: `GET /health`
- 공식 타슈 정류소 프록시: `GET /api/v1/tashu/stations`
- 재배치 계획: `POST /api/v1/rebalancing/plans`
- 기사 미션·리워드 API: 아래 "운영 미션과 리워드" 참고

요청 예시는 [`examples/plan_request.json`](examples/plan_request.json)에 있다. `live_stations`를 요청에 직접 넣으면 해당 스냅샷을 사용하고, 생략하면 `TASHU_API_TOKEN`으로 공식 API를 조회한다. 토큰 또는 공식 API가 없으면 예측값만으로 계획을 만들고 응답 `warnings`에 폴백 사실을 표시한다.

## 테스트 패널

`TEST_MODE=true`로 실행하면 `/test-panel`에서 과거 시점의 실제 코어 모델 추론부터 테스트폰 QR 수행까지 하나의 시나리오로 시험할 수 있다. 이 모드에서는 JWT 로그인, 관리자 QR 키, Play Integrity/App Attest 검증을 우회한다. 테스트 TMAP 키는 서버와 기사 앱에 기본 연결되어 별도 입력이 필요 없다.

패널에서 지원하는 작업:

- PR #1 커밋 `b3e9133726b5eee5ac3472f7282dcc5d5bb16f09`의 `Hosu/snapshot_engine.py`와 STGNN 가중치로 지원 날짜·회차 추론
- 선택 시점을 기준으로 지정 범위 안의 임의 기사 수, 이름, 거주지 위치를 seed 기반으로 생성
- 기사 거주지에서 가까운 회수지를 우선하는 기존 배차 엔진과 TMAP 차량 경로 실행
- TMAP 지도에서 기사별 출발·픽업·반납 위치, 전체 경로, 정차 순서와 도로 안내 확인
- 생성된 기사 한 명을 `RIDEGO-TEST-DEVICE-01` 테스트폰에 연결
- 관리자가 선택 기사를 다음 정차지 좌표로 강제 이동하고 기사 앱이 서버 도착 상태를 반영
- 현재 정차지에 필요한 대여소·자전거 QR을 실제 스캔 순서대로 한 장씩 표시
- 테스트폰 카메라로 픽업 자전거 QR, 반납 대여소 QR, 동일 자전거 QR을 실제 업무 API 순서로 처리

테스트 요청은 `X-Test-Role: admin|operator|driver`와 기사인 경우 `X-Test-Driver-Id` 헤더를 사용한다. 패널이 관리자 헤더를 자동으로 넣으므로 별도 로그인이 필요 없다. 기사 앱에는 테스트 메뉴나 가짜 스캔 버튼이 없으며, 관리자 패널이 발급한 SVG QR을 실제 카메라로 읽어야 정차가 완료된다. `TEST_MODE=false`이면 패널과 `/api/v1/test/*`는 404가 되고 기존 인증·기기 검증이 다시 적용된다.

핵심 테스트 API:

| 용도 | API |
|---|---|
| 코어 모델 상태·날짜 | `GET /api/v1/test/core-model/status` |
| 특정 날짜·회차 스냅샷 | `GET /api/v1/test/core-model/snapshot?date=2026-03-17&round_id=C` |
| 랜덤 기사 시나리오 생성 | `POST /api/v1/test/scenarios` |
| 현재 시나리오 복원 | `GET /api/v1/test/scenarios/current` |
| 테스트폰 기사 연결·조회 | `PUT/GET /api/v1/test/devices/{device_id}/assignment` |
| 기사 위치·도착 상태 | `GET /api/v1/test/drivers/{driver_id}/state` |
| 다음 정차지 강제 이동 | `POST /api/v1/test/scenarios/{scenario_id}/drivers/{driver_id}/move-next` |
| 현재 정차지 순차 QR | `GET /api/v1/test/scenarios/{scenario_id}/drivers/{driver_id}/qr-sequence` |

코어 런타임은 PR #1에서 가져온 학습 가중치와 필수 `processed/` 산출물만 사용한다. 코어 상태 API가 체크포인트를 실제로 로드해 검증하고 이후 요청에서 같은 모델을 재사용한다. 날짜별 존재하는 회차만 패널 선택지로 제공하며 D 회차는 해당 서비스일의 **다음 날 03:00**으로 해석한다. 필요한 Python 패키지는 `numpy`, `pandas`, `pyarrow`, `torch`이며 `pyproject.toml`에 선언되어 있다. wheel 빌드에도 `Hosu/processed` 모델 산출물과 관리자 패널이 포함된다.

PR 코어의 현재 데이터 한계도 API `limitations`와 패널에 그대로 노출한다. `available_bikes`는 실제 과거 재고가 아니라 매일 8대를 기준으로 관측 flow를 누적한 데모 복원값이고, 고장 의심 피처에는 전체 수집기간 집계값이 포함되어 과거 시점 성능평가에 사용할 수 없다. 따라서 현재 결과는 **실제 PR 모델을 이용한 시나리오·업무 흐름 검증용**이며, 실시간 전환이나 정확도 평가 전에는 시점별 실제 재고와 point-in-time 고장 피처로 교체해야 한다.

테스트 시나리오·휴대폰 배정·강제 이동 상태는 의도적으로 프로세스 메모리에만 유지하며 서버 재시작 시 테스트 DB와 함께 초기화된다. 따라서 `TEST_MODE=true`에서는 Uvicorn을 단일 worker로 실행한다. 운영 모드의 미션·리워드 데이터에는 이 제한이 없다.

## 프론트엔드 연동

응답에는 다음이 함께 들어간다.

- `routes[]`: 기사별 작업, 순서화된 `stops`, ETA/ETD, 구간 거리, 적재량 변화
- `routes[].first_pickup_*`: 기사 출발지에서 첫 잉여 대여소까지의 TMAP 거리·시간
- `routes[].navigation`: TMAP 차량 도로 경로의 총 거리·예상 시간·요금·길 안내 지점
- `map_data.routes[]`: 지도에 바로 그릴 수 있는 기사별 색상과 `lat/lng` 좌표 배열
- `map_data.markers[]`: 출발·픽업·반납 마커
- `map_data.bounds`: 지도 초기 viewport
- `unresolved[]`: 재고 부족 또는 근무시간 초과로 배정하지 못한 수량과 이유
- `data_sources`: 실시간 타슈 API 사용 여부와 거리 계산 방식
- `published_mission_ids`: 계획과 동시에 발행된 기사 미션 ID

기본 CORS 허용 주소는 `http://localhost:3000`, `http://localhost:5173`, Expo Web의 `http://localhost:8081`, `http://127.0.0.1:8081`이다. 운영 주소는 `FRONTEND_ORIGINS` 환경변수에 쉼표로 나열한다.

`TMAP_APP_KEY`가 설정되면 `map_data.routes[].coordinates`는 TMAP 도로 GeoJSON을 `lat/lng`로 정규화한 실제 차량 경로다. 픽업과 반납 순서를 보존하면서 도로별 회전 안내까지 받기 위해 자동차 경로안내 API의 고정 순서 `passList`를 사용한다. 한 요청의 최대 경유지 5개를 넘으면 여러 요청으로 나눈다. TMAP 장애나 키 미설정 시에만 Haversine 직선 미리보기로 폴백하며 `warnings`와 `data_sources.distance`로 구분할 수 있다.

운영 서버의 `TMAP_APP_KEY`는 요청 JSON에 넣지 않고 서버 환경변수 또는 배포 플랫폼의 Secret으로 주입한다. 단, React Native 테스트 앱에는 사용자 요청에 따라 테스트 키가 기본값으로 포함되어 있으며 운영 배포 전 교체하거나 제거해야 한다. 동일 경로 응답은 호출량 보호를 위해 메모리에 5분만 캐시하며 서버에 영구 저장하지 않는다.

## 운영 미션과 리워드

재배치 계획을 만들면 작업이 있는 기사별 미션이 SQLite에 자동 발행된다. 기사 앱은 `offered → accepted → in_progress → completed` 순서로 진행한다. 완료 리워드는 먼저 `pending` 원장에 들어가며 관리자 검증 후 `approved`, `rejected`, `reversed`로 변경된다. 같은 계획·정차·완료·오프라인 이벤트 재요청은 멱등 처리된다.

모든 업무 API에는 `Authorization: Bearer {access_token}`이 필요하다. 최초 1회 `POST /api/v1/auth/bootstrap`으로 관리자를 만든 뒤 로그인하고, 관리자가 `POST /api/v1/admin/users`로 기사와 배차 담당자를 생성한다. 기사 API는 body의 `driver_id`뿐 아니라 JWT의 기사 ID와 미션 배정 ID까지 서버에서 대조한다. Refresh Token은 한 번 갱신하면 이전 토큰을 폐기한다.

프론트 공개 API는 다음과 같다.

| 용도 | API |
|---|---|
| 앱 초기 데이터(미션+지갑) | `GET /api/v1/operations/bootstrap?driver_id=D-1` |
| 미션 목록/상태 필터 | `GET /api/v1/operations/missions?driver_id=D-1&status=offered` |
| 지도·내비게이션 포함 미션 상세 | `GET /api/v1/operations/missions/{mission_id}` |
| 대여소 QR 발급(관리자) | `POST /api/v1/admin/stations/{station_id}/qr` |
| 미션 수락 | `POST /api/v1/operations/missions/{mission_id}/accept` |
| 미션 시작 | `POST /api/v1/operations/missions/{mission_id}/start` |
| 반납 대여소 QR 인증 | `POST /api/v1/operations/missions/{mission_id}/stops/{sequence}/verify-qr` |
| 일회용 QR challenge | `POST /api/v1/operations/missions/{mission_id}/stops/{sequence}/qr-challenge` |
| 픽업/반납 GPS 완료 | `POST /api/v1/operations/missions/{mission_id}/stops/{sequence}/complete` |
| 명시적 최종 완료(멱등) | `POST /api/v1/operations/missions/{mission_id}/complete` |
| 포인트 지갑 | `GET /api/v1/rewards/wallets/{driver_id}` |
| 포인트 거래내역 | `GET /api/v1/rewards/wallets/{driver_id}/transactions` |
| 기사 리더보드 | `GET /api/v1/rewards/leaderboard?limit=20` |
| 기사 위치 heartbeat | `POST /api/v1/operations/drivers/me/location` |
| 기사 알림함 | `GET /api/v1/operations/notifications` |
| 오프라인 이벤트 동기화 | `POST /api/v1/operations/offline/sync` |

관리자·배차 화면 API도 제공한다.

| 용도 | API |
|---|---|
| 리워드 검토 목록 | `GET /api/v1/admin/rewards/reviews?status=pending` |
| 승인·거절·회수 | `POST /api/v1/admin/rewards/{transaction_id}/{approved|rejected|reversed}` |
| 사고 목록 | `GET /api/v1/admin/incidents` |
| 미션 취소·재배정 | `POST /api/v1/admin/missions/{id}/{cancel|reassign}` |
| 정차지 건너뛰기 | `POST /api/v1/admin/missions/{id}/stops/{sequence}/skip` |
| 실시간 기사 현황 | `GET /api/v1/admin/operations/live` |
| 운영 통계 | `GET /api/v1/admin/analytics/operations` |
| 감사로그 | `GET /api/v1/admin/audit-logs` |
| 정산 생성·지급 완료 | `POST /api/v1/admin/settlements`, `POST /api/v1/admin/settlements/{id}/paid` |
| 기존 계획 동적 교체 | `POST /api/v1/rebalancing/plans/{plan_id}/reoptimize` |

수락·시작·최종 완료 body는 `{"driver_id":"D-1"}`이다. 정차 완료 body는 다음 형식이다.

```json
{
  "driver_id": "D-1",
  "location": {"lat": 36.3665, "lng": 127.3445},
  "actual_quantity": 6,
  "bike_qr_codes": ["BIKE-QR-001", "BIKE-QR-002", "BIKE-QR-003", "BIKE-QR-004", "BIKE-QR-005", "BIKE-QR-006"],
  "evidence_photo_url": "https://example.com/evidence/stop-1.jpg"
}
```

서버는 배정 기사, 정차 순서, 계획 수량, 차량 적재량, 대여소와의 GPS 거리, 자전거 QR 수량을 검증한다. 기본 허용 반경은 200m다. 예상 포인트와 지급 포인트는 `estimated_reward`, `awarded_reward`에 기본·부족도·완주 보너스별로 내려간다.

### QR 반납 확인 흐름

1. 운영 관리자가 `X-Admin-Key` 헤더와 함께 QR 발급 API를 호출해 대여소별 서명 payload를 만들고 현장에 부착한다. 관리자 키는 기사 앱에 포함하지 않는다.
2. 픽업 정차 완료 시 기사는 적재한 자전거 QR을 모두 스캔한다. `actual_quantity`와 `bike_qr_codes` 개수가 같아야 한다.
3. 반납 대여소 도착 후 `qr-challenge`로 기사·미션·정차지·기기에 묶인 1회용 challenge를 받는다.
4. 현장 QR을 스캔해 `verify-qr` API에 challenge, 현재 GPS, QR payload, 기기 무결성 결과를 전송한다.
5. 서버는 challenge 재사용, QR 서명, 대여소 ID, 기사, 다음 정차 순서, GPS 반경과 기기 무결성을 검증한다.
6. 반납 완료 시 다시 자전거 QR 목록을 보낸다. 픽업 때 적재 원장에 등록된 QR만 반납 가능하고 동일 QR은 중복 처리할 수 없다.
7. 마지막 정차 완료 후 리워드는 검증 대기 상태가 되며 승인된 포인트만 지갑·리더보드·정산에 반영된다.

미션 상세의 정차지에는 `qr_verification`(`not_required`, `pending`, `verified`), `qr_verified_at`, `bike_qr_count`가 포함된다. QR 원문은 저장하지 않고 HMAC 해시와 짧은 토큰 지문만 저장한다.

기본 포인트 공식은 `실제 반납 대수 × 100 + round(실제 반납 대수 × 부족도 × 50) + 전체 계획 수량 완료 시 300`이다. 아래 환경변수로 운영 정책을 바꿀 수 있다.

- `TASHU_DB_PATH` (기본 `data/tashu.db`)
- `MISSION_GPS_RADIUS_METERS` (기본 `200`)
- `REWARD_POINTS_PER_BIKE` (기본 `100`)
- `REWARD_PRIORITY_POINTS_PER_BIKE` (기본 `50`)
- `REWARD_FULL_COMPLETION_BONUS_POINTS` (기본 `300`)
- `STATION_QR_ADMIN_KEY` (관리자 QR 발급 API 인증키, 운영 필수)
- `STATION_QR_SIGNING_SECRET` (고정 QR 서명키, 운영 권장)
- `STATION_QR_VERIFICATION_TTL_SECONDS` (기본 `600`)
- `QR_CHALLENGE_TTL_SECONDS` (기본 `120`)
- `AUTH_JWT_SECRET` (운영 필수, 생략 시 DB에 임의 생성)
- `AUTH_ACCESS_TTL_SECONDS` (기본 `900`)
- `AUTH_REFRESH_TTL_SECONDS` (기본 `2592000`)
- `REWARD_AUTO_APPROVE` (기본 `false`)
- `DEVICE_INTEGRITY_GATEWAY_SECRET` (Play Integrity/App Attest 검증 게이트웨이 서명키)
- `ALLOW_DEVELOPMENT_INTEGRITY` (기본 `false`, 테스트에서만 사용)

`STATION_QR_SIGNING_SECRET`을 생략하면 서버가 무작위 키를 생성해 SQLite 설정 테이블에 보존한다. DB를 교체해도 기존 인쇄 QR을 유지해야 하는 운영 환경에서는 반드시 고정 Secret을 주입한다.

Android Play Integrity와 iOS App Attest의 플랫폼 토큰은 별도 검증 게이트웨이가 검증한 뒤 `provider:device_id:challenge_id`에 대한 HMAC 결과를 이 서버에 전달한다. 외부 푸시 인증서가 없는 환경에서는 알림이 서버 알림함에 보존되며, FCM/APNs 발송기는 `notifications` 테이블을 outbox로 사용해 연결할 수 있다.

## 배차 방식

배차 전에 기사 출발지와 작업 대상 대여소를 TMAP 경로 매트릭스로 조회한다. 각 기사의 첫 작업은 출발지에서 잉여 대여소까지의 도로시간이 가장 짧은 조합을 우선 배정한다. 이후에는 부족도 구간, 자전거 1대당 추가 도로시간, 기사별 누적 작업시간 순으로 다음 작업을 선택한다. 첫 작업은 고정하고 나머지 `픽업→반납` 작업 블록은 TMAP 총시간이 줄어드는 교환과 부분 역순을 반복해 개선한다. API 실패 시에만 Haversine 예상시간으로 폴백한다.

PR 또는 git ref의 station master CSV로 E2E 테스트할 수 있다.

```powershell
$env:TMAP_APP_KEY="발급받은 키"
python -m scripts.run_csv_e2e --git-object origin/pr-1:docs/Hosu/station_master.csv
```

계획 발행부터 GPS 완료·리워드 지급까지 한 번에 검증하려면 다음처럼 실행한다.

```powershell
python -m scripts.run_csv_e2e --git-object origin/pr-1:docs/Hosu/station_master.csv --complete-missions --database-path :memory:
```

## 실제 타슈 데이터 매핑

공식 타슈 API 응답을 아래처럼 정규화한다.

| 공식 필드 | 서버/프론트 필드 |
|---|---|
| `id` | `station_id` |
| `name` | `station_name` |
| `x_pos` (위도) | `location.lat` |
| `y_pos` (경도) | `location.lng` |
| `parking_count` | `available_bikes` |
| `address` | `address` |

공식 API의 `x_pos`가 위도, `y_pos`가 경도라는 명세를 어댑터 한 곳에서 처리한다.
서버는 공식 API 호출량을 줄이기 위해 정류소 스냅샷을 60초간 메모리 캐시한다. 응답의 `data_sources.live_station_match_count`로 core의 정류소 ID가 실제 타슈 ID와 몇 곳 매칭됐는지 확인할 수 있다. 공식 필드 명세는 [타슈 Open API 안내](https://bike.tashu.or.kr/noticeDetail.do?seq=28), 과거 수요 검증용 대여 이력은 [공공데이터포털 타슈 대여이력](https://www.data.go.kr/data/15137219/fileData.do)을 기준으로 한다.

## 테스트

```powershell
python -m pytest
```
