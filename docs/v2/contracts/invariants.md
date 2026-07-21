# 타슈캐스트 불변 규칙

이 문서의 규칙은 구현 편의나 일정 때문에 완화할 수 없다. 변경에는 제품·데이터·개발 책임자의 명시적 승인과 회귀 테스트가 필요하다.

## 1. 데이터와 표현

1. API 원본 `parking_count`에서 추정 고장 대수를 빼지 않는다.
2. v2.2 재고 원천은 신뢰할 수 있는 원천 관측시각을 제공하지 않는다. 성공 관측은 `observed_at=collected_at`, `observed_at_basis=collected_at`으로 표시하고, 이를 원천 업데이트 시각처럼 표현하지 않는다.
3. `stale` 또는 `unavailable` 데이터로 예측·대안·정체 신호를 새로 산출하지 않는다.
4. 총량 무변화를 대여·반납 없음이나 고장의 증거로 표현하지 않는다.
5. capacity가 성공 응답에서 검증되기 전에는 점유율·만차·빈 거치대 수를 표시하지 않는다.
6. `response_mode=demo`인 데이터는 모든 화면에서 식별 가능한 워터마크를 가진다.
7. `data_source`는 `direct_tashu|national_integrated|demo` 중 실제 선택된 공식 재고 snapshot의 수집 경로 하나이며, `data_freshness`와 함께 공식 재고 관측 축을 이룬다. 날씨·달력·행사·공간 맥락 또는 응답 실행 모드를 이 필드에 덮어쓰거나 합성하지 않는다.
7-a. `direct_tashu`와 `national_integrated`는 독립 run으로 이중 수집한다. 서로 다른 원천의 행을 한 snapshot으로 혼합하거나, 한 원천에서 받은 값을 다른 `data_source`로 표시하지 않는다. 서빙 원천은 versioned 선택 정책으로 고르고 응답에 그대로 노출한다.
7-b. live 수집기는 원천별 호출 한도·페이지 크기·전체 페이지 완주·재시도 예산을 검증하는 rate/page gate를 통과해야 한다. 누락 페이지가 있는 cycle은 `partial`이며 완전한 정류장 집합처럼 승격하지 않는다.
8. 합성 맥락을 예측 feature에 하나라도 사용하면 전체 provenance에서 `uses_synthetic_context=true`, 응답 전체를 `response_mode=demo`로 강등하고 실제 이동 추천과 운영 성능 집계에서 제외한다. 선택된 evidence가 모두 실데이터여도 예외가 아니다.
9. 맥락 결측·지연을 `비 없음`, `행사 없음`, 숫자 `0`으로 대체하지 않는다. `context_status`를 낮추고 검증된 폴백 경로를 사용한다.
10. `data_source=demo`이면 `response_mode=demo`다. 반대로 live 공식 재고라도 합성 맥락을 사용하면 `data_source`는 원천값을 유지하고 `response_mode`만 demo가 된다.
11. StationList의 parent와 모든 station item, Forecast의 parent와 모든 alternative item은 같은 `response_mode`를 가져야 한다.

## 2. 상태와 결정 권한

