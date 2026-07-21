from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.models import (
    DriverRouteOutput,
    Location,
    NavigationInstruction,
    PlanResponse,
    RoadNavigation,
)
from app.travel import TravelMetric, TravelNode, TravelTimeMatrix


TMAP_VEHICLE_ROUTE_URL = "https://apis.openapi.sk.com/tmap/routes"
TMAP_ROUTE_MATRIX_URL = "https://apis.openapi.sk.com/tmap/matrix"
MAX_STOPS_PER_REQUEST = 6  # 5 passList points plus one end point.


class TmapApiError(RuntimeError):
    pass


class TmapClient:
    """TMAP fixed-order vehicle route adapter with road-by-road instructions.

    Fixed-order routing is intentional: an optimizer must never move a dropoff
    ahead of the pickup that supplies its bicycles.
    """

    def __init__(
        self,
        app_key: str | None = None,
        timeout_seconds: float = 20.0,
        cache_ttl_seconds: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.app_key = app_key or os.getenv("TMAP_APP_KEY")
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.transport = transport
        self._semaphore = asyncio.Semaphore(3)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._matrix_cache: dict[str, tuple[float, TravelTimeMatrix]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.app_key)

    async def route_driver(
        self,
        route: DriverRouteOutput,
        service_minutes_per_stop: float,
    ) -> RoadNavigation:
        if not self.app_key:
            raise TmapApiError("TMAP_APP_KEY is not configured")
        if not route.stops:
            return RoadNavigation(
                total_distance_meters=0,
                total_duration_seconds=0,
                total_fare_won=0,
                coordinates=[route.start_location],
                instructions=[],
            )

        all_coordinates: list[Location] = []
        all_instructions: list[NavigationInstruction] = []
        total_distance = 0
        total_duration = 0
        total_fare = 0
        current_location = route.start_location
        current_start_at = route.start_at

        for offset in range(0, len(route.stops), MAX_STOPS_PER_REQUEST):
            stops = route.stops[offset : offset + MAX_STOPS_PER_REQUEST]
            payload = self._make_payload(
                route=route,
                start=current_location,
                start_at=current_start_at,
                stops=stops,
            )
            response = await self._request(payload)
            parsed = self._parse_response(response)
            total_distance += parsed.total_distance_meters
            total_duration += parsed.total_duration_seconds
            total_fare += parsed.total_fare_won
            self._append_coordinates(all_coordinates, parsed.coordinates)
            all_instructions.extend(parsed.instructions)

            current_location = stops[-1].location
            service_seconds = round(service_minutes_per_stop * 60 * len(stops))
            current_start_at += timedelta(
                seconds=parsed.total_duration_seconds + service_seconds
            )

        instructions = [
            instruction.model_copy(update={"sequence": index})
            for index, instruction in enumerate(all_instructions, start=1)
        ]
        return RoadNavigation(
            total_distance_meters=total_distance,
            total_duration_seconds=total_duration,
            total_fare_won=total_fare,
            coordinates=all_coordinates,
            instructions=instructions,
        )

    async def travel_time_matrix(
        self,
        nodes: list[TravelNode],
    ) -> TravelTimeMatrix:
        if not self.app_key:
            raise TmapApiError("TMAP_APP_KEY is not configured")
        if not nodes:
            return TravelTimeMatrix(metrics={}, source="tmap_route_matrix")

        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    [node.node_id, node.location.lat, node.location.lng]
                    for node in nodes
                ],
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        cached = self._matrix_cache.get(fingerprint)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        payload = {
            "origins": [
                {"lon": str(node.location.lng), "lat": str(node.location.lat)}
                for node in nodes
            ],
            "destinations": [
                {"lon": str(node.location.lng), "lat": str(node.location.lat)}
                for node in nodes
            ],
            "transportMode": "car",
            "metric": "Recommendation",
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "appKey": self.app_key,
        }
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        TMAP_ROUTE_MATRIX_URL,
                        params={"version": "1"},
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TmapApiError(f"TMAP route matrix request failed: {exc}") from exc

        routes = data.get("matrixRoutes") if isinstance(data, dict) else None
        if not isinstance(routes, list):
            raise TmapApiError("TMAP matrix response has no matrixRoutes list")
        metrics: dict[tuple[str, str], TravelMetric] = {}
        for item in routes:
            try:
                origin_index = int(item["originIndex"])
                destination_index = int(item["destinationIndex"])
                if not (0 <= origin_index < len(nodes)) or not (
                    0 <= destination_index < len(nodes)
                ):
                    raise IndexError("matrix index outside request nodes")
                status = str(item.get("status", "")).lower()
                if status and status not in {"ok", "success", "200", "0"}:
                    continue
                metrics[
                    (nodes[origin_index].node_id, nodes[destination_index].node_id)
                ] = TravelMetric(
                    distance_meters=_nonnegative_int(item.get("distance")),
                    duration_seconds=_nonnegative_int(item.get("duration")),
                )
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise TmapApiError(f"invalid TMAP matrix route row: {exc}") from exc
        if not metrics:
            raise TmapApiError("TMAP matrix response contains no usable routes")
        matrix = TravelTimeMatrix(metrics=metrics, source="tmap_route_matrix")
        self._matrix_cache[fingerprint] = (time.monotonic(), matrix)
        return matrix

    @staticmethod
    def _make_payload(
        route: DriverRouteOutput,
        start: Location,
        start_at,
        stops,
    ) -> dict[str, Any]:
        end = stops[-1]
        gps_time = start_at.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d%H%M%S")
        pass_list = "_".join(
            f"{stop.location.lng},{stop.location.lat}" for stop in stops[:-1]
        )
        payload = {
            "reqCoordType": "WGS84GEO",
            "resCoordType": "WGS84GEO",
            "startName": f"{route.driver_name} 출발",
            "startX": str(start.lng),
            "startY": str(start.lat),
            "gpsTime": gps_time,
            "endName": end.station_name,
            "endX": str(end.location.lng),
            "endY": str(end.location.lat),
            "endPoiId": "",
            "searchOption": 0,
            "carType": 4,
            "totalValue": 1,
            "trafficInfo": "Y",
            "mainRoadInfo": "Y",
        }
        if pass_list:
            payload["passList"] = pass_list
        return payload

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        cache_key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "appKey": self.app_key or "",
        }
        try:
            async with self._semaphore:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        TMAP_VEHICLE_ROUTE_URL,
                        params={"version": "1"},
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TmapApiError(f"TMAP vehicle route request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise TmapApiError("TMAP response is not a JSON object")
        self._cache[cache_key] = (time.monotonic(), data)
        return data

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> RoadNavigation:
        properties = payload.get("properties") or {}
        features = payload.get("features")
        if not isinstance(features, list):
            raise TmapApiError("TMAP response has no features list")

        first_feature_properties = (
            (features[0].get("properties") or {}) if features else {}
        )
        total_properties = {**first_feature_properties, **properties}
        coordinates: list[Location] = []
        instructions: list[NavigationInstruction] = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            feature_properties = feature.get("properties") or {}
            geometry_type = geometry.get("type")
            raw_coordinates = geometry.get("coordinates")
            if geometry_type == "LineString" and isinstance(raw_coordinates, list):
                line = [TmapClient._location(item) for item in raw_coordinates]
                TmapClient._append_coordinates(coordinates, line)
                if instructions:
                    previous = instructions[-1]
                    previous.distance_meters = _nonnegative_int(
                        feature_properties.get("distance")
                    )
                    previous.duration_seconds = _nonnegative_int(
                        feature_properties.get("time")
                    )
                    previous.road_name = _optional_str(
                        feature_properties.get("name")
                    ) or previous.road_name
            elif geometry_type == "Point" and isinstance(raw_coordinates, list):
                description = (
                    feature_properties.get("description")
                    or feature_properties.get("viaPointName")
                    or feature_properties.get("name")
                )
                if description:
                    instructions.append(
                        NavigationInstruction(
                            sequence=len(instructions) + 1,
                            description=str(description).replace("[0] ", ""),
                            location=TmapClient._location(raw_coordinates),
                            point_type=_optional_str(feature_properties.get("pointType")),
                            turn_type=_optional_int(feature_properties.get("turnType")),
                            road_name=_optional_str(
                                feature_properties.get("nextRoadName")
                                or feature_properties.get("roadName")
                            ),
                            distance_meters=_nonnegative_int(
                                feature_properties.get("distance")
                            ),
                            duration_seconds=_nonnegative_int(
                                feature_properties.get("time")
                            ),
                            arrive_at=_optional_str(
                                feature_properties.get("arriveTime")
                            ),
                            complete_at=_optional_str(
                                feature_properties.get("completeTime")
                            ),
                        )
                    )
        if not coordinates:
            raise TmapApiError("TMAP response has no LineString geometry")
        return RoadNavigation(
            total_distance_meters=_nonnegative_int(
                total_properties.get("totalDistance")
            ),
            total_duration_seconds=_nonnegative_int(total_properties.get("totalTime")),
            total_fare_won=_nonnegative_int(total_properties.get("totalFare")),
            coordinates=coordinates,
            instructions=instructions,
        )

    @staticmethod
    def _location(raw: Any) -> Location:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise TmapApiError("invalid coordinate in TMAP response")
        return Location(lat=float(raw[1]), lng=float(raw[0]))

    @staticmethod
    def _append_coordinates(target: list[Location], incoming: list[Location]) -> None:
        if target and incoming and target[-1] == incoming[0]:
            target.extend(incoming[1:])
        else:
            target.extend(incoming)


async def enrich_plan_with_tmap(
    plan: PlanResponse,
    client: TmapClient,
    service_minutes_per_stop: float,
) -> PlanResponse:
    active_routes = [route for route in plan.routes if route.stops]
    if not active_routes:
        return plan
    if not client.configured:
        plan.warnings.append(
            "TMAP_APP_KEY가 없어 직선 경로 미리보기를 반환했습니다."
        )
        return plan

    results = await asyncio.gather(
        *[
            client.route_driver(route, service_minutes_per_stop)
            for route in active_routes
        ],
        return_exceptions=True,
    )
    success_count = 0
    errors: list[str] = []
    for route, result in zip(active_routes, results, strict=True):
        if isinstance(result, Exception):
            errors.append(f"{route.driver_id}: {result}")
            continue
        route.navigation = result
        route.total_distance_km = round(result.total_distance_meters / 1000, 3)
        service_seconds = round(service_minutes_per_stop * 60 * len(route.stops))
        route.estimated_finish_at = route.start_at + timedelta(
            seconds=result.total_duration_seconds + service_seconds
        )
        map_route = next(
            item for item in plan.map_data.routes if item.driver_id == route.driver_id
        )
        map_route.coordinates = result.coordinates
        map_route.geometry_source = "tmap_vehicle_route"
        success_count += 1

    if success_count:
        _recalculate_map_view(plan)
        plan.warnings = [
            warning
            for warning in plan.warnings
            if not warning.startswith("map_data 경로는 직선 미리보기")
        ]
    if success_count == len(active_routes):
        plan.data_sources.distance = "tmap_vehicle_route"
        plan.map_data.geometry_source = "tmap_vehicle_route"
    elif success_count:
        plan.data_sources.distance = "mixed_tmap_and_haversine"
        plan.map_data.geometry_source = "mixed_tmap_and_straight_line"
    if errors:
        plan.warnings.append("일부 TMAP 경로 폴백: " + " | ".join(errors))
    return plan


def _recalculate_map_view(plan: PlanResponse) -> None:
    coordinates = [
        coordinate
        for route in plan.map_data.routes
        for coordinate in route.coordinates
    ]
    min_lat = min(point.lat for point in coordinates)
    max_lat = max(point.lat for point in coordinates)
    min_lng = min(point.lng for point in coordinates)
    max_lng = max(point.lng for point in coordinates)
    plan.map_data.center = Location(
        lat=(min_lat + max_lat) / 2,
        lng=(min_lng + max_lng) / 2,
    )
    plan.map_data.bounds.southwest = Location(lat=min_lat, lng=min_lng)
    plan.map_data.bounds.northeast = Location(lat=max_lat, lng=max_lng)


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError) as exc:
        raise TmapApiError(f"invalid numeric value in TMAP response: {value}") from exc


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)
