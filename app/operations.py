from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import DriverRouteOutput, Location, PlanResponse
from app.operations_models import (
    AuditLogItem,
    AuditLogResponse,
    BikeDamageReport,
    DriverLivePosition,
    DriverBootstrapResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    LiveOperationsResponse,
    MissionDetail,
    MissionIncident,
    MissionIncidentListResponse,
    MissionListResponse,
    MissionStop,
    MissionSummary,
    NotificationItem,
    NotificationListResponse,
    OperationsAnalytics,
    QrChallengeResponse,
    RewardBreakdown,
    RewardTransaction,
    RewardTransactionListResponse,
    RewardWallet,
    SettlementBatch,
    SettlementDriverTotal,
    StationQrProvisionResponse,
)
from app.planner import haversine_km


class OperationError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OperationConfig:
    gps_radius_meters: int = 200
    points_per_bike: int = 100
    priority_points_per_bike: int = 50
    full_completion_bonus_points: int = 300
    qr_verification_ttl_seconds: int = 600
    station_qr_admin_key: str | None = None
    qr_challenge_ttl_seconds: int = 120
    reward_auto_approve: bool = False
    allow_development_integrity: bool = False
    test_mode: bool = True

    @classmethod
    def from_env(cls) -> "OperationConfig":
        return cls(
            gps_radius_meters=int(os.getenv("MISSION_GPS_RADIUS_METERS", "200")),
            points_per_bike=int(os.getenv("REWARD_POINTS_PER_BIKE", "100")),
            priority_points_per_bike=int(
                os.getenv("REWARD_PRIORITY_POINTS_PER_BIKE", "50")
            ),
            full_completion_bonus_points=int(
                os.getenv("REWARD_FULL_COMPLETION_BONUS_POINTS", "300")
            ),
            qr_verification_ttl_seconds=int(
                os.getenv("STATION_QR_VERIFICATION_TTL_SECONDS", "600")
            ),
            station_qr_admin_key=os.getenv("STATION_QR_ADMIN_KEY"),
            qr_challenge_ttl_seconds=int(
                os.getenv("QR_CHALLENGE_TTL_SECONDS", "120")
            ),
            reward_auto_approve=os.getenv("REWARD_AUTO_APPROVE", "false").lower()
            == "true",
            allow_development_integrity=os.getenv(
                "ALLOW_DEVELOPMENT_INTEGRITY", "false"
            ).lower()
            == "true",
            test_mode=os.getenv("TEST_MODE", "true").lower() == "true",
        )