1. 예측, 재고 정체 신호, 커뮤니티 신고, 공식 정비, 데이터 최신성은 별도 상태 축이다.
2. `normal`을 “확인된 정상”의 뜻으로 사용하지 않는다. 관측 가능한 표현은 “현재 특이 신호 없음”이다.
3. 반복된 익명 신고만으로 `official_maintenance_state=confirmed_fault`가 될 수 없다.
4. 인증된 운영기관 연동이 없으면 공식 정비 상태는 항상 `unavailable`이다. `unknown`은 연동은 확인됐지만 해당 상태값만 미확인일 때 사용한다.
5. LLM 출력은 등급, 상태 전이, 대안 선택, 안전 행동을 결정하지 않는다.
6. 안전 위험 신고에는 탑승 중지와 공식 신고 안내를 애플리케이션 규칙으로 즉시 제공한다.
7. `decision_signal.mode=stockout_risk`일 때만 `horizon_minutes=15`, `stockout_probability`와 `stockout_risk_grade`가 non-null이고, `mode=demand_pressure`는 `horizon_minutes=15`와 `demand_pressure_grade`만 가진다. `current_stock|unavailable`은 horizon과 probability를 null로 두며 서로 다른 mode의 출력을 동시에 채우지 않는다.
8. `community_report_state=corroborated`는 같은 정류장·같은 category가 유효기간 안에 분리된 signed 익명 세션에서 반복 제출됐다는 뜻일 뿐, 서로 다른 실제 사람이나 공식 사실을 증명하지 않는다.
9. `data_freshness=fresh`에서는 `stockout_risk|current_stock`, `stale|unavailable`에서는 `demand_pressure|unavailable` mode만 허용한다.
10. 공식 정비가 `unavailable`이면 `verified=false`, `updated_at/source=null`이고, 그 밖의 공식 상태는 인증된 non-null source와 갱신시각 및 `verified=true`를 가져야 한다.
11. `StationState`와 `ForecastResponse`가 `data_freshness=fresh`이면 `inventory`는 non-null `OfficialInventory`여야 한다. 값이 없으면 freshness를 `fresh`로 표시하지 않는다.
12. `prediction_basis=contextual_ml`은 `context_status=complete`이고 승인된 `feature_contract_version`, `model_version`, `calibration_version`, `threshold_version`이 모두 있을 때만 허용한다.
12-a. `stockout_probability`는 `mode=stockout_risk`에서만 `0..1`의 non-null 값이며 정확히 `P(parking_count(t+15분)<1)`을 뜻한다. 실제 대여 성공·정상 자전거·고장 확률로 이름을 바꾸지 않는다.
13. 예측 폴백 순서는 검증된 `contextual_ml` → 검증된 `inventory_temporal` → `current_stock` → snapshot이 없을 때 검증된 `historical_demand` → `unavailable`이다. `inventory_temporal`은 fresh 공식 재고 lag/rolling과 시간 특징만 쓰며 맥락 결측을 대체하지 않는다.
14. `current_stock|unavailable` mode에서는 `prediction_basis`, `feature_contract_version`, `calibration_version`을 null로 두며 예측을 수행한 것처럼 표현하지 않는다.
15. `context_evidence`는 최대 2개의 구조화 사실만 담고, `direction`은 모델 신호와의 연관 방향일 뿐 원인·인과관계로 표현하지 않는다.
16. `stockout_risk`는 `prediction_basis=contextual_ml|inventory_temporal`만, `demand_pressure`는 `prediction_basis=historical_demand`만 허용한다. historical demand는 context evidence가 없는 no-snapshot trip fallback이며 현재 재고나 contextual 예측으로 표현하지 않는다.
17. 모든 decision signal은 `uses_synthetic_context`를 필수로 가진다. stockout 이외 mode에서는 항상 false이고, evidence 중 하나라도 `synthetic=true`이면 stockout flag도 true여야 한다. false는 선택 evidence만 보고 정하지 않고 전체 feature provenance에서 계산한다.
18. contextual ML evidence는 `weather|calendar|event|neighbor|temporal`만 허용하고 `inventory`를 금지한다. inventory-temporal evidence는 `inventory`만 허용한다.
19. weather·calendar·event evidence는 non-null `issued_at`과 `valid_at`을, neighbor·temporal·inventory evidence는 `issued_at=null`과 기준·갱신시각인 `valid_at`을 가져야 한다.

## 3. LLM

1. Core는 LLM 없이 완전히 동작해야 한다.
2. LLM은 애플리케이션이 확정한 구조화 사실을 자연어로 표현하거나 자유 텍스트를 보조 분류할 수 있다.
3. 사용자가 이미 선택한 구조화 category를 LLM이 임의 변경하지 않는다.
4. LLM 생성문은 입력 필드 존재 여부뿐 아니라 숫자·고유명·행동의 실제 일치도까지 검증한다.
5. 검증 실패, timeout, refusal이면 재시도 폭주 없이 결정론적 템플릿으로 폴백한다.
6. 템플릿 문구를 “LLM 생성” 또는 “AI가 확인”으로 표시하지 않는다.

## 4. 평가

