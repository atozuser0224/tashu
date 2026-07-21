from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from app.models import ApiModel, CorePayload, DriverInput, PlanRequest, PlanningOptions


class CoreTestScenarioRequest(ApiModel):
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
        if value is not None and value.tzinfo is None:
            raise ValueError("start_at must include a timezone offset")
        return value


class TestTmapConfig(ApiModel):
    configured: bool
    sdk_url: str | None = None


def build_test_plan_request(request: CoreTestScenarioRequest) -> PlanRequest:
    start_at = request.start_at or datetime.now(ZoneInfo("Asia/Seoul")).replace(
        second=0, microsecond=0
    )
    end_at = start_at + timedelta(minutes=request.work_minutes)
    live_stations = []
    capacities: dict[str, int] = {}
    for station in request.core.stations:
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
                request.reserve_bikes_per_source
                + max(0, predicted)
                + station.ml.broken_suspected_count
            )
        capacity = _first_int(extra, "capacity", "rack_capacity", "거치대수")
        capacity = max(capacity or 20, available)
        capacities[station.station_id] = capacity
        live_stations.append(
            {
                "station_id": station.station_id,
                "station_name": station.station_name,
                "location": station.location,
                "available_bikes": available,
            }
        )

    drivers = request.drivers or _virtual_drivers(request, start_at, end_at)
    return PlanRequest(
        core=request.core,
        drivers=drivers,
        live_stations=live_stations,
        options=PlanningOptions(
            reserve_bikes_per_source=request.reserve_bikes_per_source,
            service_minutes_per_stop=request.service_minutes_per_stop,
            use_live_tashu=False,
            use_tmap_planning_matrix=request.use_tmap,
            use_tmap_navigation=request.use_tmap,
            planning_end_at=end_at,
        ),
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
