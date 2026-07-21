from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import qrcode
from pydantic import ValidationError
from qrcode.image.svg import SvgPathImage

from app.auth import AuthError, AuthStore
from app.auth_models import (
    AuthPrincipal,
    AuthTokens,
    BootstrapAdminRequest,
    CreateUserRequest,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    UserResponse,
)
from app.core_model import (
    CoreModelAdapter,
    CoreModelError,
    CoreModelSnapshot,
    CoreModelStatus,
)
from app.models import (
    HealthResponse,
    PlanRequest,
    PlanResponse,
    TashuStationListResponse,
)
from app.operations import OperationError, OperationStore
from app.operations_models import (
    AuditLogResponse,
    BikeDamageReport,
    BikeDamageReportRequest,
    CancelMissionRequest,
    CompleteMissionStopRequest,
    CreateSettlementRequest,
    DriverLivePosition,
    DriverLocationRequest,
    DriverBootstrapResponse,
    LeaderboardResponse,
    LiveOperationsResponse,
    MissionActionRequest,
    MissionDetail,
    MissionIncident,
    MissionIncidentListResponse,
    MissionIncidentRequest,
    MissionListResponse,
    NotificationItem,
    NotificationListResponse,
    OfflineSyncItem,
    OfflineSyncRequest,
    OfflineSyncResponse,
    OperationsAnalytics,
    QrChallengeRequest,
    QrChallengeResponse,
    ReassignMissionRequest,
    RewardReviewRequest,
    RewardTransaction,
    RewardTransactionListResponse,
    RewardWallet,
    SettlementBatch,
    SkipStopRequest,
    StationQrProvisionResponse,
    TestStationQrResponse,
    VerifyStationQrRequest,
)
from app.planner import create_plan
from app.tashu import TashuApiError, TashuClient
from app.test_scenario import (
    CoreTestScenarioRequest,
    CreateTestScenarioRequest,
    TestDeviceAssignment,
    TestDeviceBindingRequest,
    TestForcedArrival,
    TestQrItem,
    TestQrSequence,
    TestScenarioResponse,
    TestScenarioRuntime,
    TestTmapConfig,
    TEST_TMAP_APP_KEY,
    build_scenario_plan_request,
    build_test_plan_request,
    create_sample_core_scenario,
)
from app.tmap import TmapApiError, TmapClient, enrich_plan_with_tmap
from app.travel import TravelNode, driver_node_id, station_node_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.tashu_client = TashuClient()
    app.state.tmap_client = TmapClient()
    app.state.test_tmap_client = TmapClient(app_key=TEST_TMAP_APP_KEY)
    app.state.core_model = CoreModelAdapter()
    app.state.test_scenarios = TestScenarioRuntime()
    app.state.scenario_creation_lock = asyncio.Lock()
    app.state.test_mode = os.getenv("TEST_MODE", "true").lower() == "true"
    database_path = os.getenv("TASHU_DB_PATH", "data/tashu.db")
    app.state.operation_store = OperationStore(database_path)
    app.state.auth_store = AuthStore(database_path)
    if app.state.test_mode:
        app.state.operation_store.reset_test_data()
    try:
        yield
    finally:
        app.state.auth_store.close()
        app.state.operation_store.close()


app = FastAPI(
    title="타슈 다중 기사 재배치 API",
    version="0.9.0",
    description=(
        "core ST-GNN 예측과 타슈 실시간 재고를 결합해 기사별 동선을 배정하고, "
        "기사 미션 수행과 포인트 리워드까지 관리합니다."
    ),
    lifespan=lifespan,
)

origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        (
            "http://localhost:3000,http://localhost:5173,"
            "http://localhost:8081,http://127.0.0.1:8081"
        ),
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_test_role: Annotated[str | None, Header()] = None,
    x_test_driver_id: Annotated[str | None, Header()] = None,
) -> AuthPrincipal:
    if app.state.test_mode:
        role = x_test_role or "admin"
        if role not in {"admin", "operator", "driver"}:
            raise HTTPException(status_code=422, detail="지원하지 않는 테스트 역할입니다.")
        if role == "driver" and not x_test_driver_id:
            raise HTTPException(status_code=422, detail="X-Test-Driver-Id가 필요합니다.")
        return AuthPrincipal(
            user_id=f"test-{role}-{x_test_driver_id or 'console'}",
            username=f"test-{role}",
            display_name="테스트 사용자",
            role=role,
            driver_id=x_test_driver_id if role == "driver" else None,
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer 인증 토큰이 필요합니다.")
    token = authorization.split(" ", 1)[1]
    try:
        return app.state.auth_store.authenticate(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def require_roles(*roles: str) -> Callable:
    def dependency(
        principal: AuthPrincipal = Depends(current_principal),
    ) -> AuthPrincipal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="이 작업을 수행할 권한이 없습니다.")
        return principal

    return dependency


AdminPrincipal = Annotated[AuthPrincipal, Depends(require_roles("admin"))]
OperatorPrincipal = Annotated[
    AuthPrincipal, Depends(require_roles("admin", "operator"))
]
DriverPrincipal = Annotated[AuthPrincipal, Depends(require_roles("driver"))]
AnyPrincipal = Annotated[AuthPrincipal, Depends(current_principal)]


@app.get("/test-panel", response_class=HTMLResponse, include_in_schema=False)
async def test_panel() -> HTMLResponse:
    _require_test_mode()
    panel_path = Path(__file__).with_name("test_panel.html")
    return HTMLResponse(
        panel_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/v1/test/status", tags=["test-mode"])
async def test_mode_status() -> dict:
    _require_test_mode()
    return {
        "test_mode": True,
        "authentication_bypassed": True,
        "external_calls_simulated": False,
        "tmap_mode": "real_external_api_with_distance_fallback",
        "core_model_mode": "pinned_pr_artifacts",
        "historical_inventory_mode": "synthetic_reconstruction",
        "panel_url": "/test-panel",
        "driver_app_url": os.getenv("TEST_DRIVER_APP_URL"),
    }


@app.post("/api/v1/test/reset", tags=["test-mode"])
async def reset_test_mode() -> dict:
    _require_test_mode()
    _operation_call(app.state.operation_store.reset_test_data)
    app.state.test_scenarios.reset()
    return {"reset": True}


@app.post(
    "/api/v1/test/demo/plan",
    response_model=PlanResponse,
    tags=["test-mode"],
)
async def create_test_plan() -> PlanResponse:
    _require_test_mode()
    payload_path = Path(__file__).parent.parent / "examples" / "plan_request.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["core"]["meta"]["demo_mode"] = True
    payload["options"].update(
        {
            "use_live_tashu": False,
            "use_tmap_planning_matrix": False,
            "use_tmap_navigation": False,
        }
    )
    principal = AuthPrincipal(
        user_id="test-admin-console",
        username="test-admin",
        display_name="테스트 관리자",
        role="admin",
    )
    return await plan_rebalancing(PlanRequest.model_validate(payload), principal)


@app.get(
    "/api/v1/test/core-scenarios/sample",
    response_model=CoreTestScenarioRequest,
    tags=["test-mode"],
)
async def get_sample_core_scenario(_: AdminPrincipal) -> CoreTestScenarioRequest:
    _require_test_mode()
    return create_sample_core_scenario()


@app.get(
    "/api/v1/test/tmap/config",
    response_model=TestTmapConfig,
    tags=["test-mode"],
)
async def get_test_tmap_config(_: AdminPrincipal) -> TestTmapConfig:
    _require_test_mode()
    app_key = app.state.test_tmap_client.app_key
    return TestTmapConfig(
        configured=bool(app_key),
        sdk_url=(
            "https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey="
            + quote(app_key, safe="")
            if app_key
            else None
        ),
    )


@app.get(
    "/api/v1/test/core-model/status",
    response_model=CoreModelStatus,
    tags=["test-mode"],
)
async def get_core_model_status(_: AdminPrincipal) -> CoreModelStatus:
    _require_test_mode()
    try:
        await asyncio.to_thread(app.state.core_model.load)
    except CoreModelError:
        pass
    return app.state.core_model.status()


@app.get(
    "/api/v1/test/core-model/snapshot",
    response_model=CoreModelSnapshot,
    tags=["test-mode"],
)
async def get_core_model_snapshot(
    _: AdminPrincipal,
    date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    round_id: str = Query(pattern=r"^[ABCDabcd]$"),
) -> CoreModelSnapshot:
    _require_test_mode()
    try:
        return await asyncio.to_thread(
            app.state.core_model.snapshot,
            date,
            round_id,
        )
    except CoreModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/test/scenarios",
    response_model=TestScenarioResponse,
    tags=["test-mode"],
)
async def create_test_scenario(
    request: CreateTestScenarioRequest,
    principal: AdminPrincipal,
) -> TestScenarioResponse:
    """Create one reproducible historical scenario and publish its missions."""

    _require_test_mode()
    resolved_core = None
    if request.core_model is not None:
        try:
            snapshot = await asyncio.to_thread(
                app.state.core_model.snapshot,
                request.core_model.date.isoformat(),
                request.core_model.round_id,
            )
        except CoreModelError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        resolved_core = snapshot.core
        # The selected core frame is the source of truth for the simulated time.
        request = request.model_copy(update={"assumed_at": snapshot.assumed_at})

    try:
        built = build_scenario_plan_request(request, resolved_core)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with app.state.scenario_creation_lock:
        _operation_call(app.state.operation_store.reset_test_data)
        app.state.test_scenarios.reset()
        plan = await plan_rebalancing(
            built.plan_request,
            principal,
            TEST_TMAP_APP_KEY,
        )
        scenario = TestScenarioResponse(
            scenario_id=f"scenario-{uuid.uuid4().hex[:12]}",
            assumed_at=request.assumed_at,
            random_seed=built.random_seed,
            created_at=datetime.now(timezone.utc),
            drivers=list(built.drivers),
            plan=plan,
        )
        scenario = app.state.test_scenarios.set_scenario(scenario)
        _initialize_test_driver_states(scenario)
        return scenario


@app.get(
    "/api/v1/test/scenarios/current",
    response_model=TestScenarioResponse,
    tags=["test-mode"],
)
async def get_current_test_scenario(_: AdminPrincipal) -> TestScenarioResponse:
    _require_test_mode()
    scenario = app.state.test_scenarios.get_scenario()
    if scenario is None:
        raise HTTPException(status_code=404, detail="활성 테스트 시나리오가 없습니다.")
    return scenario


@app.put(
    "/api/v1/test/devices/{device_id}/assignment",
    response_model=TestDeviceAssignment,
    tags=["test-mode"],
)
async def bind_test_device(
    device_id: str,
    request: TestDeviceBindingRequest,
    _: AdminPrincipal,
) -> TestDeviceAssignment:
    _require_test_mode()
    scenario = app.state.test_scenarios.get_scenario()
    if scenario is None:
        raise HTTPException(status_code=404, detail="활성 테스트 시나리오가 없습니다.")
    if _test_driver_mission(scenario, request.driver_id) is None:
        raise HTTPException(
            status_code=409,
            detail="배정 미션이 없는 대기 기사는 테스트폰에 연결할 수 없습니다.",
        )
    try:
        return app.state.test_scenarios.bind_device(
            device_id,
            scenario.scenario_id,
            request.driver_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/api/v1/test/devices/{device_id}/assignment",
    response_model=TestDeviceAssignment | None,
    tags=["test-mode"],
)
async def get_test_device_assignment(device_id: str) -> TestDeviceAssignment | None:
    _require_test_mode()
    return app.state.test_scenarios.get_assignment(device_id)


@app.get(
    "/api/v1/test/drivers/{driver_id}/state",
    response_model=TestForcedArrival,
    tags=["test-mode"],
)
async def get_test_driver_state(driver_id: str) -> TestForcedArrival:
    _require_test_mode()
    return _current_test_driver_state(driver_id)


@app.post(
    "/api/v1/test/scenarios/{scenario_id}/drivers/{driver_id}/move-next",
    response_model=TestForcedArrival,
    tags=["test-mode"],
)
async def force_test_driver_to_next_stop(
    scenario_id: str,
    driver_id: str,
    _: AdminPrincipal,
) -> TestForcedArrival:
    _require_test_mode()
    scenario = _require_test_scenario(scenario_id)
    mission = _test_driver_mission(scenario, driver_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="이 기사에게 배정된 미션이 없습니다.")
    store: OperationStore = app.state.operation_store
    if mission.status == "offered":
        mission = _operation_call(store.accept_mission, mission.mission_id, driver_id)
    if mission.status == "accepted":
        mission = _operation_call(store.start_mission, mission.mission_id, driver_id)
    next_stop = next((stop for stop in mission.stops if stop.status == "pending"), None)
    if next_stop is None:
        raise HTTPException(status_code=409, detail="이 미션에 남은 정차지가 없습니다.")
    now = datetime.now(timezone.utc)
    _operation_call(
        store.record_driver_location,
        driver_id,
        next_stop.location,
        now,
        3,
        0,
        f"test-admin-{driver_id}",
    )
    return app.state.test_scenarios.set_movement_state(
        scenario_id,
        driver_id,
        mission_id=mission.mission_id,
        mission_status=mission.status,
        current_location=next_stop.location,
        next_stop=next_stop,
        arrived=True,
    )


@app.get(
    "/api/v1/test/scenarios/{scenario_id}/drivers/{driver_id}/qr-sequence",
    response_model=TestQrSequence,
    tags=["test-mode"],
)
async def get_test_qr_sequence(
    scenario_id: str,
    driver_id: str,
    _: AdminPrincipal,
) -> TestQrSequence:
    _require_test_mode()
    scenario = _require_test_scenario(scenario_id)
    state = _current_test_driver_state(driver_id)
    if not state.arrived or state.next_stop is None or state.mission_id is None:
        raise HTTPException(
            status_code=409,
            detail="먼저 기사를 현재 정차지로 강제 이동하세요.",
        )
    cached = app.state.test_scenarios.get_qr_sequence(
        scenario_id,
        state.mission_id,
        state.next_stop.sequence,
    )
    if cached is not None:
        return cached
    mission = _operation_call(app.state.operation_store.get_mission, state.mission_id)
    sequence = _build_test_qr_sequence(scenario, mission, state.next_stop)
    return app.state.test_scenarios.cache_qr_sequence(sequence)


@app.post(
    "/api/v1/test/core-scenarios/plan",
    response_model=PlanResponse,
    tags=["test-mode"],
)
async def plan_test_core_scenario(
    request: CoreTestScenarioRequest,
    principal: AdminPrincipal,
    x_test_tmap_key: Annotated[
        str | None, Header(alias="X-Test-Tmap-Key")
    ] = None,
) -> PlanResponse:
    _require_test_mode()
    planning_request = build_test_plan_request(request)
    return await plan_rebalancing(
        planning_request,
        principal,
        x_test_tmap_key or TEST_TMAP_APP_KEY,
    )


@app.post(
    "/api/v1/test/stations/{station_id}/qr",
    response_model=TestStationQrResponse,
    tags=["test-mode"],
)
async def create_test_station_qr(
    station_id: str,
    _: AdminPrincipal,
) -> TestStationQrResponse:
    _require_test_mode()
    provisioned = _operation_call(
        app.state.operation_store.provision_station_qr, station_id, None
    )
    return TestStationQrResponse(
        station_id=station_id,
        qr_payload=provisioned.qr_payload,
        svg_data_url=_qr_svg_data_url(provisioned.qr_payload),
    )


@app.post(
    "/api/v1/auth/bootstrap",
    response_model=UserResponse,
    tags=["auth"],
)
async def bootstrap_admin(request: BootstrapAdminRequest) -> UserResponse:
    return _auth_call(
        app.state.auth_store.bootstrap_admin,
        request.username,
        request.password,
        request.display_name,
    )


@app.post("/api/v1/auth/login", response_model=AuthTokens, tags=["auth"])
async def login(request: LoginRequest) -> AuthTokens:
    return _auth_call(
        app.state.auth_store.login,
        request.username,
        request.password,
        request.device_id,
    )


@app.post("/api/v1/auth/refresh", response_model=AuthTokens, tags=["auth"])
async def refresh_token(request: RefreshTokenRequest) -> AuthTokens:
    return _auth_call(app.state.auth_store.refresh, request.refresh_token)


@app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
async def logout(request: LogoutRequest) -> None:
    _auth_call(app.state.auth_store.logout, request.refresh_token)


@app.get("/api/v1/auth/me", response_model=AuthPrincipal, tags=["auth"])
async def get_me(principal: AnyPrincipal) -> AuthPrincipal:
    return principal


@app.post(
    "/api/v1/admin/users",
    response_model=UserResponse,
    tags=["auth-admin"],
)
async def create_user(request: CreateUserRequest, _: AdminPrincipal) -> UserResponse:
    return _auth_call(app.state.auth_store.create_user, request)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse()


@app.get(
    "/api/v1/tashu/stations",
    response_model=TashuStationListResponse,
    tags=["tashu"],
)
async def list_tashu_stations(_: AnyPrincipal) -> TashuStationListResponse:
    client: TashuClient = app.state.tashu_client
    try:
        stations = await client.fetch_stations()
    except TashuApiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TashuStationListResponse(count=len(stations), stations=stations)


@app.post(
    "/api/v1/rebalancing/plans",
    response_model=PlanResponse,
    tags=["rebalancing"],
)
async def plan_rebalancing(
    request: PlanRequest,
    principal: OperatorPrincipal,
    x_test_tmap_key: Annotated[
        str | None, Header(alias="X-Test-Tmap-Key")
    ] = None,
) -> PlanResponse:
    warnings: list[str] = []
    if request.live_stations is not None:
        live_stations = request.live_stations
        source = "provided_tashu_snapshot"
    elif request.options.use_live_tashu:
        client: TashuClient = app.state.tashu_client
        try:
            live_stations = await client.fetch_stations()
            source = "official_tashu_openapi"
        except TashuApiError as exc:
            live_stations = None
            source = "prediction_only"
            warnings.append(f"타슈 실시간 API 폴백: {exc}")
    else:
        live_stations = None
        source = "prediction_only"

    tmap_client: TmapClient = app.state.tmap_client
    if app.state.test_mode and x_test_tmap_key:
        tmap_client = (
            app.state.test_tmap_client
            if x_test_tmap_key == TEST_TMAP_APP_KEY
            else TmapClient(app_key=x_test_tmap_key)
        )
    travel_matrix = None
    if request.options.use_tmap_planning_matrix:
        if tmap_client.configured:
            live_by_id = {
                station.station_id: station for station in live_stations or []
            }
            nodes = [
                TravelNode(
                    node_id=driver_node_id(driver.driver_id),
                    location=driver.start_location,
                )
                for driver in request.drivers
            ]
            nodes.extend(
                TravelNode(
                    node_id=station_node_id(station.station_id),
                    location=(
                        live_by_id[station.station_id].location
                        if station.station_id in live_by_id
                        else station.location
                    ),
                )
                for station in request.core.stations
                if station.stgnn.predicted_net_flow != 0
            )
            try:
                travel_matrix = await tmap_client.travel_time_matrix(nodes)
            except TmapApiError as exc:
                warnings.append(f"TMAP 배차 시간행렬 폴백: {exc}")
        else:
            warnings.append(
                "TMAP_APP_KEY가 없어 배차에는 직선거리 예상시간을 사용했습니다."
            )

    plan = create_plan(
        request,
        live_stations,
        source,
        warnings,
        travel_matrix=travel_matrix,
    )
    if request.options.use_tmap_navigation:
        plan = await enrich_plan_with_tmap(
            plan,
            tmap_client,
            request.options.service_minutes_per_stop,
        )
    store: OperationStore = app.state.operation_store
    plan.published_mission_ids = store.publish_plan(plan)
    store.record_audit(
        principal.user_id,
        principal.role,
        "plan.publish",
        "plan",
        plan.plan_id,
        {"mission_ids": plan.published_mission_ids},
    )
    return plan


@app.post(
    "/api/v1/rebalancing/plans/{plan_id}/reoptimize",
    response_model=PlanResponse,
    tags=["rebalancing"],
)
async def reoptimize_plan(
    plan_id: str,
    request: PlanRequest,
    principal: OperatorPrincipal,
) -> PlanResponse:
    new_plan = await plan_rebalancing(request, principal)
    replaced = _operation_call(
        app.state.operation_store.supersede_plan, plan_id, new_plan.plan_id
    )
    new_plan.warnings.append(f"기존 계획의 미션 {replaced}개를 새 계획으로 대체했습니다.")
    _audit(
        principal,
        "plan.reoptimize",
        "plan",
        plan_id,
        {"new_plan_id": new_plan.plan_id, "replaced_missions": replaced},
    )
    return new_plan


@app.get(
    "/api/v1/operations/missions",
    response_model=MissionListResponse,
    tags=["operations"],
)
async def list_missions(
    principal: AnyPrincipal,
    driver_id: str | None = None,
    status: str | None = None,
) -> MissionListResponse:
    if principal.role == "driver":
        if driver_id and driver_id != principal.driver_id:
            raise HTTPException(status_code=403, detail="다른 기사의 미션을 조회할 수 없습니다.")
        driver_id = principal.driver_id
    return _operation_call(
        app.state.operation_store.list_missions,
        driver_id=driver_id,
        status=status,
    )


@app.get(
    "/api/v1/operations/missions/{mission_id}",
    response_model=MissionDetail,
    tags=["operations"],
)
async def get_mission(mission_id: str, principal: AnyPrincipal) -> MissionDetail:
    mission = _operation_call(app.state.operation_store.get_mission, mission_id)
    _authorize_mission(principal, mission.driver_id)
    return mission


@app.post(
    "/api/v1/admin/stations/{station_id}/qr",
    response_model=StationQrProvisionResponse,
    tags=["operations-admin"],
)
async def provision_station_qr(
    station_id: str,
    principal: AdminPrincipal,
    x_admin_key: str | None = Header(default=None),
) -> StationQrProvisionResponse:
    return _operation_call(
        app.state.operation_store.provision_station_qr,
        station_id,
        x_admin_key,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/accept",
    response_model=MissionDetail,
    tags=["operations"],
)
async def accept_mission(
    mission_id: str, request: MissionActionRequest, principal: DriverPrincipal
) -> MissionDetail:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.accept_mission,
        mission_id,
        request.driver_id,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/start",
    response_model=MissionDetail,
    tags=["operations"],
)
async def start_mission(
    mission_id: str, request: MissionActionRequest, principal: DriverPrincipal
) -> MissionDetail:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.start_mission,
        mission_id,
        request.driver_id,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/stops/{sequence}/complete",
    response_model=MissionDetail,
    tags=["operations"],
)
async def complete_mission_stop(
    mission_id: str,
    sequence: int,
    request: CompleteMissionStopRequest,
    principal: DriverPrincipal,
) -> MissionDetail:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.complete_stop,
        mission_id,
        sequence,
        request.driver_id,
        request.location,
        request.actual_quantity,
        request.bike_qr_codes,
        request.evidence_photo_url,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/stops/{sequence}/qr-challenge",
    response_model=QrChallengeResponse,
    tags=["operations"],
)
async def issue_mission_qr_challenge(
    mission_id: str,
    sequence: int,
    request: QrChallengeRequest,
    principal: DriverPrincipal,
) -> QrChallengeResponse:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.issue_qr_challenge,
        mission_id,
        sequence,
        request.driver_id,
        request.device_id,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/stops/{sequence}/verify-qr",
    response_model=MissionDetail,
    tags=["operations"],
)
async def verify_mission_stop_qr(
    mission_id: str,
    sequence: int,
    request: VerifyStationQrRequest,
    principal: DriverPrincipal,
) -> MissionDetail:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.verify_station_qr,
        mission_id,
        sequence,
        request.driver_id,
        request.location,
        request.qr_payload,
        request.challenge_id,
        request.device_id,
        request.integrity_provider,
        request.integrity_token,
    )


