from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models import ApiModel, DriverRouteOutput, Location


MissionStatus = Literal[
    "offered", "accepted", "in_progress", "completed", "cancelled"
]
StopStatus = Literal["pending", "completed", "skipped"]
RewardStatus = Literal["pending", "approved", "rejected", "reversed"]


class MissionActionRequest(ApiModel):
    driver_id: str = Field(min_length=1)
    client_event_id: str | None = Field(default=None, min_length=8, max_length=200)


class CompleteMissionStopRequest(MissionActionRequest):
    location: Location
    actual_quantity: int = Field(ge=0)
    bike_qr_codes: list[str] = Field(default_factory=list, max_length=100)
    evidence_photo_url: str | None = Field(default=None, max_length=2048)


class VerifyStationQrRequest(MissionActionRequest):
    location: Location
    qr_payload: str = Field(min_length=1, max_length=4096)
    challenge_id: str
    device_id: str = Field(min_length=1, max_length=200)
    integrity_provider: Literal["development", "play_integrity", "app_attest"]
    integrity_token: str | None = Field(default=None, max_length=16_384)


class QrChallengeRequest(MissionActionRequest):
    device_id: str = Field(min_length=1, max_length=200)


class QrChallengeResponse(ApiModel):
    challenge_id: str
    mission_id: str
    sequence: int
    expires_at: datetime


class StationQrProvisionResponse(ApiModel):
    station_id: str
    qr_payload: str
    qr_format: Literal["tashu-station-v1"] = "tashu-station-v1"
    usage: str = "대여소에 부착하고 기사 앱 스캐너가 원문 payload를 전송합니다."


class TestStationQrResponse(ApiModel):
    station_id: str
    qr_payload: str
    svg_data_url: str


class RewardBreakdown(ApiModel):
    base_points: int = Field(ge=0)
    priority_bonus_points: int = Field(ge=0)
    completion_bonus_points: int = Field(ge=0)
    total_points: int = Field(ge=0)


class MissionStop(ApiModel):
    sequence: int = Field(ge=1)
    action: Literal["pickup", "dropoff"]
    station_id: str
    station_name: str
    location: Location
    planned_quantity: int = Field(ge=0)
    actual_quantity: int | None = Field(default=None, ge=0)
    status: StopStatus
    shortage_pressure: float = Field(ge=0, le=1)
    qr_verification: Literal["not_required", "pending", "verified"]
    qr_verified_at: datetime | None = None
    qr_verified_location: Location | None = None
    bike_qr_count: int = Field(default=0, ge=0)
    completed_location: Location | None = None
    distance_from_station_meters: float | None = Field(default=None, ge=0)
    evidence_photo_url: str | None = None
    skipped_reason: str | None = None
    completed_at: datetime | None = None


class MissionSummary(ApiModel):
    mission_id: str
    plan_id: str
    driver_id: str
    driver_name: str
    status: MissionStatus
    total_stops: int = Field(ge=0)
    completed_stops: int = Field(ge=0)
    planned_bikes: int = Field(ge=0)
    first_pickup: MissionStop | None = None
    estimated_reward: RewardBreakdown
    awarded_reward: RewardBreakdown | None = None
    reward_status: RewardStatus | None = None
    cancelled_reason: str | None = None
    offered_at: datetime
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MissionDetail(MissionSummary):
    stops: list[MissionStop]
    route: DriverRouteOutput
    gps_completion_radius_meters: int = Field(ge=1)


class MissionListResponse(ApiModel):
    count: int = Field(ge=0)
    missions: list[MissionSummary]


class RewardTransaction(ApiModel):
    transaction_id: str
    driver_id: str
    mission_id: str
    points: int = Field(ge=0)
    reason: str
    status: RewardStatus
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    fraud_score: int = Field(default=0, ge=0, le=100)
    settlement_id: str | None = None
    breakdown: RewardBreakdown
    created_at: datetime


class RewardWallet(ApiModel):
    driver_id: str
    balance_points: int = Field(ge=0)
    lifetime_earned_points: int = Field(ge=0)
    completed_mission_count: int = Field(ge=0)
    pending_points: int = Field(default=0, ge=0)
    reversed_points: int = Field(default=0, ge=0)
    updated_at: datetime | None = None


class RewardTransactionListResponse(ApiModel):
    count: int = Field(ge=0)
    transactions: list[RewardTransaction]


class LeaderboardEntry(ApiModel):
    rank: int = Field(ge=1)
    driver_id: str
    driver_name: str
    points: int = Field(ge=0)
    completed_mission_count: int = Field(ge=0)


