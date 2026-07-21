from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from app.models import (
    DataSources,
    DriverInput,
    DriverRouteOutput,
    FrontendMapData,
    Location,
    MapBounds,
    MapMarker,
    MapRoute,
    PlanRequest,
    PlanResponse,
    PlanSummary,
    StopOutput,
    TashuLiveStation,
    TransferOutput,
    UnresolvedStation,
)
from app.travel import (
    TravelMetric,
    TravelTimeMatrix,
    driver_node_id,
    station_node_id,
)


EARTH_RADIUS_KM = 6371.0088
ROUTE_COLORS = ("#2563EB", "#DC2626", "#16A34A", "#9333EA", "#EA580C", "#0891B2")
HORIZON_PATTERN = re.compile(r"(?P<start>\d{1,2}:\d{2})\s*[→~\-]\s*(?P<end>\d{1,2}:\d{2})")
PRECIP_SPEED_MULTIPLIER = {
    "none": 1.0,
    "clear": 1.0,
    "rain": 0.82,
    "snow": 0.65,
    "mixed": 0.72,
}


@dataclass
class StationState:
    station_id: str
    station_name: str
    location: Location
    predicted_net_flow: int
    shortage_pressure: float
    precip_band: str
    broken_suspected: int
    live_available: int | None
    remaining_supply: int
    remaining_shortage: int
    initial_shortage: int


@dataclass
class DriverState:
    driver: DriverInput
    end_at: datetime | None
    color: str
    current_location: Location
    current_node_id: str
    available_at: datetime
    stops: list[StopOutput] = field(default_factory=list)
    transfers: list[TransferOutput] = field(default_factory=list)
    total_distance_km: float = 0.0
    total_bikes_moved: int = 0


@dataclass(frozen=True)
class Candidate:
    driver_index: int
    source_id: str
    destination_id: str
    quantity: int
    to_source_km: float
    direct_km: float
    to_source_seconds: int
    direct_seconds: int
    pickup_eta: datetime
    pickup_etd: datetime
    dropoff_eta: datetime
    dropoff_etd: datetime


def haversine_km(first: Location, second: Location) -> float:
    lat1, lon1, lat2, lon2 = map(
        math.radians, (first.lat, first.lng, second.lat, second.lng)
    )
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(value))


def _travel_minutes(distance_km: float, speed_kmh: float, precip_band: str) -> float:
    multiplier = PRECIP_SPEED_MULTIPLIER.get(precip_band.lower(), 0.9)
    return distance_km / (speed_kmh * multiplier) * 60


def _travel_metric(
    matrix: TravelTimeMatrix | None,
    origin_id: str,
    destination_id: str,
    origin: Location,
    destination: Location,
    request: PlanRequest,
    precip_band: str,
) -> TravelMetric:
    if matrix is not None:
        metric = matrix.get(origin_id, destination_id)
        if metric is not None:
            return metric
    distance_km = haversine_km(origin, destination)
    duration_seconds = round(
        _travel_minutes(
            distance_km,
            request.options.average_speed_kmh,
            precip_band,
        )
        * 60
    )
    return TravelMetric(
        distance_meters=round(distance_km * 1000),
        duration_seconds=duration_seconds,
    )


def _derive_end_at(driver: DriverInput, request: PlanRequest) -> datetime | None:
    if driver.end_at is not None:
        return driver.end_at
    if request.options.planning_end_at is not None:
        return request.options.planning_end_at
    horizon = request.core.meta.horizon or ""
    match = HORIZON_PATTERN.search(horizon)
    if not match:
        return None
    hour, minute = (int(part) for part in match.group("end").split(":"))
    end_clock = time(hour=hour, minute=minute, tzinfo=driver.start_at.tzinfo)
    result = datetime.combine(driver.start_at.date(), end_clock)
    if result <= driver.start_at:
        result += timedelta(days=1)
    return result


