from __future__ import annotations

import random
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from app.models import (
    ApiModel,
    CorePayload,
    DriverInput,
    Location,
    PlanRequest,
    PlanResponse,
    PlanningOptions,
)
from app.operations_models import MissionStatus, MissionStop


TEST_TMAP_APP_KEY = "L46IMLQYRu11AZhUXWRkz9Qarp01Bpm86xObCORB"

_DAEJEON_LAT_RANGE = (36.18, 36.50)
_DAEJEON_LNG_RANGE = (127.25, 127.56)
_KOREAN_DRIVER_NAMES = (
    "김민준",
    "이서준",
    "박도윤",
    "최예준",
    "정시우",
    "강주원",
    "조하준",
    "윤지호",
    "장현우",
    "임준서",
    "한도현",
    "오건우",
    "서우진",
    "신민재",
    "권태윤",
    "황지훈",
    "안승현",
    "송재원",
    "류성민",
    "홍진우",
)


class CoreTestScenarioRequest(ApiModel):
    """Legacy core-scenario payload kept for existing clients."""

    core: CorePayload
    drivers: list[DriverInput] | None = None
    driver_count: int = Field(default=2, ge=1, le=20)
    vehicle_capacity: int = Field(default=8, ge=1, le=100)
    start_at: datetime | None = None
    work_minutes: int = Field(default=240, ge=30, le=720)
    reserve_bikes_per_source: int = Field(default=2, ge=0, le=50)
    service_minutes_per_stop: float = Field(default=3, ge=0, le=60)
    use_tmap: bool = True

    @field_validator("start_at")
    @classmethod
    def start_at_needs_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("start_at must include a timezone offset")
        return value


class CoreModelSelection(ApiModel):
    date: date
    round_id: Literal["A", "B", "C", "D"]