@app.post(
    "/api/v1/operations/missions/{mission_id}/complete",
    response_model=MissionDetail,
    tags=["operations"],
)
async def complete_mission(
    mission_id: str, request: MissionActionRequest, principal: DriverPrincipal
) -> MissionDetail:
    _authorize_driver_action(principal, request.driver_id)
    return _operation_call(
        app.state.operation_store.complete_mission,
        mission_id,
        request.driver_id,
    )


@app.get(
    "/api/v1/operations/bootstrap",
    response_model=DriverBootstrapResponse,
    tags=["operations"],
)
async def driver_bootstrap(
    driver_id: str, principal: AnyPrincipal
) -> DriverBootstrapResponse:
    _authorize_mission(principal, driver_id)
    return _operation_call(app.state.operation_store.bootstrap, driver_id)


@app.get(
    "/api/v1/rewards/wallets/{driver_id}",
    response_model=RewardWallet,
    tags=["rewards"],
)
async def get_reward_wallet(driver_id: str, principal: AnyPrincipal) -> RewardWallet:
    _authorize_mission(principal, driver_id)
    return _operation_call(app.state.operation_store.get_wallet, driver_id)


@app.get(
    "/api/v1/rewards/wallets/{driver_id}/transactions",
    response_model=RewardTransactionListResponse,
    tags=["rewards"],
)
async def list_reward_transactions(
    driver_id: str,
    principal: AnyPrincipal,
) -> RewardTransactionListResponse:
    _authorize_mission(principal, driver_id)
    return _operation_call(
        app.state.operation_store.list_transactions,
        driver_id,
    )