def _build_station_states(
    request: PlanRequest, live_stations: list[TashuLiveStation] | None
) -> dict[str, StationState]:
    live_by_id = {station.station_id: station for station in live_stations or []}
    states: dict[str, StationState] = {}
    reserve = request.options.reserve_bikes_per_source
    for station in request.core.stations:
        live = live_by_id.get(station.station_id)
        live_available = live.available_bikes if live else None
        predicted_surplus = max(0, station.stgnn.predicted_net_flow)
        if live_available is None:
            usable_supply = max(0, predicted_surplus - station.ml.broken_suspected_count)
        else:
            movable_live = max(
                0,
                live_available - reserve - station.ml.broken_suspected_count,
            )
            usable_supply = min(predicted_surplus, movable_live)
        states[station.station_id] = StationState(
            station_id=station.station_id,
            station_name=live.station_name if live else station.station_name,
            location=live.location if live else station.location,
            predicted_net_flow=station.stgnn.predicted_net_flow,
            shortage_pressure=station.stgnn.shortage_pressure,
            precip_band=station.weather.precip_band,
            broken_suspected=station.ml.broken_suspected_count,
            live_available=live_available,
            remaining_supply=usable_supply,
            remaining_shortage=max(0, -station.stgnn.predicted_net_flow),
            initial_shortage=max(0, -station.stgnn.predicted_net_flow),
        )
    return states


