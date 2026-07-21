import json

import httpx
import pytest

from app.models import PlanRequest
from app.planner import create_plan
from app.tmap import TmapClient, enrich_plan_with_tmap
from app.travel import TravelNode
from tests.test_planner import request_payload


def tmap_response():
    return {
        "type": "FeatureCollection",
        "properties": {
            "totalDistance": "2345",
            "totalTime": "420",
            "totalFare": "0",
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [127.34, 36.36],
                },
                "properties": {
                    "description": "출발",
                    "pointType": "S",
                    "distance": "0",
                    "time": "0",
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [127.34, 36.36],
                        [127.345, 36.363],
                        [127.35, 36.366],
                    ],
                },
                "properties": {
                    "name": "대학로",
                    "distance": 2345,
                    "time": 420,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [127.35, 36.366],
                },
                "properties": {
                    "viaPointName": "[0] 궁동 인근 pickup",
                    "pointType": "B1",
                    "distance": "1000",
                    "time": "180",
                    "arriveTime": "20260721160500",
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_tmap_preserves_assigned_stop_order_and_parses_road_geometry():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["appkey"] == "test-key"
        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(200, json=tmap_response())

    request = PlanRequest.model_validate(request_payload())
    plan = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    route = next(item for item in plan.routes if item.stops)
    client = TmapClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    navigation = await client.route_driver(
        route, request.options.service_minutes_per_stop
    )

    assert captured[0]["startX"] == str(route.start_location.lng)
    assert captured[0]["passList"] == "_".join(
        f"{stop.location.lng},{stop.location.lat}" for stop in route.stops[:5]
    )
    assert captured[0]["endName"] == route.stops[-1].station_name
    assert navigation.total_distance_meters == 2345
    assert navigation.coordinates[1].lng == 127.345
    assert navigation.instructions[0].road_name == "대학로"
    assert navigation.instructions[0].distance_meters == 2345
    assert navigation.instructions[-1].description == "궁동 인근 pickup"


@pytest.mark.asyncio
async def test_tmap_retries_rejected_multi_stop_route_one_leg_at_a_time():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        if "passList" in payload:
            return httpx.Response(400, json={"error": "invalid pass list"})
        return httpx.Response(200, json=tmap_response())

    request = PlanRequest.model_validate(request_payload())
    plan = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    route = next(item for item in plan.routes if item.stops)
    client = TmapClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    navigation = await client.route_driver(
        route, request.options.service_minutes_per_stop
    )

    assert "passList" in captured[0]
    assert len(captured) == len(route.stops) + 1
    assert all("passList" not in payload for payload in captured[1:])
    assert captured[1]["startX"] == str(route.start_location.lng)
    assert captured[2]["startX"] == str(route.stops[0].location.lng)
    assert navigation.total_distance_meters == 2345 * len(route.stops)


@pytest.mark.asyncio
async def test_enriches_frontend_map_with_tmap_route():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tmap_response())

    request = PlanRequest.model_validate(request_payload())
    plan = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    client = TmapClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    result = await enrich_plan_with_tmap(
        plan, client, request.options.service_minutes_per_stop
    )

    assert result.data_sources.distance == "tmap_vehicle_route"
    assert result.map_data.geometry_source == "tmap_vehicle_route"
    assert all(
        route.geometry_source == "tmap_vehicle_route"
        for route in result.map_data.routes
        if next(item for item in result.routes if item.driver_id == route.driver_id).stops
    )
    assert all(route.navigation is not None for route in result.routes if route.stops)


@pytest.mark.asyncio
async def test_identical_tmap_route_is_cached_for_five_minutes():
    call_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=tmap_response())

    request = PlanRequest.model_validate(request_payload())
    plan = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    route = next(item for item in plan.routes if item.stops)
    client = TmapClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    await client.route_driver(route, request.options.service_minutes_per_stop)
    await client.route_driver(route, request.options.service_minutes_per_stop)

    assert call_count == 1


@pytest.mark.asyncio
async def test_parses_tmap_route_matrix_by_requested_node_index():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tmap/matrix"
        return httpx.Response(
            200,
            json={
                "matrixRoutes": [
                    {
                        "status": "Ok",
                        "originIndex": 0,
                        "destinationIndex": 0,
                        "distance": 0,
                        "duration": 0,
                    },
                    {
                        "status": "Ok",
                        "originIndex": 0,
                        "destinationIndex": 1,
                        "distance": 2345,
                        "duration": 456,
                    },
                    {
                        "status": "Ok",
                        "originIndex": 1,
                        "destinationIndex": 0,
                        "distance": 2100,
                        "duration": 400,
                    },
                    {
                        "status": "Ok",
                        "originIndex": 1,
                        "destinationIndex": 1,
                        "distance": 0,
                        "duration": 0,
                    },
                ]
            },
        )

    client = TmapClient(
        app_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    nodes = [
        TravelNode("A", request_payload_location(36.36, 127.34)),
        TravelNode("B", request_payload_location(36.37, 127.35)),
    ]

    matrix = await client.travel_time_matrix(nodes)

    assert matrix.get("A", "B").distance_meters == 2345
    assert matrix.get("B", "A").duration_seconds == 400


def request_payload_location(lat: float, lng: float):
    from app.models import Location

    return Location(lat=lat, lng=lng)