@app.get(
    "/api/v1/rewards/leaderboard",
    response_model=LeaderboardResponse,
    tags=["rewards"],
)
async def reward_leaderboard(
    _: AnyPrincipal,
    limit: int = Query(default=20, ge=1, le=100),
) -> LeaderboardResponse:
    return _operation_call(app.state.operation_store.leaderboard, limit)


@app.get(
    "/api/v1/admin/rewards/reviews",
    response_model=RewardTransactionListResponse,
    tags=["rewards-admin"],
)
async def list_reward_reviews(
    _: OperatorPrincipal,
    status: str = "pending",
) -> RewardTransactionListResponse:
    return _operation_call(app.state.operation_store.list_reward_reviews, status)


@app.post(
    "/api/v1/admin/rewards/{transaction_id}/{decision}",
    response_model=RewardTransaction,
    tags=["rewards-admin"],
)
async def review_reward(
    transaction_id: str,
    decision: str,
    request: RewardReviewRequest,
    principal: OperatorPrincipal,
) -> RewardTransaction:
    result = _operation_call(
        app.state.operation_store.review_reward,
        transaction_id,
        decision,
        principal.user_id,
        request.reason,
    )
    _audit(principal, f"reward.{decision}", "reward", transaction_id)
    return result


@app.post(
    "/api/v1/operations/missions/{mission_id}/incidents",
    response_model=MissionIncident,
    tags=["incidents"],
)
async def create_mission_incident(
    mission_id: str,
    request: MissionIncidentRequest,
    principal: DriverPrincipal,
    sequence: int | None = None,
) -> MissionIncident:
    result = _operation_call(
        app.state.operation_store.create_incident,
        mission_id,
        principal.driver_id,
        request.incident_type,
        request.description,
        sequence,
        request.location,
        request.evidence_photo_url,
        request.client_event_id,
    )
    _audit(principal, "incident.create", "mission", mission_id)
    return result


