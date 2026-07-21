from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Location(ApiModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class CoreMeta(BaseModel):
    """Core metadata. Extra model metadata is preserved for forward compatibility."""

    model_config = ConfigDict(extra="allow")
    generated_at: str | None = None
    horizon: str | None = None
    demo_mode: bool = False


class Weather(ApiModel):
    precip_band: str = "none"
    temperature_c: float | None = None


class MlPrediction(ApiModel):
    broken_suspected_count: int = Field(default=0, ge=0)


class StgnnPrediction(ApiModel):
    predicted_net_flow: int
    shortage_pressure: float = Field(ge=0, le=1)


class CoreStation(BaseModel):
    model_config = ConfigDict(extra="allow")
    station_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    location: Location
    weather: Weather
    ml: MlPrediction
    stgnn: StgnnPrediction


class CorePayload(ApiModel):
    meta: CoreMeta
    stations: list[CoreStation] = Field(min_length=1)

    @model_validator(mode="after")
    def station_ids_must_be_unique(self) -> "CorePayload":
        ids = [station.station_id for station in self.stations]
        if len(ids) != len(set(ids)):
            raise ValueError("core.stations station_id must be unique")
        return self


class DriverInput(ApiModel):
    driver_id: str = Field(min_length=1)
    driver_name: str = Field(min_length=1)
    start_at: datetime
    start_location: Location
    vehicle_capacity: int = Field(default=20, ge=1, le=100)
    end_at: datetime | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def timezone_is_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone offset is required")
        return value

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "DriverInput":
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class TashuLiveStation(ApiModel):
    station_id: str
    station_name: str
    location: Location
    available_bikes: int = Field(ge=0)
    address: str | None = None
    station_name_en: str | None = None
    station_name_cn: str | None = None


class PlanningOptions(ApiModel):
    average_speed_kmh: float = Field(default=25.0, gt=0, le=100)
    service_minutes_per_stop: float = Field(default=5.0, ge=0, le=60)
    reserve_bikes_per_source: int = Field(default=2, ge=0, le=50)
    min_transfer_quantity: int = Field(default=1, ge=1, le=20)
    use_live_tashu: bool = True
    use_tmap_navigation: bool = True
    use_tmap_planning_matrix: bool = True
    planning_end_at: datetime | None = None

    @field_validator("planning_end_at")
    @classmethod
    def planning_end_needs_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timezone offset is required")
        return value


class PlanRequest(ApiModel):
    core: CorePayload
    drivers: list[DriverInput] = Field(min_length=1)
    live_stations: list[TashuLiveStation] | None = None
    options: PlanningOptions = Field(default_factory=PlanningOptions)

    @model_validator(mode="after")
    def driver_ids_must_be_unique(self) -> "PlanRequest":
        ids = [driver.driver_id for driver in self.drivers]
        if len(ids) != len(set(ids)):
            raise ValueError("drivers driver_id must be unique")
        return self


class StopOutput(ApiModel):
    sequence: int
    action: Literal["pickup", "dropoff"]
    station_id: str
    station_name: str
    location: Location
    quantity: int
    load_after: int
    capacity: int
    leg_distance_km: float
    eta: datetime
    etd: datetime
    available_bikes_at_plan_time: int | None = None
    predicted_net_flow: int
    shortage_pressure: float
    precip_band: str


class TransferOutput(ApiModel):
    transfer_id: str
    source_station_id: str
    source_station_name: str
    destination_station_id: str
    destination_station_name: str
    quantity: int
    shortage_pressure: float
    direct_distance_km: float
    pickup_eta: datetime
    dropoff_eta: datetime


class NavigationInstruction(ApiModel):
    sequence: int
    description: str
    location: Location
    point_type: str | None = None
    turn_type: int | None = None
    road_name: str | None = None
    distance_meters: int = Field(default=0, ge=0)
    duration_seconds: int = Field(default=0, ge=0)
    arrive_at: str | None = None
    complete_at: str | None = None


class RoadNavigation(ApiModel):
    provider: Literal["tmap"] = "tmap"
    total_distance_meters: int = Field(ge=0)
    total_duration_seconds: int = Field(ge=0)
    total_fare_won: int = Field(ge=0)
    coordinates: list[Location]
    instructions: list[NavigationInstruction]


class DriverRouteOutput(ApiModel):
    driver_id: str
    driver_name: str
    route_color: str
    start_at: datetime
    end_at: datetime | None
    start_location: Location
    vehicle_capacity: int
    status: Literal["assigned", "idle"]
    total_bikes_moved: int
    total_distance_km: float
    estimated_finish_at: datetime
    first_pickup_distance_km: float | None = None
    first_pickup_travel_seconds: int | None = None
    transfers: list[TransferOutput]
    stops: list[StopOutput]
    navigation: RoadNavigation | None = None


class UnresolvedStation(ApiModel):
    station_id: str
    station_name: str
    kind: Literal["shortage", "surplus"]
    remaining_quantity: int
    reason: Literal[
        "insufficient_usable_supply",
        "outside_driver_work_window",
        "below_min_transfer",
        "surplus_after_all_shortages_filled",
    ]


class PlanSummary(ApiModel):
    driver_count: int
    active_driver_count: int
    transfer_count: int
    total_bikes_requested: int
    total_bikes_moved: int
    total_shortage_unresolved: int
    total_surplus_unassigned: int
    broken_bikes_excluded: int


class DataSources(ApiModel):
    demand_forecast: str = "core.stgnn"
    live_inventory: Literal[
        "official_tashu_openapi", "provided_tashu_snapshot", "prediction_only"
    ]
    live_snapshot_station_count: int = Field(ge=0)
    live_station_match_count: int = Field(ge=0)
    core_station_count: int = Field(ge=1)
    allocation_travel_time: Literal[
        "tmap_route_matrix", "haversine_estimate"
    ] = "haversine_estimate"
    allocation_strategy: Literal[
        "nearest_home_seed_then_road_time_greedy_local_search"
    ] = "nearest_home_seed_then_road_time_greedy_local_search"
    distance: Literal[
        "haversine_straight_line",
        "tmap_vehicle_route",
        "mixed_tmap_and_haversine",
    ] = "haversine_straight_line"


class MapBounds(ApiModel):
    southwest: Location
    northeast: Location


class MapRoute(ApiModel):
    driver_id: str
    color: str
    geometry_source: Literal["straight_line_preview", "tmap_vehicle_route"]
    coordinates: list[Location]


class MapMarker(ApiModel):
    marker_type: Literal["driver_start", "pickup", "dropoff"]
    driver_id: str
    sequence: int
    location: Location
    label: str
    station_id: str | None = None
    quantity: int | None = None


class FrontendMapData(ApiModel):
    geometry_source: Literal[
        "straight_line_preview",
        "tmap_vehicle_route",
        "mixed_tmap_and_straight_line",
    ] = "straight_line_preview"
    center: Location
    bounds: MapBounds
    routes: list[MapRoute]
    markers: list[MapMarker]


class PlanResponse(ApiModel):
    plan_id: str
    generated_at: datetime
    status: Literal["fully_assigned", "partially_assigned", "no_assignment"]
    data_sources: DataSources
    summary: PlanSummary
    routes: list[DriverRouteOutput]
    unresolved: list[UnresolvedStation]
    map_data: FrontendMapData
    warnings: list[str]
    published_mission_ids: list[str] = Field(default_factory=list)


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: str = "tashu-rebalancing-server"


class TashuStationListResponse(ApiModel):
    source: Literal["official_tashu_openapi"] = "official_tashu_openapi"
    count: int
    stations: list[TashuLiveStation]