class LeaderboardResponse(ApiModel):
    count: int = Field(ge=0)
    entries: list[LeaderboardEntry]


class DriverBootstrapResponse(ApiModel):
    driver_id: str
    missions: list[MissionSummary]
    wallet: RewardWallet


class RewardReviewRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=1000)


class MissionIncidentRequest(ApiModel):
    incident_type: Literal[
        "dock_full",
        "station_closed",
        "station_qr_damaged",
        "bike_damaged",
        "vehicle_capacity",
        "traffic_accident",
        "access_blocked",
        "quantity_mismatch",
        "other",
    ]
    description: str = Field(min_length=3, max_length=2000)
    location: Location | None = None
    evidence_photo_url: str | None = Field(default=None, max_length=2048)
    client_event_id: str | None = Field(default=None, min_length=8, max_length=200)


class MissionIncident(ApiModel):
    incident_id: str
    mission_id: str
    sequence: int | None = None
    driver_id: str
    incident_type: str
    description: str
    location: Location | None = None
    evidence_photo_url: str | None = None
    status: Literal["open", "resolved"]
    created_at: datetime
    resolved_at: datetime | None = None


class MissionIncidentListResponse(ApiModel):
    count: int
    incidents: list[MissionIncident]


class CancelMissionRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=1000)


class ReassignMissionRequest(ApiModel):
    driver_id: str = Field(min_length=1)
    driver_name: str = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)


class SkipStopRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=1000)


class BikeDamageReportRequest(ApiModel):
    bike_qr_code: str = Field(min_length=1, max_length=2048)
    mission_id: str | None = None
    description: str = Field(min_length=3, max_length=2000)
    location: Location | None = None
    evidence_photo_url: str | None = Field(default=None, max_length=2048)


class BikeDamageReport(ApiModel):
    report_id: str
    bike_qr_fingerprint: str
    mission_id: str | None = None
    reported_by: str
    description: str
    status: Literal["open", "resolved"]
    created_at: datetime


class DriverLocationRequest(ApiModel):
    location: Location
    recorded_at: datetime
    accuracy_meters: float = Field(ge=0, le=5000)
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    device_id: str = Field(min_length=1, max_length=200)


class DriverLivePosition(ApiModel):
    driver_id: str
    location: Location
    recorded_at: datetime
    accuracy_meters: float
    speed_kmh: float | None = None
    anomaly: str | None = None
    active_mission_id: str | None = None


class LiveOperationsResponse(ApiModel):
    count: int
    drivers: list[DriverLivePosition]


class NotificationItem(ApiModel):
    notification_id: str
    driver_id: str
    notification_type: str
    title: str
    body: str
    data: dict
    created_at: datetime
    read_at: datetime | None = None


class NotificationListResponse(ApiModel):
    count: int
    notifications: list[NotificationItem]


class AuditLogItem(ApiModel):
    audit_id: str
    actor_id: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    details: dict
    created_at: datetime


class AuditLogResponse(ApiModel):
    count: int
    items: list[AuditLogItem]


class OperationsAnalytics(ApiModel):
    mission_counts: dict[str, int]
    reward_points: dict[str, int]
    incident_counts: dict[str, int]
    total_bikes_delivered: int
    active_driver_count: int


class CreateSettlementRequest(ApiModel):
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def period_is_valid(self) -> "CreateSettlementRequest":
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("settlement period requires timezone offsets")
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be later than period_start")
        return self


class SettlementDriverTotal(ApiModel):
    driver_id: str
    points: int = Field(ge=0)
    transaction_count: int = Field(ge=0)


class SettlementBatch(ApiModel):
    settlement_id: str
    status: Literal["open", "paid"]
    period_start: datetime
    period_end: datetime
    total_points: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    drivers: list[SettlementDriverTotal]
    created_by: str
    created_at: datetime
    paid_at: datetime | None = None


class OfflineEvent(ApiModel):
    event_id: str = Field(min_length=8, max_length=200)
    event_type: Literal["location", "incident"]
    payload: dict


class OfflineSyncRequest(ApiModel):
    events: list[OfflineEvent] = Field(min_length=1, max_length=100)


class OfflineSyncItem(ApiModel):
    event_id: str
    status: Literal["processed", "duplicate", "failed"]
    result: dict | None = None
    error: str | None = None


class OfflineSyncResponse(ApiModel):
    processed: int
    duplicates: int
    failed: int
    items: list[OfflineSyncItem]