@app.get(
    "/api/v1/admin/incidents",
    response_model=MissionIncidentListResponse,
    tags=["incidents-admin"],
)
async def list_mission_incidents(
    _: OperatorPrincipal,
    mission_id: str | None = None,
    status: str | None = None,
) -> MissionIncidentListResponse:
    return _operation_call(
        app.state.operation_store.list_incidents, mission_id, status
    )


@app.post(
    "/api/v1/admin/missions/{mission_id}/cancel",
    response_model=MissionDetail,
    tags=["operations-admin"],
)
async def cancel_mission(
    mission_id: str,
    request: CancelMissionRequest,
    principal: OperatorPrincipal,
) -> MissionDetail:
    result = _operation_call(
        app.state.operation_store.cancel_mission, mission_id, request.reason
    )
    _audit(principal, "mission.cancel", "mission", mission_id, request.model_dump())
    return result


@app.post(
    "/api/v1/admin/missions/{mission_id}/reassign",
    response_model=MissionDetail,
    tags=["operations-admin"],
)
async def reassign_mission(
    mission_id: str,
    request: ReassignMissionRequest,
    principal: OperatorPrincipal,
) -> MissionDetail:
    result = _operation_call(
        app.state.operation_store.reassign_mission,
        mission_id,
        request.driver_id,
        request.driver_name,
        request.reason,
    )
    _audit(principal, "mission.reassign", "mission", mission_id, request.model_dump())
    return result


