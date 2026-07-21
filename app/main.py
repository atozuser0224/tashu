from __future__ import annotations

import base64
import io
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable

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
from app.tmap import TmapApiError, TmapClient, enrich_plan_with_tmap
from app.travel import TravelNode, driver_node_id, station_node_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.tashu_client = TashuClient()
    app.state.tmap_client = TmapClient()
    app.state.test_mode = os.getenv("TEST_MODE", "true").lower() == "true"
    database_path = os.getenv("TASHU_DB_PATH", "data/tashu.db")
    app.state.operation_store = OperationStore(database_path)
    app.state.auth_store = AuthStore(database_path)
    try:
        yield
    finally:
        app.state.auth_store.close()
        app.state.operation_store.close()


app = FastAPI(
    title="타슈 다중 기사 재배치 API",
    version="0.6.0",
    description=(
        "core ST-GNN 예측과 타슈 실시간 재고를 결합해 기사별 동선을 배정하고, "
        "기사 미션 수행과 포인트 리워드까지 관리합니다."
    ),
    lifespan=lifespan,
)

origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173"
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
    return HTMLResponse(panel_path.read_text(encoding="utf-8"))


@app.get("/api/v1/test/status", tags=["test-mode"])
async def test_mode_status() -> dict:
    _require_test_mode()
    return {
        "test_mode": True,
        "authentication_bypassed": True,
        "external_calls_simulated": True,
        "panel_url": "/test-panel",
    }


@app.post("/api/v1/test/reset", tags=["test-mode"])
async def reset_test_mode() -> dict:
    _require_test_mode()
    _operation_call(app.state.operation_store.reset_test_data)
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
    qr = qrcode.QRCode(version=None, box_size=8, border=3)
    qr.add_data(provisioned.qr_payload)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = io.BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode()
    return TestStationQrResponse(
        station_id=station_id,
        qr_payload=provisioned.qr_payload,
        svg_data_url=f"data:image/svg+xml;base64,{encoded}",
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
    request: PlanRequest, principal: OperatorPrincipal
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