def _candidate_for(
    driver_index: int,
    driver: DriverState,
    source: StationState,
    destination: StationState,
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> Candidate | None:
    quantity = min(
        driver.driver.vehicle_capacity,
        source.remaining_supply,
        destination.remaining_shortage,
    )
    if quantity < request.options.min_transfer_quantity:
        return None

    to_source_metric = _travel_metric(
        matrix,
        driver.current_node_id,
        station_node_id(source.station_id),
        driver.current_location,
        source.location,
        request,
        source.precip_band,
    )
    direct_metric = _travel_metric(
        matrix,
        station_node_id(source.station_id),
        station_node_id(destination.station_id),
        source.location,
        destination.location,
        request,
        destination.precip_band,
    )
    to_source = to_source_metric.distance_meters / 1000
    direct = direct_metric.distance_meters / 1000
    pickup_eta = driver.available_at + timedelta(
        seconds=to_source_metric.duration_seconds
    )
    pickup_etd = pickup_eta + timedelta(minutes=request.options.service_minutes_per_stop)
    dropoff_eta = pickup_etd + timedelta(
        seconds=direct_metric.duration_seconds
    )
    dropoff_etd = dropoff_eta + timedelta(minutes=request.options.service_minutes_per_stop)
    if driver.end_at is not None and dropoff_etd > driver.end_at:
        return None
    return Candidate(
        driver_index=driver_index,
        source_id=source.station_id,
        destination_id=destination.station_id,
        quantity=quantity,
        to_source_km=to_source,
        direct_km=direct,
        to_source_seconds=to_source_metric.duration_seconds,
        direct_seconds=direct_metric.duration_seconds,
        pickup_eta=pickup_eta,
        pickup_etd=pickup_etd,
        dropoff_eta=dropoff_eta,
        dropoff_etd=dropoff_etd,
    )


def _best_global_candidate(
    drivers: list[DriverState],
    stations: dict[str, StationState],
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> Candidate | None:
    candidates: list[Candidate] = []
    sources = [station for station in stations.values() if station.remaining_supply > 0]
    destinations = [station for station in stations.values() if station.remaining_shortage > 0]
    for driver_index, driver in enumerate(drivers):
        for destination in destinations:
            for source in sources:
                candidate = _candidate_for(
                    driver_index, driver, source, destination, request, matrix
                )
                if candidate is not None:
                    candidates.append(candidate)
    if not candidates:
        return None
    def priority_bucket(pressure: float) -> int:
        if pressure >= 0.8:
            return 2
        if pressure >= 0.5:
            return 1
        return 0

    return min(
        candidates,
        key=lambda item: (
            -priority_bucket(stations[item.destination_id].shortage_pressure),
            (item.to_source_seconds + item.direct_seconds) / item.quantity,
            (
                item.dropoff_etd
                - drivers[item.driver_index].driver.start_at
            ).total_seconds(),
            -stations[item.destination_id].shortage_pressure,
            -item.quantity,
            drivers[item.driver_index].driver.driver_id,
            item.destination_id,
            item.source_id,
        ),
    )


def _best_first_trip_candidate(
    driver_indexes: set[int],
    drivers: list[DriverState],
    stations: dict[str, StationState],
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> Candidate | None:
    """Assign each driver's first pickup primarily by home-to-source road time."""

    candidates: list[Candidate] = []
    sources = [station for station in stations.values() if station.remaining_supply > 0]
    destinations = [station for station in stations.values() if station.remaining_shortage > 0]
    for driver_index in driver_indexes:
        driver = drivers[driver_index]
        for source in sources:
            source_candidates = [
                candidate
                for destination in destinations
                if (
                    candidate := _candidate_for(
                        driver_index,
                        driver,
                        source,
                        destination,
                        request,
                        matrix,
                    )
                )
                is not None
            ]
            if source_candidates:
                candidates.append(
                    min(
                        source_candidates,
                        key=lambda item: (
                            -stations[item.destination_id].shortage_pressure,
                            item.direct_seconds / item.quantity,
                            item.dropoff_eta,
                            item.destination_id,
                        ),
                    )
                )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            item.to_source_seconds,
            -item.quantity,
            item.direct_seconds / item.quantity,
            drivers[item.driver_index].driver.driver_id,
            item.source_id,
        ),
    )


def _assign_candidate(
    candidate: Candidate,
    drivers: list[DriverState],
    stations: dict[str, StationState],
) -> None:
    driver = drivers[candidate.driver_index]
    source = stations[candidate.source_id]
    destination = stations[candidate.destination_id]
    transfer_number = len(driver.transfers) + 1
    transfer_id = f"{driver.driver.driver_id}-transfer-{transfer_number:03d}"
    first_sequence = len(driver.stops) + 1

    driver.stops.append(
        StopOutput(
            sequence=first_sequence,
            action="pickup",
            station_id=source.station_id,
            station_name=source.station_name,
            location=source.location,
            quantity=candidate.quantity,
            load_after=candidate.quantity,
            capacity=driver.driver.vehicle_capacity,
            leg_distance_km=round(candidate.to_source_km, 3),
            eta=candidate.pickup_eta,
            etd=candidate.pickup_etd,
            available_bikes_at_plan_time=source.live_available,
            predicted_net_flow=source.predicted_net_flow,
            shortage_pressure=source.shortage_pressure,
            precip_band=source.precip_band,
        )
    )
    driver.stops.append(
        StopOutput(
            sequence=first_sequence + 1,
            action="dropoff",
            station_id=destination.station_id,
            station_name=destination.station_name,
            location=destination.location,
            quantity=candidate.quantity,
            load_after=0,
            capacity=driver.driver.vehicle_capacity,
            leg_distance_km=round(candidate.direct_km, 3),
            eta=candidate.dropoff_eta,
            etd=candidate.dropoff_etd,
            available_bikes_at_plan_time=destination.live_available,
            predicted_net_flow=destination.predicted_net_flow,
            shortage_pressure=destination.shortage_pressure,
            precip_band=destination.precip_band,
        )
    )
    driver.transfers.append(
        TransferOutput(
            transfer_id=transfer_id,
            source_station_id=source.station_id,
            source_station_name=source.station_name,
            destination_station_id=destination.station_id,
            destination_station_name=destination.station_name,
            quantity=candidate.quantity,
            shortage_pressure=destination.shortage_pressure,
            direct_distance_km=round(candidate.direct_km, 3),
            pickup_eta=candidate.pickup_eta,
            dropoff_eta=candidate.dropoff_eta,
        )
    )
    source.remaining_supply -= candidate.quantity
    destination.remaining_shortage -= candidate.quantity
    driver.current_location = destination.location
    driver.current_node_id = station_node_id(destination.station_id)
    driver.available_at = candidate.dropoff_etd
    driver.total_distance_km += candidate.to_source_km + candidate.direct_km
    driver.total_bikes_moved += candidate.quantity


def _route_block_cost_seconds(
    driver: DriverState,
    blocks: list[tuple[TransferOutput, StopOutput, StopOutput]],
    stations: dict[str, StationState],
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> int:
    current_id = driver_node_id(driver.driver.driver_id)
    current_location = driver.driver.start_location
    total = 0
    for _, pickup, dropoff in blocks:
        source = stations[pickup.station_id]
        destination = stations[dropoff.station_id]
        to_source = _travel_metric(
            matrix,
            current_id,
            station_node_id(source.station_id),
            current_location,
            source.location,
            request,
            source.precip_band,
        )
        to_destination = _travel_metric(
            matrix,
            station_node_id(source.station_id),
            station_node_id(destination.station_id),
            source.location,
            destination.location,
            request,
            destination.precip_band,
        )
        total += to_source.duration_seconds + to_destination.duration_seconds
        current_id = station_node_id(destination.station_id)
        current_location = destination.location
    return total


def _improve_driver_route(
    driver: DriverState,
    stations: dict[str, StationState],
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> None:
    """Keep the nearest-home first trip and locally improve the remaining trips."""

    blocks = [
        (driver.transfers[index], driver.stops[index * 2], driver.stops[index * 2 + 1])
        for index in range(len(driver.transfers))
    ]
    if len(blocks) > 2:
        improved = True
        while improved:
            improved = False
            current_cost = _route_block_cost_seconds(
                driver, blocks, stations, request, matrix
            )
            best_blocks = blocks
            best_cost = current_cost
            for left in range(1, len(blocks)):
                for right in range(left + 1, len(blocks)):
                    swapped = blocks.copy()
                    swapped[left], swapped[right] = swapped[right], swapped[left]
                    swapped_cost = _route_block_cost_seconds(
                        driver, swapped, stations, request, matrix
                    )
                    if swapped_cost < best_cost:
                        best_blocks, best_cost = swapped, swapped_cost

                    reversed_tail = blocks[:left] + list(
                        reversed(blocks[left : right + 1])
                    ) + blocks[right + 1 :]
                    reversed_cost = _route_block_cost_seconds(
                        driver, reversed_tail, stations, request, matrix
                    )
                    if reversed_cost < best_cost:
                        best_blocks, best_cost = reversed_tail, reversed_cost
            if best_cost < current_cost:
                blocks = best_blocks
                improved = True

    _rebuild_driver_timeline(driver, blocks, stations, request, matrix)


def _rebuild_driver_timeline(
    driver: DriverState,
    blocks: list[tuple[TransferOutput, StopOutput, StopOutput]],
    stations: dict[str, StationState],
    request: PlanRequest,
    matrix: TravelTimeMatrix | None,
) -> None:
    driver.transfers = [block[0] for block in blocks]
    driver.stops = []
    driver.current_location = driver.driver.start_location
    driver.current_node_id = driver_node_id(driver.driver.driver_id)
    driver.available_at = driver.driver.start_at
    driver.total_distance_km = 0.0
    service_time = timedelta(minutes=request.options.service_minutes_per_stop)

    for block_index, (transfer, pickup, dropoff) in enumerate(blocks):
        source = stations[pickup.station_id]
        destination = stations[dropoff.station_id]
        to_source = _travel_metric(
            matrix,
            driver.current_node_id,
            station_node_id(source.station_id),
            driver.current_location,
            source.location,
            request,
            source.precip_band,
        )
        direct = _travel_metric(
            matrix,
            station_node_id(source.station_id),
            station_node_id(destination.station_id),
            source.location,
            destination.location,
            request,
            destination.precip_band,
        )
        pickup.sequence = block_index * 2 + 1
        pickup.leg_distance_km = round(to_source.distance_meters / 1000, 3)
        pickup.eta = driver.available_at + timedelta(seconds=to_source.duration_seconds)
        pickup.etd = pickup.eta + service_time
        dropoff.sequence = block_index * 2 + 2
        dropoff.leg_distance_km = round(direct.distance_meters / 1000, 3)
        dropoff.eta = pickup.etd + timedelta(seconds=direct.duration_seconds)
        dropoff.etd = dropoff.eta + service_time
        transfer.pickup_eta = pickup.eta
        transfer.dropoff_eta = dropoff.eta
        transfer.direct_distance_km = dropoff.leg_distance_km
        driver.stops.extend((pickup, dropoff))
        driver.available_at = dropoff.etd
        driver.current_location = destination.location
        driver.current_node_id = station_node_id(destination.station_id)
        driver.total_distance_km += (
            to_source.distance_meters + direct.distance_meters
        ) / 1000


def _make_routes(drivers: list[DriverState]) -> list[DriverRouteOutput]:
    return [
        DriverRouteOutput(
            driver_id=state.driver.driver_id,
            driver_name=state.driver.driver_name,
            route_color=state.color,
            start_at=state.driver.start_at,
            end_at=state.end_at,
            start_location=state.driver.start_location,
            vehicle_capacity=state.driver.vehicle_capacity,
            status="assigned" if state.stops else "idle",
            total_bikes_moved=state.total_bikes_moved,
            total_distance_km=round(state.total_distance_km, 3),
            estimated_finish_at=state.available_at,
            first_pickup_distance_km=(
                state.stops[0].leg_distance_km if state.stops else None
            ),
            first_pickup_travel_seconds=(
                round((state.stops[0].eta - state.driver.start_at).total_seconds())
                if state.stops
                else None
            ),
            transfers=state.transfers,
            stops=state.stops,
        )
        for state in drivers
    ]


def _make_map_data(routes: list[DriverRouteOutput]) -> FrontendMapData:
    coordinates: list[Location] = []
    map_routes: list[MapRoute] = []
    markers: list[MapMarker] = []
    for route in routes:
        route_coordinates = [route.start_location, *[stop.location for stop in route.stops]]
        coordinates.extend(route_coordinates)
        map_routes.append(
            MapRoute(
                driver_id=route.driver_id,
                color=route.route_color,
                geometry_source="straight_line_preview",
                coordinates=route_coordinates,
            )
        )
        markers.append(
            MapMarker(
                marker_type="driver_start",
                driver_id=route.driver_id,
                sequence=0,
                location=route.start_location,
                label=f"{route.driver_name} 출발",
            )
        )
        for stop in route.stops:
            markers.append(
                MapMarker(
                    marker_type=stop.action,
                    driver_id=route.driver_id,
                    sequence=stop.sequence,
                    location=stop.location,
                    label=stop.station_name,
                    station_id=stop.station_id,
                    quantity=stop.quantity,
                )
            )

    min_lat = min(point.lat for point in coordinates)
    max_lat = max(point.lat for point in coordinates)
    min_lng = min(point.lng for point in coordinates)
    max_lng = max(point.lng for point in coordinates)
    return FrontendMapData(
        center=Location(lat=(min_lat + max_lat) / 2, lng=(min_lng + max_lng) / 2),
        bounds=MapBounds(
            southwest=Location(lat=min_lat, lng=min_lng),
            northeast=Location(lat=max_lat, lng=max_lng),
        ),
        routes=map_routes,
        markers=markers,
    )


def create_plan(
    request: PlanRequest,
    live_stations: list[TashuLiveStation] | None,
    live_inventory_source: str,
    additional_warnings: list[str] | None = None,
    travel_matrix: TravelTimeMatrix | None = None,
) -> PlanResponse:
    stations = _build_station_states(request, live_stations)
    live_ids = {station.station_id for station in live_stations or []}
    live_match_count = sum(
        station.station_id in live_ids for station in request.core.stations
    )
    drivers = [
        DriverState(
            driver=driver,
            end_at=_derive_end_at(driver, request),
            color=ROUTE_COLORS[index % len(ROUTE_COLORS)],
            current_location=driver.start_location,
            current_node_id=driver_node_id(driver.driver_id),
            available_at=driver.start_at,
        )
        for index, driver in enumerate(request.drivers)
    ]
    total_requested = sum(station.initial_shortage for station in stations.values())

    # Every driver receives at most one seed trip before any driver receives a
    # second trip. Home-to-pickup road time is the primary seed criterion.
    unseeded_driver_indexes = set(range(len(drivers)))
    while unseeded_driver_indexes:
        candidate = _best_first_trip_candidate(
            unseeded_driver_indexes,
            drivers,
            stations,
            request,
            travel_matrix,
        )
        if candidate is None:
            break
        _assign_candidate(candidate, drivers, stations)
        unseeded_driver_indexes.remove(candidate.driver_index)

    while True:
        candidate = _best_global_candidate(
            drivers,
            stations,
            request,
            travel_matrix,
        )
        if candidate is None:
            break
        _assign_candidate(candidate, drivers, stations)

    for driver in drivers:
        _improve_driver_route(driver, stations, request, travel_matrix)

    routes = _make_routes(drivers)
    remaining_supply_total = sum(station.remaining_supply for station in stations.values())
    has_supply_but_no_time = remaining_supply_total >= request.options.min_transfer_quantity
    unresolved: list[UnresolvedStation] = []
    for station in sorted(stations.values(), key=lambda item: item.station_id):
        if station.remaining_shortage > 0:
            if station.remaining_shortage < request.options.min_transfer_quantity:
                reason = "below_min_transfer"
            elif has_supply_but_no_time:
                reason = "outside_driver_work_window"
            else:
                reason = "insufficient_usable_supply"
            unresolved.append(
                UnresolvedStation(
                    station_id=station.station_id,
                    station_name=station.station_name,
                    kind="shortage",
                    remaining_quantity=station.remaining_shortage,
                    reason=reason,
                )
            )
        if station.remaining_supply > 0:
            unresolved.append(
                UnresolvedStation(
                    station_id=station.station_id,
                    station_name=station.station_name,
                    kind="surplus",
                    remaining_quantity=station.remaining_supply,
                    reason="surplus_after_all_shortages_filled",
                )
            )

    total_moved = sum(route.total_bikes_moved for route in routes)
    unresolved_shortage = sum(
        item.remaining_quantity for item in unresolved if item.kind == "shortage"
    )
    unresolved_surplus = sum(
        item.remaining_quantity for item in unresolved if item.kind == "surplus"
    )
    if total_moved == 0:
        status = "no_assignment"
    elif unresolved_shortage:
        status = "partially_assigned"
    else:
        status = "fully_assigned"

    digest = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()[:12]
    warnings = list(additional_warnings or [])
    if live_stations is None:
        warnings.append(
            "실시간 parking_count가 없어 predicted_net_flow와 고장 의심 대수만으로 반출량을 계산했습니다."
        )
    elif live_match_count < len(request.core.stations):
        warnings.append(
            f"core 정류소 {len(request.core.stations)}곳 중 {live_match_count}곳만 "
            "타슈 station_id와 매칭되어, 나머지는 예측값으로 계산했습니다."
        )
    warnings.append(
        "map_data 경로는 직선 미리보기입니다. 실제 도로 안내에는 별도 길찾기 API를 연결해야 합니다."
    )
    return PlanResponse(
        plan_id=f"plan-{digest}",
        generated_at=datetime.now(tz=request.drivers[0].start_at.tzinfo),
        status=status,
        data_sources=DataSources(
            live_inventory=live_inventory_source,
            live_snapshot_station_count=len(live_stations or []),
            live_station_match_count=live_match_count,
            core_station_count=len(request.core.stations),
            allocation_travel_time=(
                "tmap_route_matrix"
                if travel_matrix is not None
                else "haversine_estimate"
            ),
        ),
        summary=PlanSummary(
            driver_count=len(routes),
            active_driver_count=sum(route.status == "assigned" for route in routes),
            transfer_count=sum(len(route.transfers) for route in routes),
            total_bikes_requested=total_requested,
            total_bikes_moved=total_moved,
            total_shortage_unresolved=unresolved_shortage,
            total_surplus_unassigned=unresolved_surplus,
            broken_bikes_excluded=sum(
                station.broken_suspected
                for station in stations.values()
                if station.predicted_net_flow > 0
            ),
        ),
        routes=routes,
        unresolved=unresolved,
        map_data=_make_map_data(routes),
        warnings=warnings,
    )