@app.post(
    "/api/v1/admin/missions/{mission_id}/stops/{sequence}/skip",
    response_model=MissionDetail,
    tags=["operations-admin"],
)
async def skip_mission_stop(
    mission_id: str,
    sequence: int,
    request: SkipStopRequest,
    principal: OperatorPrincipal,
) -> MissionDetail:
    result = _operation_call(
        app.state.operation_store.skip_stop, mission_id, sequence, request.reason
    )
    _audit(principal, "mission.stop.skip", "mission", mission_id, request.model_dump())
    return result


@app.post(
    "/api/v1/operations/bikes/damage-reports",
    response_model=BikeDamageReport,
    tags=["incidents"],
)
async def report_bike_damage(
    request: BikeDamageReportRequest,
    principal: DriverPrincipal,
) -> BikeDamageReport:
    result = _operation_call(
        app.state.operation_store.report_bike_damage,
        request.bike_qr_code,
        request.mission_id,
        principal.driver_id,
        request.description,
        request.location,
        request.evidence_photo_url,
    )
    _audit(principal, "bike.damage.report", "bike", result.bike_qr_fingerprint)
    return result


@app.post(
    "/api/v1/operations/drivers/me/location",
    response_model=DriverLivePosition,
    tags=["live-operations"],
)
async def record_driver_location(
    request: DriverLocationRequest,
    principal: DriverPrincipal,
) -> DriverLivePosition:
    return _operation_call(
        app.state.operation_store.record_driver_location,
        principal.driver_id,
        request.location,
        request.recorded_at,
        request.accuracy_meters,
        request.speed_kmh,
        request.device_id,
    )


@app.get(
    "/api/v1/admin/operations/live",
    response_model=LiveOperationsResponse,
    tags=["live-operations-admin"],
)
async def get_live_operations(_: OperatorPrincipal) -> LiveOperationsResponse:
    return _operation_call(app.state.operation_store.live_operations)


@app.get(
    "/api/v1/operations/notifications",
    response_model=NotificationListResponse,
    tags=["notifications"],
)
async def list_notifications(
    principal: DriverPrincipal,
    unread_only: bool = False,
) -> NotificationListResponse:
    return _operation_call(
        app.state.operation_store.list_notifications,
        principal.driver_id,
        unread_only,
    )


@app.post(
    "/api/v1/operations/notifications/{notification_id}/read",
    response_model=NotificationItem,
    tags=["notifications"],
)
async def mark_notification_read(
    notification_id: str,
    principal: DriverPrincipal,
) -> NotificationItem:
    return _operation_call(
        app.state.operation_store.mark_notification_read,
        notification_id,
        principal.driver_id,
    )