class OperationStore:
    def __init__(
        self,
        database_path: str,
        config: OperationConfig | None = None,
    ) -> None:
        self.config = config or OperationConfig.from_env()
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._initialize_schema()
        self._qr_secret = self._load_qr_secret()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def reset_test_data(self) -> None:
        if not self.config.test_mode:
            raise OperationError(403, "TEST_MODE에서만 테스트 데이터를 초기화할 수 있습니다.")
        with self._lock, self._connection:
            for table in (
                "reward_ledger",
                "mission_bikes",
                "qr_challenges",
                "mission_incidents",
                "bike_damage_reports",
                "driver_locations",
                "notifications",
                "audit_logs",
                "offline_events",
                "mission_stops",
                "missions",
                "settlements",
            ):
                self._connection.execute(f"DELETE FROM {table}")

    def _initialize_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    mission_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    driver_id TEXT NOT NULL,
                    driver_name TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('offered', 'accepted', 'in_progress', 'completed')
                    ),
                    estimated_reward_json TEXT NOT NULL,
                    awarded_reward_json TEXT,
                    route_json TEXT NOT NULL,
                    offered_at TEXT NOT NULL,
                    accepted_at TEXT,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_missions_driver_status
                    ON missions(driver_id, status, offered_at DESC);

                CREATE TABLE IF NOT EXISTS mission_stops (
                    mission_id TEXT NOT NULL REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    action TEXT NOT NULL CHECK (action IN ('pickup', 'dropoff')),
                    station_id TEXT NOT NULL,
                    station_name TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL,
                    planned_quantity INTEGER NOT NULL CHECK (planned_quantity >= 0),
                    actual_quantity INTEGER CHECK (actual_quantity >= 0),
                    shortage_pressure REAL NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
                    qr_status TEXT NOT NULL DEFAULT 'not_required',
                    qr_verified_at TEXT,
                    qr_verified_lat REAL,
                    qr_verified_lng REAL,
                    qr_token_fingerprint TEXT,
                    bike_qr_count INTEGER NOT NULL DEFAULT 0,
                    completed_lat REAL,
                    completed_lng REAL,
                    distance_from_station_meters REAL,
                    evidence_photo_url TEXT,
                    completed_at TEXT,
                    PRIMARY KEY (mission_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS reward_ledger (
                    transaction_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL UNIQUE REFERENCES missions(mission_id),
                    points INTEGER NOT NULL CHECK (points >= 0),
                    reason TEXT NOT NULL,
                    breakdown_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    review_reason TEXT,
                    fraud_score INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_rewards_driver_created
                    ON reward_ledger(driver_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS mission_bikes (
                    mission_id TEXT NOT NULL REFERENCES missions(mission_id)
                        ON DELETE CASCADE,
                    bike_qr_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('loaded', 'dropped')),
                    pickup_sequence INTEGER NOT NULL,
                    dropoff_sequence INTEGER,
                    picked_at TEXT NOT NULL,
                    dropped_at TEXT,
                    PRIMARY KEY (mission_id, bike_qr_hash)
                );

                CREATE TABLE IF NOT EXISTS operation_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS qr_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(mission_id),
                    sequence INTEGER NOT NULL,
                    driver_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    integrity_provider TEXT,
                    integrity_fingerprint TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mission_incidents (
                    incident_id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(mission_id),
                    sequence INTEGER,
                    driver_id TEXT NOT NULL,
                    incident_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    lat REAL,
                    lng REAL,
                    evidence_photo_url TEXT,
                    client_event_id TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS bike_damage_reports (
                    report_id TEXT PRIMARY KEY,
                    bike_qr_hash TEXT NOT NULL,
                    mission_id TEXT,
                    reported_by TEXT NOT NULL,
                    description TEXT NOT NULL,
                    lat REAL,
                    lng REAL,
                    evidence_photo_url TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS driver_locations (
                    location_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL,
                    accuracy_meters REAL NOT NULL,
                    speed_kmh REAL,
                    device_id TEXT NOT NULL,
                    anomaly TEXT,
                    recorded_at TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_driver_locations_latest
                    ON driver_locations(driver_id, recorded_at DESC);

                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    notification_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_driver
                    ON notifications(driver_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settlements (
                    settlement_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'open',
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    total_points INTEGER NOT NULL,
                    transaction_count INTEGER NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    paid_at TEXT
                );

                CREATE TABLE IF NOT EXISTS offline_events (
                    event_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(
                "mission_stops", "qr_status", "TEXT NOT NULL DEFAULT 'not_required'"
            )
            self._ensure_column("mission_stops", "qr_verified_at", "TEXT")
            self._ensure_column("mission_stops", "qr_verified_lat", "REAL")
            self._ensure_column("mission_stops", "qr_verified_lng", "REAL")
            self._ensure_column("mission_stops", "qr_token_fingerprint", "TEXT")
            self._ensure_column(
                "mission_stops", "bike_qr_count", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column("mission_stops", "skipped_reason", "TEXT")
            self._ensure_column("missions", "cancelled_at", "TEXT")
            self._ensure_column("missions", "cancelled_reason", "TEXT")
            self._ensure_column(
                "reward_ledger", "status", "TEXT NOT NULL DEFAULT 'approved'"
            )
            self._ensure_column("reward_ledger", "reviewed_at", "TEXT")
            self._ensure_column("reward_ledger", "reviewed_by", "TEXT")
            self._ensure_column("reward_ledger", "review_reason", "TEXT")
            self._ensure_column(
                "reward_ledger", "fraud_score", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column("reward_ledger", "settlement_id", "TEXT")
            self._connection.execute(
                "UPDATE mission_stops SET qr_status = 'pending' "
                "WHERE action = 'dropoff' AND status = 'pending' "
                "AND qr_status = 'not_required'"
            )
            self._connection.execute(
                "UPDATE mission_stops SET qr_status = 'verified' "
                "WHERE action = 'dropoff' AND status = 'completed' "
                "AND qr_status = 'not_required'"
            )

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self._connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def _load_qr_secret(self) -> bytes:
        configured = os.getenv("STATION_QR_SIGNING_SECRET")
        if configured:
            return configured.encode()
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT setting_value FROM operation_settings "
                "WHERE setting_key = 'station_qr_signing_secret'"
            ).fetchone()
            if row is not None:
                return row["setting_value"].encode()
            generated = secrets.token_urlsafe(48)
            self._connection.execute(
                "INSERT INTO operation_settings(setting_key, setting_value) VALUES (?, ?)",
                ("station_qr_signing_secret", generated),
            )
            return generated.encode()

    def provision_station_qr(
        self, station_id: str, admin_key: str | None
    ) -> StationQrProvisionResponse:
        expected_key = self.config.station_qr_admin_key
        if self.config.test_mode:
            pass
        elif not expected_key:
            raise OperationError(
                503, "STATION_QR_ADMIN_KEY를 설정해야 QR을 발급할 수 있습니다."
            )
        elif not admin_key or not hmac.compare_digest(admin_key, expected_key):
            raise OperationError(403, "QR 발급 관리자 키가 올바르지 않습니다.")
        encoded_station = _base64url_encode(station_id.encode())
        signed_value = f"v1:{encoded_station}"
        signature = hmac.new(
            self._qr_secret, signed_value.encode(), hashlib.sha256
        ).digest()
        return StationQrProvisionResponse(
            station_id=station_id,
            qr_payload=(
                f"tashu-station:{signed_value}:{_base64url_encode(signature)}"
            ),
        )

    def verify_station_qr(
        self,
        mission_id: str,
        sequence: int,
        driver_id: str,
        location: Location,
        qr_payload: str,
        challenge_id: str,
        device_id: str,
        integrity_provider: str,
        integrity_token: str | None,
    ) -> MissionDetail:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            self._verify_driver(mission, driver_id)
            if self._effective_mission_status(mission) != "in_progress":
                raise OperationError(409, "진행 중인 미션에서만 QR 인증이 가능합니다.")
            stop = self._connection.execute(
                "SELECT * FROM mission_stops WHERE mission_id = ? AND sequence = ?",
                (mission_id, sequence),
            ).fetchone()
            if stop is None:
                raise OperationError(404, "미션 정차지를 찾을 수 없습니다.")
            if stop["status"] == "completed" and stop["qr_status"] == "verified":
                return self._get_mission_locked(mission_id)
            if stop["action"] != "dropoff":
                raise OperationError(422, "반납 정차지만 대여소 QR 인증이 필요합니다.")
            next_stop = self._connection.execute(
                """
                SELECT sequence FROM mission_stops
                WHERE mission_id = ? AND status = 'pending'
                ORDER BY sequence LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if next_stop is None or next_stop["sequence"] != sequence:
                expected = next_stop["sequence"] if next_stop else "없음"
                raise OperationError(
                    409, f"정차 순서가 맞지 않습니다. 다음 순서는 {expected}입니다."
                )
            challenge = self._consume_qr_challenge_locked(
                challenge_id,
                mission_id,
                sequence,
                driver_id,
                device_id,
                integrity_provider,
                integrity_token,
            )
            scanned_station_id = self._decode_station_qr(qr_payload)
            if scanned_station_id != stop["station_id"]:
                raise OperationError(422, "현재 반납 대여소의 QR이 아닙니다.")
            distance_meters = self._distance_from_stop(stop, location)
            if distance_meters > self.config.gps_radius_meters:
                raise OperationError(
                    422,
                    "대여소에서 너무 멉니다. "
                    f"현재 {distance_meters:.0f}m, 허용 {self.config.gps_radius_meters}m",
                )
            self._connection.execute(
                """
                UPDATE mission_stops SET qr_status = 'verified', qr_verified_at = ?,
                    qr_verified_lat = ?, qr_verified_lng = ?, qr_token_fingerprint = ?
                WHERE mission_id = ? AND sequence = ?
                """,
                (
                    _utc_now(),
                    location.lat,
                    location.lng,
                    hashlib.sha256(qr_payload.encode()).hexdigest()[:16],
                    mission_id,
                    sequence,
                ),
            )
            self._connection.execute(
                """
                UPDATE qr_challenges SET consumed_at = ?, integrity_provider = ?,
                    integrity_fingerprint = ? WHERE challenge_id = ?
                """,
                (
                    _utc_now(),
                    integrity_provider,
                    challenge,
                    challenge_id,
                ),
            )
            return self._get_mission_locked(mission_id)

    def issue_qr_challenge(
        self,
        mission_id: str,
        sequence: int,
        driver_id: str,
        device_id: str,
    ) -> QrChallengeResponse:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            self._verify_driver(mission, driver_id)
            if self._effective_mission_status(mission) != "in_progress":
                raise OperationError(409, "진행 중인 미션에서만 QR 인증이 가능합니다.")
            stop = self._connection.execute(
                "SELECT * FROM mission_stops WHERE mission_id = ? AND sequence = ?",
                (mission_id, sequence),
            ).fetchone()
            if stop is None or stop["action"] != "dropoff":
                raise OperationError(422, "반납 정차지만 QR challenge를 발급합니다.")
            next_stop = self._connection.execute(
                "SELECT sequence FROM mission_stops WHERE mission_id = ? "
                "AND status = 'pending' ORDER BY sequence LIMIT 1",
                (mission_id,),
            ).fetchone()
            if next_stop is None or next_stop["sequence"] != sequence:
                raise OperationError(409, "현재 처리할 반납 정차지가 아닙니다.")
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(
                seconds=self.config.qr_challenge_ttl_seconds
            )
            challenge_id = f"qrc-{uuid.uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO qr_challenges (
                    challenge_id, mission_id, sequence, driver_id, device_id,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    mission_id,
                    sequence,
                    driver_id,
                    device_id,
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
            return QrChallengeResponse(
                challenge_id=challenge_id,
                mission_id=mission_id,
                sequence=sequence,
                expires_at=expires_at,
            )

    def _consume_qr_challenge_locked(
        self,
        challenge_id: str,
        mission_id: str,
        sequence: int,
        driver_id: str,
        device_id: str,
        integrity_provider: str,
        integrity_token: str | None,
    ) -> str:
        row = self._connection.execute(
            "SELECT * FROM qr_challenges WHERE challenge_id = ?", (challenge_id,)
        ).fetchone()
        if row is None or row["consumed_at"]:
            raise OperationError(409, "QR challenge가 없거나 이미 사용되었습니다.")
        if (
            row["mission_id"] != mission_id
            or row["sequence"] != sequence
            or row["driver_id"] != driver_id
            or row["device_id"] != device_id
        ):
            raise OperationError(403, "QR challenge가 현재 요청과 일치하지 않습니다.")
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            raise OperationError(409, "QR challenge가 만료되었습니다.")
        return self._verify_device_integrity(
            integrity_provider, integrity_token, device_id, challenge_id
        )

    def _verify_device_integrity(
        self,
        provider: str,
        token: str | None,
        device_id: str,
        challenge_id: str,
    ) -> str:
        if provider == "development":
            if (
                not self.config.test_mode
                and (
                    not self.config.allow_development_integrity
                    or token != "development-ok"
                )
            ):
                raise OperationError(403, "개발용 기기 무결성 인증이 허용되지 않습니다.")
        else:
            gateway_secret = os.getenv("DEVICE_INTEGRITY_GATEWAY_SECRET")
            if not gateway_secret or not token:
                raise OperationError(503, "기기 무결성 검증 게이트웨이가 설정되지 않았습니다.")
            message = f"{provider}:{device_id}:{challenge_id}"
            expected = hmac.new(
                gateway_secret.encode(), message.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(token, expected):
                raise OperationError(403, "기기 무결성 검증에 실패했습니다.")
        return hashlib.sha256(f"{provider}:{token}".encode()).hexdigest()[:16]

    def _decode_station_qr(self, qr_payload: str) -> str:
        try:
            prefix, version, encoded_station, encoded_signature = qr_payload.split(":")
            if prefix != "tashu-station" or version != "v1":
                raise ValueError
            signed_value = f"{version}:{encoded_station}"
            expected = hmac.new(
                self._qr_secret, signed_value.encode(), hashlib.sha256
            ).digest()
            actual = _base64url_decode(encoded_signature)
            if not hmac.compare_digest(actual, expected):
                raise ValueError
            return _base64url_decode(encoded_station).decode()
        except (UnicodeDecodeError, ValueError) as exc:
            raise OperationError(422, "유효하지 않거나 위조된 대여소 QR입니다.") from exc

    def publish_plan(self, plan: PlanResponse) -> list[str]:
        mission_ids: list[str] = []
        now = _utc_now()
        with self._lock, self._connection:
            for route in plan.routes:
                if route.status != "assigned" or not route.stops:
                    continue
                mission_id = _mission_id(plan.plan_id, route.driver_id)
                reward = self._reward_for_route(route)
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO missions (
                        mission_id, plan_id, driver_id, driver_name, status,
                        estimated_reward_json, route_json, offered_at
                    ) VALUES (?, ?, ?, ?, 'offered', ?, ?, ?)
                    """,
                    (
                        mission_id,
                        plan.plan_id,
                        route.driver_id,
                        route.driver_name,
                        reward.model_dump_json(),
                        route.model_dump_json(),
                        now,
                    ),
                )
                if cursor.rowcount:
                    self._connection.executemany(
                        """
                        INSERT INTO mission_stops (
                            mission_id, sequence, action, station_id, station_name,
                            lat, lng, planned_quantity, shortage_pressure, status,
                            qr_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        [
                            (
                                mission_id,
                                stop.sequence,
                                stop.action,
                                stop.station_id,
                                stop.station_name,
                                stop.location.lat,
                                stop.location.lng,
                                stop.quantity,
                                stop.shortage_pressure,
                                "pending" if stop.action == "dropoff" else "not_required",
                            )
                            for stop in route.stops
                        ],
                    )
                    self._notify_locked(
                        route.driver_id,
                        "mission.offered",
                        "새 재배치 미션",
                        f"{route.total_bikes_moved}대 재배치 미션이 배정되었습니다.",
                        {"mission_id": mission_id, "plan_id": plan.plan_id},
                    )
                mission_ids.append(mission_id)
        return mission_ids

    def record_audit(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO audit_logs (
                    audit_id, actor_id, actor_role, action, resource_type,
                    resource_id, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"audit-{uuid.uuid4().hex}",
                    actor_id,
                    actor_role,
                    action,
                    resource_type,
                    resource_id,
                    json.dumps(details or {}, ensure_ascii=False),
                    _utc_now(),
                ),
            )

    def list_audit_logs(self, limit: int = 100) -> AuditLogResponse:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        items = [
            AuditLogItem(
                audit_id=row["audit_id"],
                actor_id=row["actor_id"],
                actor_role=row["actor_role"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                details=json.loads(row["details_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
        return AuditLogResponse(count=len(items), items=items)

    def create_incident(
        self,
        mission_id: str,
        driver_id: str,
        incident_type: str,
        description: str,
        sequence: int | None,
        location: Location | None,
        evidence_photo_url: str | None,
        client_event_id: str | None,
    ) -> MissionIncident:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            self._verify_driver(mission, driver_id)
            if client_event_id:
                existing = self._connection.execute(
                    "SELECT * FROM mission_incidents WHERE client_event_id = ?",
                    (client_event_id,),
                ).fetchone()
                if existing:
                    return self._incident_from_row(existing)
            if sequence is not None:
                stop = self._connection.execute(
                    "SELECT 1 FROM mission_stops WHERE mission_id = ? AND sequence = ?",
                    (mission_id, sequence),
                ).fetchone()
                if stop is None:
                    raise OperationError(404, "신고할 정차지를 찾을 수 없습니다.")
            incident_id = f"incident-{uuid.uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO mission_incidents (
                    incident_id, mission_id, sequence, driver_id, incident_type,
                    description, lat, lng, evidence_photo_url, client_event_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    mission_id,
                    sequence,
                    driver_id,
                    incident_type,
                    description,
                    location.lat if location else None,
                    location.lng if location else None,
                    evidence_photo_url,
                    client_event_id,
                    _utc_now(),
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM mission_incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
            return self._incident_from_row(row)

    def list_incidents(
        self, mission_id: str | None = None, status: str | None = None
    ) -> MissionIncidentListResponse:
        clauses = []
        values: list[str] = []
        if mission_id:
            clauses.append("mission_id = ?")
            values.append(mission_id)
        if status:
            if status not in {"open", "resolved"}:
                raise OperationError(422, "지원하지 않는 사고 상태입니다.")
            clauses.append("status = ?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM mission_incidents{where} ORDER BY created_at DESC",
                values,
            ).fetchall()
        incidents = [self._incident_from_row(row) for row in rows]
        return MissionIncidentListResponse(count=len(incidents), incidents=incidents)

    def cancel_mission(self, mission_id: str, reason: str) -> MissionDetail:
        with self._lock, self._connection:
            row = self._mission_row(mission_id)
            status = self._effective_mission_status(row)
            if status == "completed":
                raise OperationError(409, "완료된 미션은 취소할 수 없습니다.")
            if status != "cancelled":
                self._connection.execute(
                    "UPDATE missions SET cancelled_at = ?, cancelled_reason = ? "
                    "WHERE mission_id = ?",
                    (_utc_now(), reason, mission_id),
                )
                self._notify_locked(
                    row["driver_id"],
                    "mission.cancelled",
                    "미션 취소",
                    reason,
                    {"mission_id": mission_id},
                )
            return self._get_mission_locked(mission_id)

    def reassign_mission(
        self,
        mission_id: str,
        driver_id: str,
        driver_name: str,
        reason: str,
    ) -> MissionDetail:
        with self._lock, self._connection:
            row = self._mission_row(mission_id)
            if self._effective_mission_status(row) not in {"offered", "accepted"}:
                raise OperationError(409, "시작 전 미션만 재배정할 수 있습니다.")
            old_driver = row["driver_id"]
            route = DriverRouteOutput.model_validate_json(row["route_json"])
            route = route.model_copy(
                update={"driver_id": driver_id, "driver_name": driver_name}
            )
            self._connection.execute(
                """
                UPDATE missions SET driver_id = ?, driver_name = ?, status = 'offered',
                    accepted_at = NULL, route_json = ? WHERE mission_id = ?
                """,
                (driver_id, driver_name, route.model_dump_json(), mission_id),
            )
            self._notify_locked(
                old_driver,
                "mission.reassigned",
                "미션 재배정",
                reason,
                {"mission_id": mission_id, "new_driver_id": driver_id},
            )
            self._notify_locked(
                driver_id,
                "mission.offered",
                "재배치 미션 배정",
                reason,
                {"mission_id": mission_id},
            )
            return self._get_mission_locked(mission_id)

    def supersede_plan(self, old_plan_id: str, new_plan_id: str) -> int:
        if old_plan_id == new_plan_id:
            raise OperationError(409, "재계획 결과가 기존 계획과 동일합니다.")
        with self._lock, self._connection:
            rows = self._connection.execute(
                "SELECT * FROM missions WHERE plan_id = ? AND status != 'completed' "
                "AND cancelled_at IS NULL",
                (old_plan_id,),
            ).fetchall()
            now = _utc_now()
            for row in rows:
                self._connection.execute(
                    "UPDATE missions SET cancelled_at = ?, cancelled_reason = ? "
                    "WHERE mission_id = ?",
                    (now, f"새 계획 {new_plan_id}으로 대체", row["mission_id"]),
                )
                self._notify_locked(
                    row["driver_id"],
                    "mission.superseded",
                    "재배치 경로 갱신",
                    "재고 또는 운행 상황 변경으로 기존 미션이 교체되었습니다.",
                    {"old_mission_id": row["mission_id"], "new_plan_id": new_plan_id},
                )
            return len(rows)

    def skip_stop(self, mission_id: str, sequence: int, reason: str) -> MissionDetail:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            if self._effective_mission_status(mission) != "in_progress":
                raise OperationError(409, "진행 중인 미션의 정차지만 건너뛸 수 있습니다.")
            next_stop = self._connection.execute(
                "SELECT * FROM mission_stops WHERE mission_id = ? "
                "AND status = 'pending' ORDER BY sequence LIMIT 1",
                (mission_id,),
            ).fetchone()
            if next_stop is None or next_stop["sequence"] != sequence:
                raise OperationError(409, "현재 순서의 정차지만 건너뛸 수 있습니다.")
            self._connection.execute(
                """
                UPDATE mission_stops SET status = 'completed', actual_quantity = 0,
                    bike_qr_count = 0, skipped_reason = ?, completed_at = ?
                WHERE mission_id = ? AND sequence = ?
                """,
                (reason, _utc_now(), mission_id, sequence),
            )
            remaining = self._connection.execute(
                "SELECT COUNT(*) FROM mission_stops WHERE mission_id = ? "
                "AND status = 'pending'",
                (mission_id,),
            ).fetchone()[0]
            if remaining == 0:
                self._finalize_locked(mission_id)
            return self._get_mission_locked(mission_id)

    def report_bike_damage(
        self,
        bike_qr_code: str,
        mission_id: str | None,
        reported_by: str,
        description: str,
        location: Location | None,
        evidence_photo_url: str | None,
    ) -> BikeDamageReport:
        with self._lock, self._connection:
            report_id = f"damage-{uuid.uuid4().hex}"
            bike_hash = self._bike_qr_hashes([bike_qr_code])[0]
            now = _utc_now()
            self._connection.execute(
                """
                INSERT INTO bike_damage_reports (
                    report_id, bike_qr_hash, mission_id, reported_by, description,
                    lat, lng, evidence_photo_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    bike_hash,
                    mission_id,
                    reported_by,
                    description,
                    location.lat if location else None,
                    location.lng if location else None,
                    evidence_photo_url,
                    now,
                ),
            )
            return BikeDamageReport(
                report_id=report_id,
                bike_qr_fingerprint=bike_hash[:16],
                mission_id=mission_id,
                reported_by=reported_by,
                description=description,
                status="open",
                created_at=now,
            )

    def list_missions(
        self,
        driver_id: str | None = None,
        status: str | None = None,
    ) -> MissionListResponse:
        if status is not None and status not in {
            "offered",
            "accepted",
            "in_progress",
            "completed",
            "cancelled",
        }:
            raise OperationError(422, "지원하지 않는 미션 상태입니다.")
        clauses: list[str] = []
        values: list[str] = []
        if driver_id:
            clauses.append("driver_id = ?")
            values.append(driver_id)
        if status == "cancelled":
            clauses.append("cancelled_at IS NOT NULL")
        elif status:
            clauses.append("status = ?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM missions{where} ORDER BY offered_at DESC", values
            ).fetchall()
            missions = [self._summary_from_row(row) for row in rows]
        return MissionListResponse(count=len(missions), missions=missions)

    def get_mission(self, mission_id: str) -> MissionDetail:
        with self._lock:
            return self._get_mission_locked(mission_id)

    def accept_mission(self, mission_id: str, driver_id: str) -> MissionDetail:
        with self._lock, self._connection:
            row = self._mission_row(mission_id)
            self._verify_driver(row, driver_id)
            effective_status = self._effective_mission_status(row)
            if effective_status == "cancelled":
                raise OperationError(409, "취소된 미션입니다.")
            if row["status"] == "offered":
                self._connection.execute(
                    "UPDATE missions SET status = 'accepted', accepted_at = ? "
                    "WHERE mission_id = ?",
                    (_utc_now(), mission_id),
                )
            elif row["status"] not in {"accepted", "in_progress", "completed"}:
                raise OperationError(409, "수락할 수 없는 미션 상태입니다.")
            return self._get_mission_locked(mission_id)

    def start_mission(self, mission_id: str, driver_id: str) -> MissionDetail:
        with self._lock, self._connection:
            row = self._mission_row(mission_id)
            self._verify_driver(row, driver_id)
            if self._effective_mission_status(row) == "cancelled":
                raise OperationError(409, "취소된 미션입니다.")
            if row["status"] == "accepted":
                self._connection.execute(
                    "UPDATE missions SET status = 'in_progress', started_at = ? "
                    "WHERE mission_id = ?",
                    (_utc_now(), mission_id),
                )
            elif row["status"] not in {"in_progress", "completed"}:
                raise OperationError(409, "먼저 미션을 수락해야 합니다.")
            return self._get_mission_locked(mission_id)

    def complete_stop(
        self,
        mission_id: str,
        sequence: int,
        driver_id: str,
        location: Location,
        actual_quantity: int,
        bike_qr_codes: list[str],
        evidence_photo_url: str | None,
    ) -> MissionDetail:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            self._verify_driver(mission, driver_id)
            stop = self._connection.execute(
                "SELECT * FROM mission_stops WHERE mission_id = ? AND sequence = ?",
                (mission_id, sequence),
            ).fetchone()
            if stop is None:
                raise OperationError(404, "미션 정차지를 찾을 수 없습니다.")
            if stop["status"] == "completed":
                return self._get_mission_locked(mission_id)
            if self._effective_mission_status(mission) != "in_progress":
                raise OperationError(409, "진행 중인 미션에서만 정차 완료가 가능합니다.")

            next_stop = self._connection.execute(
                """
                SELECT sequence FROM mission_stops
                WHERE mission_id = ? AND status = 'pending'
                ORDER BY sequence LIMIT 1
                """,
                (mission_id,),
            ).fetchone()
            if next_stop is None or next_stop["sequence"] != sequence:
                expected = next_stop["sequence"] if next_stop else "없음"
                raise OperationError(
                    409, f"정차 순서가 맞지 않습니다. 다음 순서는 {expected}입니다."
                )
            if actual_quantity > stop["planned_quantity"]:
                raise OperationError(422, "실제 수량은 계획 수량을 초과할 수 없습니다.")

            bike_hashes = self._bike_qr_hashes(bike_qr_codes)
            if len(bike_hashes) != actual_quantity:
                raise OperationError(
                    422, "스캔한 자전거 QR 개수와 실제 처리 수량이 일치해야 합니다."
                )

            distance_meters = self._distance_from_stop(stop, location)
            if distance_meters > self.config.gps_radius_meters:
                raise OperationError(
                    422,
                    "대여소에서 너무 멉니다. "
                    f"현재 {distance_meters:.0f}m, 허용 {self.config.gps_radius_meters}m",
                )

            current_load = self._current_vehicle_load(mission_id)
            route = DriverRouteOutput.model_validate_json(mission["route_json"])
            if stop["action"] == "pickup":
                if current_load + actual_quantity > route.vehicle_capacity:
                    raise OperationError(422, "차량 적재 용량을 초과합니다.")
                for bike_hash in bike_hashes:
                    exists = self._connection.execute(
                        "SELECT 1 FROM mission_bikes "
                        "WHERE mission_id = ? AND bike_qr_hash = ?",
                        (mission_id, bike_hash),
                    ).fetchone()
                    if exists:
                        raise OperationError(
                            409, "이미 이 미션에서 처리한 자전거 QR이 포함되어 있습니다."
                        )
            else:
                if actual_quantity > current_load:
                    raise OperationError(
                        422, "차량에 실린 자전거보다 많이 하차할 수 없습니다."
                    )
                self._require_fresh_station_qr(stop)
                for bike_hash in bike_hashes:
                    bike = self._connection.execute(
                        """
                        SELECT status FROM mission_bikes
                        WHERE mission_id = ? AND bike_qr_hash = ?
                        """,
                        (mission_id, bike_hash),
                    ).fetchone()
                    if bike is None or bike["status"] != "loaded":
                        raise OperationError(
                            422, "차량에 적재 확인되지 않은 자전거 QR이 포함되어 있습니다."
                        )

            completed_at = _utc_now()
            self._connection.execute(
                """
                UPDATE mission_stops
                SET status = 'completed', actual_quantity = ?, completed_lat = ?,
                    completed_lng = ?, distance_from_station_meters = ?,
                    evidence_photo_url = ?, completed_at = ?, bike_qr_count = ?
                WHERE mission_id = ? AND sequence = ?
                """,
                (
                    actual_quantity,
                    location.lat,
                    location.lng,
                    distance_meters,
                    evidence_photo_url,
                    completed_at,
                    len(bike_hashes),
                    mission_id,
                    sequence,
                ),
            )
            if stop["action"] == "pickup":
                self._connection.executemany(
                    """
                    INSERT INTO mission_bikes (
                        mission_id, bike_qr_hash, status, pickup_sequence, picked_at
                    ) VALUES (?, ?, 'loaded', ?, ?)
                    """,
                    [
                        (mission_id, bike_hash, sequence, completed_at)
                        for bike_hash in bike_hashes
                    ],
                )
            else:
                self._connection.executemany(
                    """
                    UPDATE mission_bikes SET status = 'dropped', dropoff_sequence = ?,
                                             dropped_at = ?
                    WHERE mission_id = ? AND bike_qr_hash = ?
                    """,
                    [
                        (sequence, completed_at, mission_id, bike_hash)
                        for bike_hash in bike_hashes
                    ],
                )
            remaining = self._connection.execute(
                "SELECT COUNT(*) FROM mission_stops "
                "WHERE mission_id = ? AND status = 'pending'",
                (mission_id,),
            ).fetchone()[0]
            if remaining == 0:
                self._finalize_locked(mission_id)
            return self._get_mission_locked(mission_id)

    def _bike_qr_hashes(self, bike_qr_codes: list[str]) -> list[str]:
        normalized = [code.strip() for code in bike_qr_codes]
        if any(not code for code in normalized):
            raise OperationError(422, "빈 자전거 QR 값은 사용할 수 없습니다.")
        hashes = [
            hmac.new(self._qr_secret, code.encode(), hashlib.sha256).hexdigest()
            for code in normalized
        ]
        if len(hashes) != len(set(hashes)):
            raise OperationError(422, "같은 자전거 QR을 중복 스캔할 수 없습니다.")
        return hashes

    def _require_fresh_station_qr(self, stop: sqlite3.Row) -> None:
        if stop["qr_status"] != "verified" or not stop["qr_verified_at"]:
            raise OperationError(409, "반납 대여소 QR을 먼저 인증해야 합니다.")
        verified_at = datetime.fromisoformat(stop["qr_verified_at"])
        expires_at = verified_at + timedelta(
            seconds=self.config.qr_verification_ttl_seconds
        )
        if datetime.now(timezone.utc) > expires_at:
            raise OperationError(409, "대여소 QR 인증이 만료되었습니다. 다시 스캔하세요.")

    @staticmethod
    def _distance_from_stop(stop: sqlite3.Row, location: Location) -> float:
        return haversine_km(
            location,
            Location(lat=stop["lat"], lng=stop["lng"]),
        ) * 1000

    def complete_mission(self, mission_id: str, driver_id: str) -> MissionDetail:
        with self._lock, self._connection:
            mission = self._mission_row(mission_id)
            self._verify_driver(mission, driver_id)
            effective_status = self._effective_mission_status(mission)
            if effective_status == "completed":
                return self._get_mission_locked(mission_id)
            if effective_status != "in_progress":
                raise OperationError(409, "진행 중인 미션만 완료할 수 있습니다.")
            pending = self._connection.execute(
                "SELECT COUNT(*) FROM mission_stops "
                "WHERE mission_id = ? AND status = 'pending'",
                (mission_id,),
            ).fetchone()[0]
            if pending:
                raise OperationError(409, f"완료하지 않은 정차지가 {pending}개 있습니다.")
            self._finalize_locked(mission_id)
            return self._get_mission_locked(mission_id)

    def get_wallet(self, driver_id: str) -> RewardWallet:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN status = 'approved' THEN points ELSE 0 END), 0) AS points,
                    COALESCE(SUM(CASE WHEN status = 'pending' THEN points ELSE 0 END), 0) AS pending_points,
                    COALESCE(SUM(CASE WHEN status = 'reversed' THEN points ELSE 0 END), 0) AS reversed_points,
                    COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS mission_count,
                       MAX(created_at) AS updated_at
                FROM reward_ledger WHERE driver_id = ?
                """,
                (driver_id,),
            ).fetchone()
        return RewardWallet(
            driver_id=driver_id,
            balance_points=row["points"],
            lifetime_earned_points=row["points"] + row["reversed_points"],
            completed_mission_count=row["mission_count"],
            pending_points=row["pending_points"],
            reversed_points=row["reversed_points"],
            updated_at=row["updated_at"],
        )

    def list_transactions(self, driver_id: str) -> RewardTransactionListResponse:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM reward_ledger WHERE driver_id = ? "
                "ORDER BY created_at DESC",
                (driver_id,),
            ).fetchall()
        transactions = [self._transaction_from_row(row) for row in rows]
        return RewardTransactionListResponse(
            count=len(transactions), transactions=transactions
        )

    def list_reward_reviews(
        self, status: str = "pending"
    ) -> RewardTransactionListResponse:
        if status not in {"pending", "approved", "rejected", "reversed"}:
            raise OperationError(422, "지원하지 않는 리워드 상태입니다.")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM reward_ledger WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
        transactions = [self._transaction_from_row(row) for row in rows]
        return RewardTransactionListResponse(
            count=len(transactions), transactions=transactions
        )

    def review_reward(
        self,
        transaction_id: str,
        decision: str,
        reviewer_id: str,
        reason: str,
    ) -> RewardTransaction:
        if decision not in {"approved", "rejected", "reversed"}:
            raise OperationError(422, "지원하지 않는 리워드 결정입니다.")
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM reward_ledger WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if row is None:
                raise OperationError(404, "리워드 거래를 찾을 수 없습니다.")
            current = row["status"]
            if current == decision:
                return self._transaction_from_row(row)
            allowed = (current == "pending" and decision in {"approved", "rejected"}) or (
                current == "approved" and decision == "reversed"
            )
            if not allowed:
                raise OperationError(
                    409, f"리워드를 {current}에서 {decision}(으)로 변경할 수 없습니다."
                )
            now = _utc_now()
            self._connection.execute(
                """
                UPDATE reward_ledger SET status = ?, reviewed_at = ?,
                    reviewed_by = ?, review_reason = ? WHERE transaction_id = ?
                """,
                (decision, now, reviewer_id, reason, transaction_id),
            )
            self._notify_locked(
                row["driver_id"],
                f"reward.{decision}",
                "리워드 상태 변경",
                f"미션 리워드 {row['points']}P가 {decision} 처리되었습니다.",
                {"transaction_id": transaction_id, "status": decision},
            )
            updated = self._connection.execute(
                "SELECT * FROM reward_ledger WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            return self._transaction_from_row(updated)

    def leaderboard(self, limit: int = 20) -> LeaderboardResponse:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT r.driver_id, MAX(m.driver_name) AS driver_name,
                       SUM(r.points) AS points, COUNT(*) AS mission_count
                FROM reward_ledger r
                JOIN missions m ON m.mission_id = r.mission_id
                WHERE r.status = 'approved'
                GROUP BY r.driver_id
                ORDER BY points DESC, mission_count DESC, r.driver_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        entries = [
            LeaderboardEntry(
                rank=index,
                driver_id=row["driver_id"],
                driver_name=row["driver_name"],
                points=row["points"],
                completed_mission_count=row["mission_count"],
            )
            for index, row in enumerate(rows, start=1)
        ]
        return LeaderboardResponse(count=len(entries), entries=entries)

    def bootstrap(self, driver_id: str) -> DriverBootstrapResponse:
        return DriverBootstrapResponse(
            driver_id=driver_id,
            missions=self.list_missions(driver_id=driver_id).missions,
            wallet=self.get_wallet(driver_id),
        )

    def record_driver_location(
        self,
        driver_id: str,
        location: Location,
        recorded_at: datetime,
        accuracy_meters: float,
        speed_kmh: float | None,
        device_id: str,
    ) -> DriverLivePosition:
        now = datetime.now(timezone.utc)
        if recorded_at.tzinfo is None:
            raise OperationError(422, "위치 시간에는 timezone offset이 필요합니다.")
        if recorded_at > now + timedelta(minutes=2):
            raise OperationError(422, "미래 시각의 위치는 등록할 수 없습니다.")
        if recorded_at < now - timedelta(hours=24):
            raise OperationError(422, "24시간보다 오래된 위치는 등록할 수 없습니다.")
        with self._lock, self._connection:
            previous = self._connection.execute(
                "SELECT * FROM driver_locations WHERE driver_id = ? "
                "ORDER BY recorded_at DESC LIMIT 1",
                (driver_id,),
            ).fetchone()
            anomaly = None
            if accuracy_meters > 200:
                anomaly = "low_gps_accuracy"
            if previous:
                elapsed = (
                    recorded_at - datetime.fromisoformat(previous["recorded_at"])
                ).total_seconds()
                if elapsed > 0:
                    distance = haversine_km(
                        Location(lat=previous["lat"], lng=previous["lng"]),
                        location,
                    )
                    derived_speed = distance / elapsed * 3600
                    if derived_speed > 160:
                        anomaly = "impossible_travel_speed"
            self._connection.execute(
                """
                INSERT INTO driver_locations (
                    location_id, driver_id, lat, lng, accuracy_meters, speed_kmh,
                    device_id, anomaly, recorded_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"location-{uuid.uuid4().hex}",
                    driver_id,
                    location.lat,
                    location.lng,
                    accuracy_meters,
                    speed_kmh,
                    device_id,
                    anomaly,
                    recorded_at.isoformat(),
                    now.isoformat(),
                ),
            )
            active = self._connection.execute(
                "SELECT mission_id FROM missions WHERE driver_id = ? "
                "AND status = 'in_progress' AND cancelled_at IS NULL LIMIT 1",
                (driver_id,),
            ).fetchone()
        return DriverLivePosition(
            driver_id=driver_id,
            location=location,
            recorded_at=recorded_at,
            accuracy_meters=accuracy_meters,
            speed_kmh=speed_kmh,
            anomaly=anomaly,
            active_mission_id=active["mission_id"] if active else None,
        )

    def live_operations(self) -> LiveOperationsResponse:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT dl.* FROM driver_locations dl
                WHERE dl.recorded_at = (
                    SELECT MAX(inner_dl.recorded_at) FROM driver_locations inner_dl
                    WHERE inner_dl.driver_id = dl.driver_id
                ) ORDER BY dl.driver_id
                """
            ).fetchall()
            drivers = []
            for row in rows:
                active = self._connection.execute(
                    "SELECT mission_id FROM missions WHERE driver_id = ? "
                    "AND status = 'in_progress' AND cancelled_at IS NULL LIMIT 1",
                    (row["driver_id"],),
                ).fetchone()
                drivers.append(
                    DriverLivePosition(
                        driver_id=row["driver_id"],
                        location=Location(lat=row["lat"], lng=row["lng"]),
                        recorded_at=row["recorded_at"],
                        accuracy_meters=row["accuracy_meters"],
                        speed_kmh=row["speed_kmh"],
                        anomaly=row["anomaly"],
                        active_mission_id=active["mission_id"] if active else None,
                    )
                )
        return LiveOperationsResponse(count=len(drivers), drivers=drivers)

    def list_notifications(
        self, driver_id: str, unread_only: bool = False
    ) -> NotificationListResponse:
        where = " AND read_at IS NULL" if unread_only else ""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM notifications WHERE driver_id = ?"
                f"{where} ORDER BY created_at DESC",
                (driver_id,),
            ).fetchall()
        notifications = [self._notification_from_row(row) for row in rows]
        return NotificationListResponse(
            count=len(notifications), notifications=notifications
        )

    def mark_notification_read(
        self, notification_id: str, driver_id: str
    ) -> NotificationItem:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM notifications WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
            if row is None:
                raise OperationError(404, "알림을 찾을 수 없습니다.")
            if row["driver_id"] != driver_id:
                raise OperationError(403, "다른 기사의 알림입니다.")
            self._connection.execute(
                "UPDATE notifications SET read_at = COALESCE(read_at, ?) "
                "WHERE notification_id = ?",
                (_utc_now(), notification_id),
            )
            updated = self._connection.execute(
                "SELECT * FROM notifications WHERE notification_id = ?",
                (notification_id,),
            ).fetchone()
        return self._notification_from_row(updated)

    def analytics(self) -> OperationsAnalytics:
        with self._lock:
            mission_rows = self._connection.execute(
                """
                SELECT CASE WHEN cancelled_at IS NOT NULL THEN 'cancelled' ELSE status END AS effective_status,
                       COUNT(*) AS count FROM missions GROUP BY effective_status
                """
            ).fetchall()
            reward_rows = self._connection.execute(
                "SELECT status, COALESCE(SUM(points), 0) AS points "
                "FROM reward_ledger GROUP BY status"
            ).fetchall()
            incident_rows = self._connection.execute(
                "SELECT status, COUNT(*) AS count FROM mission_incidents GROUP BY status"
            ).fetchall()
            bikes = self._connection.execute(
                "SELECT COALESCE(SUM(actual_quantity), 0) FROM mission_stops "
                "WHERE action = 'dropoff' AND status = 'completed'"
            ).fetchone()[0]
            active = self._connection.execute(
                "SELECT COUNT(DISTINCT driver_id) FROM missions "
                "WHERE status = 'in_progress' AND cancelled_at IS NULL"
            ).fetchone()[0]
        return OperationsAnalytics(
            mission_counts={row["effective_status"]: row["count"] for row in mission_rows},
            reward_points={row["status"]: row["points"] for row in reward_rows},
            incident_counts={row["status"]: row["count"] for row in incident_rows},
            total_bikes_delivered=bikes,
            active_driver_count=active,
        )

    def create_settlement(
        self,
        period_start: datetime,
        period_end: datetime,
        created_by: str,
    ) -> SettlementBatch:
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT * FROM reward_ledger
                WHERE status = 'approved' AND settlement_id IS NULL
                  AND created_at >= ? AND created_at < ?
                ORDER BY created_at
                """,
                (period_start.isoformat(), period_end.isoformat()),
            ).fetchall()
            if not rows:
                raise OperationError(409, "정산할 승인 리워드가 없습니다.")
            settlement_id = f"settlement-{uuid.uuid4().hex}"
            now = _utc_now()
            total = sum(row["points"] for row in rows)
            self._connection.execute(
                """
                INSERT INTO settlements (
                    settlement_id, period_start, period_end, total_points,
                    transaction_count, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    settlement_id,
                    period_start.isoformat(),
                    period_end.isoformat(),
                    total,
                    len(rows),
                    created_by,
                    now,
                ),
            )
            self._connection.executemany(
                "UPDATE reward_ledger SET settlement_id = ? WHERE transaction_id = ?",
                [(settlement_id, row["transaction_id"]) for row in rows],
            )
            return self._settlement_locked(settlement_id)

    def get_settlement(self, settlement_id: str) -> SettlementBatch:
        with self._lock:
            return self._settlement_locked(settlement_id)

    def mark_settlement_paid(
        self, settlement_id: str, actor_id: str
    ) -> SettlementBatch:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT * FROM settlements WHERE settlement_id = ?",
                (settlement_id,),
            ).fetchone()
            if row is None:
                raise OperationError(404, "정산 배치를 찾을 수 없습니다.")
            if row["status"] != "paid":
                self._connection.execute(
                    "UPDATE settlements SET status = 'paid', paid_at = ? "
                    "WHERE settlement_id = ?",
                    (_utc_now(), settlement_id),
                )
                driver_rows = self._connection.execute(
                    "SELECT DISTINCT driver_id FROM reward_ledger "
                    "WHERE settlement_id = ?",
                    (settlement_id,),
                ).fetchall()
                for driver in driver_rows:
                    self._notify_locked(
                        driver["driver_id"],
                        "settlement.paid",
                        "포인트 정산 완료",
                        "승인된 포인트 정산이 완료되었습니다.",
                        {"settlement_id": settlement_id, "actor_id": actor_id},
                    )
            return self._settlement_locked(settlement_id)

    def _settlement_locked(self, settlement_id: str) -> SettlementBatch:
        row = self._connection.execute(
            "SELECT * FROM settlements WHERE settlement_id = ?", (settlement_id,)
        ).fetchone()
        if row is None:
            raise OperationError(404, "정산 배치를 찾을 수 없습니다.")
        driver_rows = self._connection.execute(
            """
            SELECT driver_id, SUM(points) AS points, COUNT(*) AS transaction_count
            FROM reward_ledger WHERE settlement_id = ? GROUP BY driver_id
            ORDER BY driver_id
            """,
            (settlement_id,),
        ).fetchall()
        return SettlementBatch(
            settlement_id=row["settlement_id"],
            status=row["status"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            total_points=row["total_points"],
            transaction_count=row["transaction_count"],
            drivers=[
                SettlementDriverTotal(
                    driver_id=driver["driver_id"],
                    points=driver["points"],
                    transaction_count=driver["transaction_count"],
                )
                for driver in driver_rows
            ],
            created_by=row["created_by"],
            created_at=row["created_at"],
            paid_at=row["paid_at"],
        )

    def get_offline_event(self, event_id: str, driver_id: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM offline_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        if row["driver_id"] != driver_id:
            raise OperationError(403, "다른 기기의 오프라인 이벤트 ID입니다.")
        return {
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }

    def record_offline_event(
        self,
        event_id: str,
        driver_id: str,
        event_type: str,
        status: str,
        result: dict | None,
        error: str | None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO offline_events (
                    event_id, driver_id, event_type, status, result_json,
                    error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    driver_id,
                    event_type,
                    status,
                    json.dumps(result, ensure_ascii=False) if result else None,
                    error,
                    _utc_now(),
                ),
            )

    def _notify_locked(
        self,
        driver_id: str,
        notification_type: str,
        title: str,
        body: str,
        data: dict,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO notifications (
                notification_id, driver_id, notification_type, title, body,
                data_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"notification-{uuid.uuid4().hex}",
                driver_id,
                notification_type,
                title,
                body,
                json.dumps(data, ensure_ascii=False),
                _utc_now(),
            ),
        )

    @staticmethod
    def _notification_from_row(row: sqlite3.Row) -> NotificationItem:
        return NotificationItem(
            notification_id=row["notification_id"],
            driver_id=row["driver_id"],
            notification_type=row["notification_type"],
            title=row["title"],
            body=row["body"],
            data=json.loads(row["data_json"]),
            created_at=row["created_at"],
            read_at=row["read_at"],
        )

    @staticmethod
    def _incident_from_row(row: sqlite3.Row) -> MissionIncident:
        return MissionIncident(
            incident_id=row["incident_id"],
            mission_id=row["mission_id"],
            sequence=row["sequence"],
            driver_id=row["driver_id"],
            incident_type=row["incident_type"],
            description=row["description"],
            location=(
                Location(lat=row["lat"], lng=row["lng"])
                if row["lat"] is not None
                else None
            ),
            evidence_photo_url=row["evidence_photo_url"],
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def _reward_for_route(self, route: DriverRouteOutput) -> RewardBreakdown:
        deliveries = [stop for stop in route.stops if stop.action == "dropoff"]
        delivered = sum(stop.quantity for stop in deliveries)
        base = delivered * self.config.points_per_bike
        priority = round(
            sum(
                stop.quantity
                * stop.shortage_pressure
                * self.config.priority_points_per_bike
                for stop in deliveries
            )
        )
        completion = self.config.full_completion_bonus_points if deliveries else 0
        return RewardBreakdown(
            base_points=base,
            priority_bonus_points=priority,
            completion_bonus_points=completion,
            total_points=base + priority + completion,
        )

    def _actual_reward_locked(self, mission_id: str) -> RewardBreakdown:
        rows = self._connection.execute(
            "SELECT * FROM mission_stops WHERE mission_id = ? AND action = 'dropoff'",
            (mission_id,),
        ).fetchall()
        actual = sum(row["actual_quantity"] or 0 for row in rows)
        planned = sum(row["planned_quantity"] for row in rows)
        base = actual * self.config.points_per_bike
        priority = round(
            sum(
                (row["actual_quantity"] or 0)
                * row["shortage_pressure"]
                * self.config.priority_points_per_bike
                for row in rows
            )
        )
        completion = (
            self.config.full_completion_bonus_points
            if rows and actual == planned
            else 0
        )
        return RewardBreakdown(
            base_points=base,
            priority_bonus_points=priority,
            completion_bonus_points=completion,
            total_points=base + priority + completion,
        )

    def _finalize_locked(self, mission_id: str) -> None:
        mission = self._mission_row(mission_id)
        if mission["status"] == "completed":
            return
        reward = self._actual_reward_locked(mission_id)
        now = _utc_now()
        fraud_score = self._fraud_score_locked(mission_id)
        reward_status = "approved" if self.config.reward_auto_approve else "pending"
        self._connection.execute(
            """
            INSERT OR IGNORE INTO reward_ledger (
                transaction_id, driver_id, mission_id, points, reason,
                breakdown_json, status, reviewed_at, reviewed_by, review_reason,
                fraud_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"reward-{mission_id}",
                mission["driver_id"],
                mission_id,
                reward.total_points,
                "재배치 미션 완료",
                reward.model_dump_json(),
                reward_status,
                now if reward_status == "approved" else None,
                "system" if reward_status == "approved" else None,
                "자동 승인 정책" if reward_status == "approved" else None,
                fraud_score,
                now,
            ),
        )
        ledger = self._connection.execute(
            "SELECT breakdown_json, created_at FROM reward_ledger WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()
        self._connection.execute(
            """
            UPDATE missions SET status = 'completed', awarded_reward_json = ?,
                                completed_at = ?
            WHERE mission_id = ?
            """,
            (ledger["breakdown_json"], ledger["created_at"], mission_id),
        )
        self._notify_locked(
            mission["driver_id"],
            "reward.pending" if reward_status == "pending" else "reward.approved",
            "재배치 미션 완료",
            (
                f"{reward.total_points}P가 검증 대기 중입니다."
                if reward_status == "pending"
                else f"{reward.total_points}P가 지급되었습니다."
            ),
            {"mission_id": mission_id, "status": reward_status},
        )

    def _fraud_score_locked(self, mission_id: str) -> int:
        incidents = self._connection.execute(
            "SELECT COUNT(*) FROM mission_incidents WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()[0]
        skipped = self._connection.execute(
            "SELECT COUNT(*) FROM mission_stops WHERE mission_id = ? "
            "AND skipped_reason IS NOT NULL",
            (mission_id,),
        ).fetchone()[0]
        return min(100, incidents * 10 + skipped * 15)

    def _current_vehicle_load(self, mission_id: str) -> int:
        rows = self._connection.execute(
            """
            SELECT action, actual_quantity FROM mission_stops
            WHERE mission_id = ? AND status = 'completed' ORDER BY sequence
            """,
            (mission_id,),
        ).fetchall()
        return sum(
            (row["actual_quantity"] or 0)
            * (1 if row["action"] == "pickup" else -1)
            for row in rows
        )

    def _mission_row(self, mission_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM missions WHERE mission_id = ?", (mission_id,)
        ).fetchone()
        if row is None:
            raise OperationError(404, "미션을 찾을 수 없습니다.")
        return row

    @staticmethod
    def _effective_mission_status(row: sqlite3.Row) -> str:
        return "cancelled" if row["cancelled_at"] else row["status"]

    @staticmethod
    def _verify_driver(row: sqlite3.Row, driver_id: str) -> None:
        if row["driver_id"] != driver_id:
            raise OperationError(403, "이 기사에게 배정된 미션이 아닙니다.")

    def _get_mission_locked(self, mission_id: str) -> MissionDetail:
        row = self._mission_row(mission_id)
        summary = self._summary_from_row(row)
        stops = self._stop_models(mission_id)
        return MissionDetail(
            **summary.model_dump(),
            stops=stops,
            route=DriverRouteOutput.model_validate_json(row["route_json"]),
            gps_completion_radius_meters=self.config.gps_radius_meters,
        )

    def _summary_from_row(self, row: sqlite3.Row) -> MissionSummary:
        stops = self._stop_models(row["mission_id"])
        first_pickup = next((stop for stop in stops if stop.action == "pickup"), None)
        reward_row = self._connection.execute(
            "SELECT status FROM reward_ledger WHERE mission_id = ?",
            (row["mission_id"],),
        ).fetchone()
        return MissionSummary(
            mission_id=row["mission_id"],
            plan_id=row["plan_id"],
            driver_id=row["driver_id"],
            driver_name=row["driver_name"],
            status=self._effective_mission_status(row),
            total_stops=len(stops),
            completed_stops=sum(stop.status != "pending" for stop in stops),
            planned_bikes=sum(
                stop.planned_quantity for stop in stops if stop.action == "dropoff"
            ),
            first_pickup=first_pickup,
            estimated_reward=RewardBreakdown.model_validate_json(
                row["estimated_reward_json"]
            ),
            awarded_reward=(
                RewardBreakdown.model_validate_json(row["awarded_reward_json"])
                if row["awarded_reward_json"]
                else None
            ),
            reward_status=reward_row["status"] if reward_row else None,
            cancelled_reason=row["cancelled_reason"],
            offered_at=row["offered_at"],
            accepted_at=row["accepted_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def _stop_models(self, mission_id: str) -> list[MissionStop]:
        rows = self._connection.execute(
            "SELECT * FROM mission_stops WHERE mission_id = ? ORDER BY sequence",
            (mission_id,),
        ).fetchall()
        return [
            MissionStop(
                sequence=row["sequence"],
                action=row["action"],
                station_id=row["station_id"],
                station_name=row["station_name"],
                location=Location(lat=row["lat"], lng=row["lng"]),
                planned_quantity=row["planned_quantity"],
                actual_quantity=row["actual_quantity"],
                status="skipped" if row["skipped_reason"] else row["status"],
                shortage_pressure=row["shortage_pressure"],
                qr_verification=row["qr_status"],
                qr_verified_at=row["qr_verified_at"],
                qr_verified_location=(
                    Location(lat=row["qr_verified_lat"], lng=row["qr_verified_lng"])
                    if row["qr_verified_lat"] is not None
                    else None
                ),
                bike_qr_count=row["bike_qr_count"],
                completed_location=(
                    Location(lat=row["completed_lat"], lng=row["completed_lng"])
                    if row["completed_lat"] is not None
                    else None
                ),
                distance_from_station_meters=row["distance_from_station_meters"],
                evidence_photo_url=row["evidence_photo_url"],
                skipped_reason=row["skipped_reason"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]

    @staticmethod
    def _transaction_from_row(row: sqlite3.Row) -> RewardTransaction:
        return RewardTransaction(
            transaction_id=row["transaction_id"],
            driver_id=row["driver_id"],
            mission_id=row["mission_id"],
            points=row["points"],
            reason=row["reason"],
            status=row["status"],
            reviewed_at=row["reviewed_at"],
            reviewed_by=row["reviewed_by"],
            review_reason=row["review_reason"],
            fraud_score=row["fraud_score"],
            settlement_id=row["settlement_id"],
            breakdown=RewardBreakdown.model_validate_json(row["breakdown_json"]),
            created_at=row["created_at"],
        )


def _mission_id(plan_id: str, driver_id: str) -> str:
    digest = hashlib.sha256(f"{plan_id}:{driver_id}".encode()).hexdigest()[:16]
    return f"mission-{digest}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid base64url") from exc