1. station 스냅샷 정답 없이 가용성 예측 정확도를 주장하지 않는다.
2. 학습·튜닝·평가 기간은 시간 순서로 분리한다.
3. 모델 입력으로 사용한 신고를 같은 알람의 독립 정답으로 재사용하지 않는다.
4. 정확도 하나만 사용하지 않고 Brier score, calibration, 의사결정 성공률과 가드레일을 함께 본다.
5. 기준선보다 개선되지 않은 모델은 배포하지 않는다.
6. 독립 현장 라벨이 없는 정체 신호는 섀도 모드에 머문다.
7. 학습·보정·평가·서빙 특징은 동일한 point-in-time 계약을 사용하며, 각 특징은 `available_at <= prediction_at`이어야 한다.
8. 과거 학습에는 예측 시점 당시 발행된 날씨 예보·행사 일정 version만 사용한다. 사후 실측 날씨, 실제 관객 수, 최종 취소 상태를 미래 특징으로 주입하지 않는다.
9. rolling 통계와 인접 정류장 특징은 `prediction_at` 이하의 관측만 사용하고, split 경계의 target horizon을 purge한다.
10. 사용자 `origin`·검색어·정밀 이동 위치와 커뮤니티 신고·자유 텍스트는 재고/수요 예측 특징 또는 독립 정답으로 사용하지 않는다.
11. 맥락 모델은 재고·시간 기준선보다 개선되고 보정 게이트를 통과해야 하며, 맥락 추가 이득이 없으면 `inventory_temporal`로 유지한다.
12. 원시 재고 관측은 원천 정책과 rate/page gate가 허용하면 1분 주기를 선호해 보존한다. 학습용 5분 grid는 각 grid 시각 이하의 최신 관측만 as-of 선택하고, 미래 관측·선형보간·원천 간 혼합으로 빈 구간을 채우지 않으며 선택된 원천과 `collected_at`을 보존한다.

## 5. 보안과 개인정보

1. 클라이언트가 임의의 `device_id`를 신뢰 경계 안으로 전달할 수 없다.
2. 익명 세션은 서버 서명 토큰으로 식별하고 원문 식별자는 로그에 남기지 않는다.
3. 쓰기 API는 rate limit과 idempotency를 적용한다.
4. 신고 상세·취소는 신고자 capability token 또는 운영자 권한으로만 허용한다.
5. 공개 응답에는 신고 자유 텍스트, 토큰, IP, 위치 정밀값을 포함하지 않는다.
6. 사진 기능 도입 전 EXIF 제거, 얼굴·번호판 처리, 보존기간, 삭제 경로를 구현한다.
7. 입력 길이, 허용 category, 콘텐츠 타입과 파일 크기를 서버에서 검증한다.
8. `bbox`, 주소 검색어, `origin` 등 정밀 위치를 드러내는 query string은 access log와 분석 이벤트에 원문으로 남기지 않는다.
9. 익명 signed session의 TTL은 발급 시각부터 최대 24시간이며, credential을 쓰는 CORS는 명시적 origin allowlist만 허용하고 `*`를 사용하지 않는다.
10. session·CSRF·capability 또는 신고자 전용 내용을 포함한 응답에는 `Cache-Control: no-store`를 적용한다.
11. 날씨·행사 등 외부 API key와 credential-bearing URL은 저장소, fixture, `context_evidence`, 로그·trace·오류 응답에 남기지 않는다.
12. point-in-time feature·prediction 로그에는 사용자 원점·검색어·정밀 이동 위치를 저장하지 않고 정류장 ID 또는 승인된 비식별 공간 셀만 사용한다.

## 6. UX와 접근성

1. 색만으로 상태를 전달하지 않는다.
2. 지도와 동일 정보를 제공하는 목록 뷰가 항상 존재한다.
3. 모든 조작은 키보드로 가능하고 포커스가 보인다.
4. 200% 확대에서 핵심 정보와 CTA가 손실되지 않는다.
5. 터치 대상은 최소 44×44 CSS px를 사용한다.
6. 오류·로딩·stale·empty·offline 상태는 스크린리더에 텍스트로 전달한다.

## 7. 계약과 변경

1. OpenAPI, enum, mock, 서버, 클라이언트는 같은 스키마 버전을 사용한다.
2. 계약 변경은 하위 호환 여부와 migration을 명시한다.
3. nullable 필드를 추가해도 의미가 불명확하면 배포하지 않는다.
4. 완료 주장은 자동 테스트 또는 재현 가능한 검수 기록을 동반한다.
5. `unavailable_after_seconds`는 항상 `stale_after_seconds`보다 커야 하며, 클라이언트는 서버의 `data_freshness` 값을 임의로 재분류하지 않는다.
6. `response_mode`, `prediction_basis`, `horizon_minutes`, `stockout_probability`, `context_status`, `feature_contract_version`, `calibration_version`, `context_evidence`, `uses_synthetic_context` 변경은 OpenAPI·enum·mock·서버·클라이언트와 model/feature manifest를 같은 변경 묶음에서 갱신한다.
7. v2.2의 `DataSource` 변경은 breaking change다. 구 enum을 묵시적으로 alias하지 않으며 producer·consumer·fixture를 함께 migration한다.