@app.post(
    "/api/v1/operations/offline/sync",
    response_model=OfflineSyncResponse,
    tags=["offline"],
)
async def sync_offline_events(
    request: OfflineSyncRequest,
    principal: DriverPrincipal,
) -> OfflineSyncResponse:
    items: list[OfflineSyncItem] = []
    store: OperationStore = app.state.operation_store
    for event in request.events:
        existing = _operation_call(
            store.get_offline_event, event.event_id, principal.driver_id
        )
        if existing is not None:
            items.append(
                OfflineSyncItem(
                    event_id=event.event_id,
                    status="duplicate",
                    result=existing["result"],
                    error=existing["error"],
                )
            )
            continue
        try:
            if event.event_type == "location":
                location = DriverLocationRequest.model_validate(event.payload)
                result_model = store.record_driver_location(
                    principal.driver_id,
                    location.location,
                    location.recorded_at,
                    location.accuracy_meters,
                    location.speed_kmh,
                    location.device_id,
                )
            else:
                mission_id = str(event.payload["mission_id"])
                sequence = event.payload.get("sequence")
                incident_payload = {
                    key: value
                    for key, value in event.payload.items()
                    if key not in {"mission_id", "sequence"}
                }
                incident_payload["client_event_id"] = event.event_id
                incident = MissionIncidentRequest.model_validate(incident_payload)
                result_model = store.create_incident(
                    mission_id,
                    principal.driver_id,
                    incident.incident_type,
                    incident.description,
                    sequence,
                    incident.location,
                    incident.evidence_photo_url,
                    event.event_id,
                )
            result = result_model.model_dump(mode="json")
            store.record_offline_event(
                event.event_id,
                principal.driver_id,
                event.event_type,
                "processed",
                result,
                None,
            )
            items.append(
                OfflineSyncItem(
                    event_id=event.event_id,
                    status="processed",
                    result=result,
                )
            )
        except (KeyError, OperationError, ValidationError) as exc:
            error = str(exc)
            store.record_offline_event(
                event.event_id,
                principal.driver_id,
                event.event_type,
                "failed",
                None,
                error,
            )
            items.append(
                OfflineSyncItem(
                    event_id=event.event_id,
                    status="failed",
                    error=error,
                )
            )
    return OfflineSyncResponse(
        processed=sum(item.status == "processed" for item in items),
        duplicates=sum(item.status == "duplicate" for item in items),
        failed=sum(item.status == "failed" for item in items),
        items=items,
    )


@app.post(
    "/api/v1/admin/settlements",
    response_model=SettlementBatch,
    tags=["settlements-admin"],
)
async def create_settlement(
    request: CreateSettlementRequest,
    principal: AdminPrincipal,
) -> SettlementBatch:
    result = _operation_call(
        app.state.operation_store.create_settlement,
        request.period_start,
        request.period_end,
        principal.user_id,
    )
    _audit(principal, "settlement.create", "settlement", result.settlement_id)
    return result


@app.get(
    "/api/v1/admin/settlements/{settlement_id}",
    response_model=SettlementBatch,
    tags=["settlements-admin"],
)
async def get_settlement(
    settlement_id: str, _: AdminPrincipal
) -> SettlementBatch:
    return _operation_call(app.state.operation_store.get_settlement, settlement_id)


@app.post(
    "/api/v1/admin/settlements/{settlement_id}/paid",
    response_model=SettlementBatch,
    tags=["settlements-admin"],
)
async def mark_settlement_paid(
    settlement_id: str,
    request: RewardReviewRequest,
    principal: AdminPrincipal,
) -> SettlementBatch:
    result = _operation_call(
        app.state.operation_store.mark_settlement_paid,
        settlement_id,
        principal.user_id,
    )
    _audit(
        principal,
        "settlement.paid",
        "settlement",
        settlement_id,
        {"reason": request.reason},
    )
    return result


@app.get(
    "/api/v1/admin/audit-logs",
    response_model=AuditLogResponse,
    tags=["audit-admin"],
)
async def list_audit_logs(
    _: AdminPrincipal,
    limit: int = Query(default=100, ge=1, le=1000),
) -> AuditLogResponse:
    return _operation_call(app.state.operation_store.list_audit_logs, limit)


@app.get(
    "/api/v1/admin/analytics/operations",
    response_model=OperationsAnalytics,
    tags=["analytics-admin"],
)
async def operations_analytics(_: OperatorPrincipal) -> OperationsAnalytics:
    return _operation_call(app.state.operation_store.analytics)


def _require_test_scenario(scenario_id: str | None = None) -> TestScenarioResponse:
    scenario = app.state.test_scenarios.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="활성 테스트 시나리오가 없습니다.")
    return scenario


def _test_driver_mission(
    scenario: TestScenarioResponse,
    driver_id: str,
) -> MissionDetail | None:
    if not any(driver.driver_id == driver_id for driver in scenario.drivers):
        raise HTTPException(status_code=404, detail="시나리오 기사를 찾을 수 없습니다.")
    summaries = _operation_call(
        app.state.operation_store.list_missions,
        driver_id=driver_id,
    ).missions
    summary = next(
        (item for item in summaries if item.plan_id == scenario.plan.plan_id),
        None,
    )
    if summary is None:
        return None
    return _operation_call(app.state.operation_store.get_mission, summary.mission_id)


def _initialize_test_driver_states(scenario: TestScenarioResponse) -> None:
    for driver in scenario.drivers:
        mission = _test_driver_mission(scenario, driver.driver_id)
        next_stop = (
            next((stop for stop in mission.stops if stop.status == "pending"), None)
            if mission is not None
            else None
        )
        app.state.test_scenarios.set_movement_state(
            scenario.scenario_id,
            driver.driver_id,
            mission_id=mission.mission_id if mission else None,
            mission_status=mission.status if mission else None,
            current_location=driver.start_location,
            next_stop=next_stop,
            arrived=False,
        )