class CreateTestScenarioRequest(ApiModel):
    core: CorePayload | None = None
    core_model: CoreModelSelection | None = None
    assumed_at: datetime
    driver_count_min: int = Field(default=2, ge=1, le=20)
    driver_count_max: int = Field(default=6, ge=1, le=20)
    random_seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    vehicle_capacity: int = Field(default=8, ge=1, le=100)
    work_minutes: int = Field(default=240, ge=30, le=720)
    reserve_bikes_per_source: int = Field(default=2, ge=0, le=50)
    service_minutes_per_stop: float = Field(default=3, ge=0, le=60)
    use_tmap: bool = True

    @field_validator("assumed_at")
    @classmethod
    def assumed_at_needs_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("assumed_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def one_core_source_and_valid_driver_range(self) -> "CreateTestScenarioRequest":
        if (self.core is None) == (self.core_model is None):
            raise ValueError("exactly one of core or core_model is required")
        if self.driver_count_min > self.driver_count_max:
            raise ValueError("driver_count_min must be less than or equal to driver_count_max")
        return self


class TestTmapConfig(ApiModel):
    configured: bool
    sdk_url: str | None = None


@dataclass(frozen=True)
class BuiltTestScenarioPlan:
    """Resolved, reproducible planning input used by the scenario API."""

    plan_request: PlanRequest
    random_seed: int
    drivers: tuple[DriverInput, ...]


class TestScenarioResponse(ApiModel):
    scenario_id: str = Field(min_length=1)
    assumed_at: datetime
    random_seed: int = Field(ge=0)
    created_at: datetime
    drivers: list[DriverInput]
    plan: PlanResponse

    @field_validator("assumed_at", "created_at")
    @classmethod
    def timestamps_need_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("scenario timestamps must include a timezone offset")
        return value


class TestDeviceBindingRequest(ApiModel):
    driver_id: str = Field(min_length=1)


class TestDeviceAssignment(ApiModel):
    device_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    driver_id: str = Field(min_length=1)
    driver_name: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    bound_at: datetime

    @field_validator("bound_at")
    @classmethod
    def bound_at_needs_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("bound_at must include a timezone offset")
        return value


class TestForcedArrival(ApiModel):
    scenario_id: str = Field(min_length=1)
    driver_id: str = Field(min_length=1)
    mission_id: str | None = None
    mission_status: MissionStatus | None = None
    current_location: Location | None = None
    next_stop: MissionStop | None = None
    arrived: bool = False
    movement_version: int = Field(default=0, ge=0)


class TestQrItem(ApiModel):
    qr_id: str = Field(min_length=1)
    kind: Literal["station", "bike"]
    label: str = Field(min_length=1)
    payload: str = Field(min_length=1)
    svg_data_url: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    stop_sequence: int = Field(ge=1)
    ordinal: int = Field(ge=1)
    total: int = Field(ge=1)
    station_id: str | None = None
    bike_id: str | None = None


class TestQrSequence(ApiModel):
    scenario_id: str = Field(min_length=1)
    driver_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    stop_sequence: int = Field(ge=1)
    stop_action: Literal["pickup", "dropoff"]
    current_index: int = Field(default=0, ge=0)
    items: list[TestQrItem] = Field(min_length=1)

    @model_validator(mode="after")
    def current_index_is_in_range(self) -> "TestQrSequence":
        if self.current_index >= len(self.items):
            raise ValueError("current_index must point to an item")
        return self


class TestScenarioRuntime:
    """Thread-safe, process-local state for a single active test scenario."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scenario: TestScenarioResponse | None = None
        self._bindings: dict[str, TestDeviceAssignment] = {}
        self._movement: dict[tuple[str, str], TestForcedArrival] = {}
        self._qr_sequences: dict[tuple[str, str, int], TestQrSequence] = {}
        self._bike_codes: dict[tuple[str, str, int], tuple[str, ...]] = {}

    def reset(self) -> None:
        with self._lock:
            self._scenario = None
            self._bindings.clear()
            self._movement.clear()
            self._qr_sequences.clear()
            self._bike_codes.clear()

    def set_scenario(self, scenario: TestScenarioResponse) -> TestScenarioResponse:
        with self._lock:
            self._scenario = scenario.model_copy(deep=True)
            self._bindings.clear()
            self._movement.clear()
            self._qr_sequences.clear()
            self._bike_codes.clear()
            return self._scenario.model_copy(deep=True)

    def get_scenario(self, scenario_id: str | None = None) -> TestScenarioResponse | None:
        with self._lock:
            if self._scenario is None:
                return None
            if scenario_id is not None and self._scenario.scenario_id != scenario_id:
                return None
            return self._scenario.model_copy(deep=True)

    def bind_device(
        self,
        device_id: str,
        scenario_id: str,
        driver_id: str,
    ) -> TestDeviceAssignment:
        with self._lock:
            scenario = self._require_scenario(scenario_id)
            driver = next(
                (item for item in scenario.drivers if item.driver_id == driver_id),
                None,
            )
            if driver is None:
                raise KeyError(f"unknown scenario driver: {driver_id}")
            previous = self._bindings.get(device_id)
            assignment = TestDeviceAssignment(
                device_id=device_id,
                scenario_id=scenario_id,
                driver_id=driver.driver_id,
                driver_name=driver.driver_name,
                plan_id=scenario.plan.plan_id,
                revision=(previous.revision + 1 if previous else 1),
                bound_at=datetime.now(timezone.utc),
            )
            self._bindings[device_id] = assignment
            return assignment.model_copy(deep=True)

    def get_assignment(self, device_id: str) -> TestDeviceAssignment | None:
        with self._lock:
            assignment = self._bindings.get(device_id)
            return assignment.model_copy(deep=True) if assignment else None

    def set_movement_state(
        self,
        scenario_id: str,
        driver_id: str,
        *,
        mission_id: str | None,
        mission_status: MissionStatus | None,
        current_location: Location | None,
        next_stop: MissionStop | None,
        arrived: bool,
    ) -> TestForcedArrival:
        with self._lock:
            scenario = self._require_scenario(scenario_id)
            if not any(item.driver_id == driver_id for item in scenario.drivers):
                raise KeyError(f"unknown scenario driver: {driver_id}")
            key = (scenario_id, driver_id)
            previous = self._movement.get(key)
            state = TestForcedArrival(
                scenario_id=scenario_id,
                driver_id=driver_id,
                mission_id=mission_id,
                mission_status=mission_status,
                current_location=current_location,
                next_stop=next_stop,
                arrived=arrived,
                movement_version=(previous.movement_version + 1 if previous else 1),
            )
            self._movement[key] = state
            return state.model_copy(deep=True)

    def get_movement_state(
        self,
        scenario_id: str,
        driver_id: str,
    ) -> TestForcedArrival | None:
        with self._lock:
            state = self._movement.get((scenario_id, driver_id))
            return state.model_copy(deep=True) if state else None

    def cache_qr_sequence(
        self,
        sequence: TestQrSequence,
        raw_bike_codes: list[str] | tuple[str, ...] | None = None,
    ) -> TestQrSequence:
        with self._lock:
            self._require_scenario(sequence.scenario_id)
            key = (
                sequence.scenario_id,
                sequence.mission_id,
                sequence.stop_sequence,
            )
            self._qr_sequences[key] = sequence.model_copy(deep=True)
            if raw_bike_codes is not None:
                self._bike_codes[key] = tuple(raw_bike_codes)
            return self._qr_sequences[key].model_copy(deep=True)

    def get_qr_sequence(
        self,
        scenario_id: str,
        mission_id: str,
        stop_sequence: int,
    ) -> TestQrSequence | None:
        with self._lock:
            sequence = self._qr_sequences.get(
                (scenario_id, mission_id, stop_sequence)
            )
            return sequence.model_copy(deep=True) if sequence else None

    def cache_bike_codes(
        self,
        scenario_id: str,
        mission_id: str,
        stop_sequence: int,
        raw_bike_codes: list[str] | tuple[str, ...],
    ) -> None:
        with self._lock:
            self._require_scenario(scenario_id)
            self._bike_codes[(scenario_id, mission_id, stop_sequence)] = tuple(
                raw_bike_codes
            )

    def get_bike_codes(
        self,
        scenario_id: str,
        mission_id: str,
        stop_sequence: int,
    ) -> list[str]:
        with self._lock:
            return list(
                self._bike_codes.get(
                    (scenario_id, mission_id, stop_sequence),
                    (),
                )
            )

    def _require_scenario(self, scenario_id: str) -> TestScenarioResponse:
        if self._scenario is None or self._scenario.scenario_id != scenario_id:
            raise KeyError(f"unknown test scenario: {scenario_id}")
        return self._scenario


def build_test_plan_request(request: CoreTestScenarioRequest) -> PlanRequest:
    start_at = request.start_at or datetime.now(ZoneInfo("Asia/Seoul")).replace(
        second=0, microsecond=0
    )
    end_at = start_at + timedelta(minutes=request.work_minutes)
    drivers = request.drivers or _virtual_drivers(request, start_at, end_at)
    return _make_plan_request(
        core=request.core,
        drivers=drivers,
        end_at=end_at,
        reserve_bikes_per_source=request.reserve_bikes_per_source,
        service_minutes_per_stop=request.service_minutes_per_stop,
        use_tmap=request.use_tmap,
    )


def build_scenario_plan_request(
    request: CreateTestScenarioRequest,
    resolved_core: CorePayload | None = None,
) -> BuiltTestScenarioPlan:
    """Build a seeded plan after the API resolves an optional core-model selector.

    ``resolved_core`` is required only when ``request.core_model`` was supplied.
    Keeping model-file lookup outside this module makes this builder deterministic
    and easy to test.
    """

    core = request.core or resolved_core
    if core is None:
        raise ValueError("resolved_core is required when core_model is selected")
    seed = request.random_seed
    if seed is None:
        seed = secrets.randbits(63)
    rng = random.Random(seed)
    driver_count = rng.randint(request.driver_count_min, request.driver_count_max)
    end_at = request.assumed_at + timedelta(minutes=request.work_minutes)
    drivers = _random_scenario_drivers(
        core=core,
        driver_count=driver_count,
        vehicle_capacity=request.vehicle_capacity,
        start_at=request.assumed_at,
        end_at=end_at,
        rng=rng,
    )
    plan_request = _make_plan_request(
        core=core,
        drivers=drivers,
        end_at=end_at,
        reserve_bikes_per_source=request.reserve_bikes_per_source,
        service_minutes_per_stop=request.service_minutes_per_stop,
        use_tmap=request.use_tmap,
    )
    return BuiltTestScenarioPlan(
        plan_request=plan_request,
        random_seed=seed,
        drivers=tuple(drivers),
    )


def create_sample_core_scenario() -> CoreTestScenarioRequest:
    start = datetime(2025, 7, 1, 8, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    stations = [
        ("ST-001", "시청역 대여소", 36.3510, 127.3850, 18, 25, 10, 0.10),
        ("ST-002", "정부청사 대여소", 36.3615, 127.3790, 15, 22, 8, 0.15),
        ("ST-003", "대전역 대여소", 36.3310, 127.4345, 1, 20, -10, 0.95),
        ("ST-004", "충남대 대여소", 36.3695, 127.3445, 2, 20, -8, 0.85),
        ("ST-005", "유성온천역 대여소", 36.3537, 127.3414, 5, 18, -4, 0.65),
    ]
    core = CorePayload.model_validate(
        {
            "meta": {
                "generated_at": start.isoformat(),
                "horizon": "08:00~12:00",
                "demo_mode": True,
            },
            "stations": [
                {
                    "station_id": station_id,
                    "station_name": name,
                    "location": {"lat": lat, "lng": lng},
                    "available_bikes": available,
                    "capacity": capacity,
                    "weather": {"precip_band": "none", "temperature_c": 26},
                    "ml": {"broken_suspected_count": 0},
                    "stgnn": {
                        "predicted_net_flow": predicted,
                        "shortage_pressure": pressure,
                    },
                }
                for (
                    station_id,
                    name,
                    lat,
                    lng,
                    available,
                    capacity,
                    predicted,
                    pressure,
                ) in stations
            ],
        }
    )
    return CoreTestScenarioRequest(
        core=core,
        driver_count=2,
        vehicle_capacity=8,
        start_at=start,
        work_minutes=240,
        use_tmap=True,
    )


def _make_plan_request(
    *,
    core: CorePayload,
    drivers: list[DriverInput],
    end_at: datetime,
    reserve_bikes_per_source: int,
    service_minutes_per_stop: float,
    use_tmap: bool,
) -> PlanRequest:
    return PlanRequest(
        core=core,
        drivers=drivers,
        live_stations=_live_station_snapshot(core, reserve_bikes_per_source),
        options=PlanningOptions(
            reserve_bikes_per_source=reserve_bikes_per_source,
            service_minutes_per_stop=service_minutes_per_stop,
            use_live_tashu=False,
            use_tmap_planning_matrix=use_tmap,
            use_tmap_navigation=use_tmap,
            planning_end_at=end_at,
        ),
    )


def _live_station_snapshot(
    core: CorePayload,
    reserve_bikes_per_source: int,
) -> list[dict]:
    live_stations: list[dict] = []
    for station in core.stations:
        extra = station.model_extra or {}
        available = _first_int(
            extra,
            "available_bikes",
            "initial_bikes",
            "parking_count",
        )
        if available is None:
            predicted = station.stgnn.predicted_net_flow
            available = (
                reserve_bikes_per_source
                + max(0, predicted)
                + station.ml.broken_suspected_count
            )
        capacity = _first_int(extra, "capacity", "rack_capacity", "거치대수")
        capacity = max(capacity or 20, available)
        live_stations.append(
            {
                "station_id": station.station_id,
                "station_name": station.station_name,
                "location": station.location,
                "available_bikes": available,
            }
        )
    return live_stations


def _random_scenario_drivers(
    *,
    core: CorePayload,
    driver_count: int,
    vehicle_capacity: int,
    start_at: datetime,
    end_at: datetime,
    rng: random.Random,
) -> list[DriverInput]:
    names = rng.sample(_KOREAN_DRIVER_NAMES, driver_count)
    min_lat, max_lat, min_lng, max_lng = _padded_station_bounds(core)
    locations: set[tuple[float, float]] = set()
    drivers: list[DriverInput] = []
    for index, name in enumerate(names, start=1):
        for attempt in range(100):
            lat = round(rng.uniform(min_lat, max_lat), 6)
            lng = round(rng.uniform(min_lng, max_lng), 6)
            location_key = (lat, lng)
            if location_key not in locations:
                break
        else:  # pragma: no cover - six decimal degrees provides ample uniqueness.
            lat = round(min(max_lat, min_lat + index * 0.00001), 6)
            lng = round(min(max_lng, min_lng + index * 0.00001), 6)
            location_key = (lat, lng)
        locations.add(location_key)
        drivers.append(
            DriverInput(
                driver_id=f"DRIVER-{index:02d}",
                driver_name=name,
                start_at=start_at,
                end_at=end_at,
                start_location=Location(lat=lat, lng=lng),
                vehicle_capacity=vehicle_capacity,
            )
        )
    return drivers


def _padded_station_bounds(core: CorePayload) -> tuple[float, float, float, float]:
    latitudes = [station.location.lat for station in core.stations]
    longitudes = [station.location.lng for station in core.stations]
    station_min_lat, station_max_lat = min(latitudes), max(latitudes)
    station_min_lng, station_max_lng = min(longitudes), max(longitudes)
    lat_span = max(station_max_lat - station_min_lat, 0.02)
    lng_span = max(station_max_lng - station_min_lng, 0.02)
    lat_padding = min(0.03, max(0.008, lat_span * 0.20))
    lng_padding = min(0.04, max(0.010, lng_span * 0.20))
    min_lat = max(_DAEJEON_LAT_RANGE[0], station_min_lat - lat_padding)
    max_lat = min(_DAEJEON_LAT_RANGE[1], station_max_lat + lat_padding)
    min_lng = max(_DAEJEON_LNG_RANGE[0], station_min_lng - lng_padding)
    max_lng = min(_DAEJEON_LNG_RANGE[1], station_max_lng + lng_padding)
    if min_lat >= max_lat or min_lng >= max_lng:
        return (
            _DAEJEON_LAT_RANGE[0],
            _DAEJEON_LAT_RANGE[1],
            _DAEJEON_LNG_RANGE[0],
            _DAEJEON_LNG_RANGE[1],
        )
    return min_lat, max_lat, min_lng, max_lng


def _virtual_drivers(
    request: CoreTestScenarioRequest,
    start_at: datetime,
    end_at: datetime,
) -> list[DriverInput]:
    supply = sorted(
        request.core.stations,
        key=lambda station: station.stgnn.predicted_net_flow,
        reverse=True,
    )
    return [
        DriverInput(
            driver_id=f"DRIVER-{index + 1:02d}",
            driver_name=f"{'김' if index == 0 else '이' if index == 1 else index + 1}기사",
            start_at=start_at,
            end_at=end_at,
            start_location={
                "lat": supply[index % len(supply)].location.lat + index * 0.001,
                "lng": supply[index % len(supply)].location.lng + index * 0.001,
            },
            vehicle_capacity=request.vehicle_capacity,
        )
        for index in range(request.driver_count)
    ]


def _first_int(values: dict, *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return max(0, int(float(value)))
    return None
