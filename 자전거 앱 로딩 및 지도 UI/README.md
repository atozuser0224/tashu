# RideGo 타슈 재배치 기사 앱

기존 단일 HTML 시제품을 Expo 57 + React Native + TypeScript 앱으로 교체한 프로젝트입니다. 로컬 FastAPI 서버의 코어 모델 JSON, 기사 분배 계획, TMAP 경로, 미션, GPS, QR, 리워드 API를 사용합니다.

## 제공 화면

- 로딩, 테스트 로그인, 기사 정보 입력
- 기사별 TMAP 내비게이션과 전체 정차 순서
- 코어 모델 JSON 입력·샘플 로드·기사별 계획 생성
- 실제 카메라 QR 스캔과 에뮬레이터용 테스트 QR
- 회수/배치 GPS 도착 확인과 대여소 QR challenge 검증
- 지갑, 포인트 거래, 설정, 앱 드로어

TMAP 지도만 공식 JavaScript SDK를 `react-native-webview` 안에서 실행합니다. 앱 화면, 상태, API 호출, QR 카메라는 모두 React Native입니다.

## 1. 로컬 서버 실행

저장소 루트에서 실행합니다.

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8765
```

실물 휴대전화로 테스트할 때는 Windows 방화벽에서 개발 네트워크의 8765 포트 접근이 가능해야 합니다. 테스트 모드 서버에서만 사용하세요.

## 2. 모바일 앱 설정

```powershell
Copy-Item .env.example .env
npm install
```

`.env`의 API 주소는 실행 환경에 맞춥니다.

- Android 에뮬레이터: `http://10.0.2.2:8765`
- iOS 시뮬레이터: `http://127.0.0.1:8765`
- 실물 휴대전화: `http://<개발 PC의 LAN IP>:8765`

사용자 요청에 따라 이 테스트 빌드에는 기본 TMAP 키가 포함되어 있습니다. `.env`의 `EXPO_PUBLIC_TMAP_APP_KEY` 또는 앱 설정 화면에서 다른 키로 덮어쓸 수 있습니다. 운영 배포 전에는 내장 테스트 키를 교체하거나 제거해야 합니다.

## 3. 실행

```powershell
npm start
```

Expo 메뉴에서 Android/iOS를 선택하거나 다음 명령을 사용할 수 있습니다.

```powershell
npm run android
npm run ios
```

앱에서 `테스트 기사로 바로 시작` → 기사 정보 확인 → 메뉴 → `코어 JSON 테스트` 순서로 이동합니다. 서버 샘플을 불러오거나 코어 모델 JSON을 붙여 넣고 계획을 만들면 `DRIVER-01` 미션이 즉시 발행됩니다.

같은 JSON 시나리오를 처음부터 다시 재생하려면 `미션·QR·리워드 테스트 상태 초기화`를 누른 뒤 계획을 다시 만드세요. 이 버튼은 테스트 서버의 미션·QR·지갑 데이터를 지웁니다.

## 테스트 미션 순서

1. 미션 수락
2. 운행 시작
3. 현재 정차의 `테스트 도착 · QR 확인`
4. 회수 정차에서는 자전거 QR을 수량만큼 확인
5. 배치 정차에서는 대여소 QR challenge를 검증하고 적재 자전거 QR을 배치
6. 마지막 정차 완료 후 리워드 거래와 지갑 확인

`내 실제 GPS로 도착 확인`은 현재 기기의 위치를 보내므로 테스트 대여소의 허용 반경 안에 있을 때만 성공합니다. `테스트 도착`은 JSON에 담긴 정차 좌표를 보내 API 흐름을 재현합니다.

## 검증 명령

로컬 서버가 `127.0.0.1:8765`에서 실행 중일 때:

```powershell
npm run typecheck
npm run doctor
npm run api-smoke
npx expo export --platform android --output-dir dist
```

`api-smoke`는 테스트 데이터를 초기화하고 새 코어 계획을 만든 뒤 `DRIVER-01` 미션의 수락, 시작, 모든 GPS/QR/정차 완료와 리워드 생성을 실제 HTTP로 검증합니다. 테스트 서버 데이터를 삭제·변경하므로 운영 서버에 실행하면 안 됩니다.

## 주요 구조

```text
App.tsx                         앱 진입·화면/설정 상태
src/screens/ScenarioLabScreen  코어 JSON·전체 기사 경로
src/screens/MissionNavigation  기사 운행·GPS·QR 상태 머신
src/components/TmapMissionMap  TMAP WebView 지도
src/components/QrScannerModal  카메라/테스트 QR
src/services/api.ts             FastAPI 강타입 클라이언트
src/types/api.ts                계획·미션·리워드 계약
scripts/smoke-mobile-api.ts     실제 API 종단 테스트
```

`screenshots/`와 `uploads/`는 기존 시제품의 디자인 참고 자료이며 앱 런타임에서는 사용하지 않습니다.