def _current_test_driver_state(driver_id: str) -> TestForcedArrival:
    scenario = _require_test_scenario()
    driver = next(
        (item for item in scenario.drivers if item.driver_id == driver_id),
        None,
    )
    if driver is None:
        raise HTTPException(status_code=404, detail="시나리오 기사를 찾을 수 없습니다.")
    mission = _test_driver_mission(scenario, driver_id)
    cached = app.state.test_scenarios.get_movement_state(
        scenario.scenario_id,
        driver_id,
    )
    next_stop = (
        next((stop for stop in mission.stops if stop.status == "pending"), None)
        if mission is not None
        else None
    )
    arrived = bool(
        cached
        and cached.arrived
        and mission is not None
        and cached.mission_id == mission.mission_id
        and cached.next_stop is not None
        and next_stop is not None
        and cached.next_stop.sequence == next_stop.sequence
    )
    return TestForcedArrival(
        scenario_id=scenario.scenario_id,
        driver_id=driver_id,
        mission_id=mission.mission_id if mission else None,
        mission_status=mission.status if mission else None,
        current_location=(cached.current_location if cached else driver.start_location),
        next_stop=next_stop,
        arrived=arrived,
        movement_version=cached.movement_version if cached else 0,
    )


def _build_test_qr_sequence(
    scenario: TestScenarioResponse,
    mission: MissionDetail,
    stop,
) -> TestQrSequence:
    payloads: list[tuple[str, str, str | None, str | None]] = []
    if stop.action == "pickup":
        codes = _test_bike_codes(
            scenario.scenario_id,
            mission.mission_id,
            stop.sequence,
            stop.planned_quantity,
        )
        payloads.extend(
            ("bike", code, code.rsplit(":", 1)[-1], None) for code in codes
        )
    else:
        provisioned = _operation_call(
            app.state.operation_store.provision_station_qr,
            stop.station_id,
            None,
        )
        payloads.append(("station", provisioned.qr_payload, None, stop.station_id))
        loaded_codes: list[str] = []
        for previous in mission.stops:
            if previous.sequence >= stop.sequence:
                break
            if previous.action == "pickup":
                if previous.status != "completed":
                    continue
                pickup_quantity = previous.actual_quantity or 0
                loaded_codes.extend(
                    _test_bike_codes(
                        scenario.scenario_id,
                        mission.mission_id,
                        previous.sequence,
                        previous.planned_quantity,
                    )[:pickup_quantity]
                )
            elif previous.status == "completed":
                loaded_codes = loaded_codes[(previous.actual_quantity or 0) :]
        drop_codes = loaded_codes[: stop.planned_quantity]
        if len(drop_codes) != stop.planned_quantity:
            raise HTTPException(
                status_code=409,
                detail="현재 차량 적재 QR을 구성할 수 없습니다. 앞선 회수 정차를 완료하세요.",
            )
        payloads.extend(
            ("bike", code, code.rsplit(":", 1)[-1], None) for code in drop_codes
        )

    total = len(payloads)
    items = [
        TestQrItem(
            qr_id=(
                f"{scenario.scenario_id}:{mission.mission_id}:"
                f"{stop.sequence}:{index}"
            ),
            kind=kind,
            label=(
                f"{stop.station_name} 대여소 QR"
                if kind == "station"
                else f"자전거 QR {index}/{total}"
            ),
            payload=payload,
            svg_data_url=_qr_svg_data_url(payload),
            mission_id=mission.mission_id,
            stop_sequence=stop.sequence,
            ordinal=index,
            total=total,
            station_id=station_id,
            bike_id=bike_id,
        )
        for index, (kind, payload, bike_id, station_id) in enumerate(
            payloads,
            start=1,
        )
    ]
    return TestQrSequence(
        scenario_id=scenario.scenario_id,
        driver_id=mission.driver_id,
        mission_id=mission.mission_id,
        stop_sequence=stop.sequence,
        stop_action=stop.action,
        items=items,
    )


def _test_bike_codes(
    scenario_id: str,
    mission_id: str,
    stop_sequence: int,
    quantity: int,
) -> list[str]:
    runtime: TestScenarioRuntime = app.state.test_scenarios
    cached = runtime.get_bike_codes(scenario_id, mission_id, stop_sequence)
    if cached:
        return cached
    codes = [
        f"TASHU-TEST-BIKE:{scenario_id}:{mission_id}:{stop_sequence}:{index}"
        for index in range(1, quantity + 1)
    ]
    runtime.cache_bike_codes(scenario_id, mission_id, stop_sequence, codes)
    return codes


def _qr_svg_data_url(payload: str) -> str:
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode()
    return f"data:image/svg+xml;base64,{encoded}"


def _operation_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except OperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _auth_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _authorize_mission(principal: AuthPrincipal, driver_id: str) -> None:
    if principal.role == "driver" and principal.driver_id != driver_id:
        raise HTTPException(status_code=403, detail="다른 기사의 데이터에 접근할 수 없습니다.")


def _authorize_driver_action(principal: AuthPrincipal, driver_id: str) -> None:
    if principal.driver_id != driver_id:
        raise HTTPException(status_code=403, detail="로그인 기사와 요청 기사가 다릅니다.")


def _audit(
    principal: AuthPrincipal,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    app.state.operation_store.record_audit(
        principal.user_id,
        principal.role,
        action,
        resource_type,
        resource_id,
        details,
    )


def _require_test_mode() -> None:
    if not getattr(app.state, "test_mode", False):
        raise HTTPException(status_code=404, detail="테스트 모드가 비활성화되어 있습니다.")
