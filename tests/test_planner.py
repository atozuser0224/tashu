from datetime import datetime

from app.models import PlanRequest
from app.planner import create_plan
from app.travel import TravelMetric, TravelTimeMatrix


def request_payload(*, use_live: bool = True) -> dict:
    def station(station_id, name, lat, lng, flow, pressure, broken=0, rain="none"):
        return {
            "station_id": station_id,
            "station_name": name,
            "location": {"lat": lat, "lng": lng},
            "weather": {"precip_band": rain, "temperature_c": 18.0},
            "ml": {"broken_suspected_count": broken},
            "stgnn": {
                "predicted_net_flow": flow,
                "shortage_pressure": pressure,
            },
        }

    return {
        "core": {
            "meta": {
                "generated_at": "2026-07-21T15:55:00+09:00",
                "horizon": "16:00→03:00",
                "demo_mode": False,
            },
            "stations": [
                station("S-1", "충남대 정문 앞", 36.3665, 127.3445, -9, 0.95),
                station("S-2", "유성온천역 인근", 36.3538, 127.3414, -7, 0.65),
                station("S-3", "궁동 인근", 36.3618, 127.3500, 10, 0.05, broken=2),
                station("S-4", "갑천 인근", 36.3553, 127.3680, 10, 0.1),
            ],
        },
        "drivers": [
            {
                "driver_id": "D-1",
                "driver_name": "김기사",
                "start_at": "2026-07-21T16:00:00+09:00",
                "start_location": {"lat": 36.3600, "lng": 127.3400},
                "vehicle_capacity": 6,
            },
            {
                "driver_id": "D-2",
                "driver_name": "이기사",
                "start_at": "2026-07-21T16:05:00+09:00",
                "start_location": {"lat": 36.3500, "lng": 127.3700},
                "vehicle_capacity": 6,
            },
        ],
        "live_stations": [
            {
                "station_id": "S-1",
                "station_name": "충남대 정문 앞",
                "location": {"lat": 36.3665, "lng": 127.3445},
                "available_bikes": 1,
            },
            {
                "station_id": "S-2",
                "station_name": "유성온천역 인근",
                "location": {"lat": 36.3538, "lng": 127.3414},
                "available_bikes": 2,
            },
            {
                "station_id": "S-3",
                "station_name": "궁동 인근",
                "location": {"lat": 36.3618, "lng": 127.3500},
                "available_bikes": 12,
            },
            {
                "station_id": "S-4",
                "station_name": "갑천 인근",
                "location": {"lat": 36.3553, "lng": 127.3680},
                "available_bikes": 12,
            },
        ],
        "options": {
            "use_live_tashu": use_live,
            "reserve_bikes_per_source": 2,
        },
    }


def test_distributes_work_across_multiple_drivers_and_moves_all_shortage():
    request = PlanRequest.model_validate(request_payload())
    response = create_plan(
        request,
        request.live_stations,
        "provided_tashu_snapshot",
    )

    assert response.status == "fully_assigned"
    assert response.summary.total_bikes_requested == 16
    assert response.summary.total_bikes_moved == 16
    assert response.summary.active_driver_count == 2
    assert all(route.total_bikes_moved > 0 for route in response.routes)
    assert all(
        stop.load_after <= stop.capacity
        for route in response.routes
        for stop in route.stops
    )
    assert response.map_data.routes[0].coordinates[0] == request.drivers[0].start_location


def test_live_inventory_and_broken_prediction_cap_pickup_quantity():
    payload = request_payload()
    payload["core"]["stations"] = [
        payload["core"]["stations"][0],
        payload["core"]["stations"][2],
    ]
    payload["core"]["stations"][0]["stgnn"]["predicted_net_flow"] = -10
    payload["live_stations"] = [
        payload["live_stations"][0],
        payload["live_stations"][2],
    ]
    payload["live_stations"][1]["available_bikes"] = 7
    request = PlanRequest.model_validate(payload)

    response = create_plan(request, request.live_stations, "provided_tashu_snapshot")

    # 7 live - 2 reserve - 2 suspected broken = 3 movable bikes.
    assert response.summary.total_bikes_moved == 3
    assert response.summary.total_shortage_unresolved == 7
    assert response.status == "partially_assigned"


def test_horizon_prevents_assignment_that_finishes_too_late():
    payload = request_payload()
    payload["drivers"] = [payload["drivers"][0]]
    payload["drivers"][0]["end_at"] = "2026-07-21T16:01:00+09:00"
    request = PlanRequest.model_validate(payload)

    response = create_plan(request, request.live_stations, "provided_tashu_snapshot")

    assert response.status == "no_assignment"
    assert response.summary.total_bikes_moved == 0
    assert any(
        item.reason == "outside_driver_work_window" for item in response.unresolved
    )


def test_plan_id_is_deterministic_for_same_input():
    request = PlanRequest.model_validate(request_payload())
    first = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    second = create_plan(request, request.live_stations, "provided_tashu_snapshot")
    assert first.plan_id == second.plan_id
    assert isinstance(first.generated_at, datetime)


def test_each_driver_starts_at_nearest_supply_by_road_time_matrix():
    payload = request_payload()
    payload["core"]["stations"] = [
        {
            "station_id": "D",
            "station_name": "부족 대여소",
            "location": {"lat": 36.36, "lng": 127.35},
            "weather": {"precip_band": "none", "temperature_c": 20},
            "ml": {"broken_suspected_count": 0},
            "stgnn": {"predicted_net_flow": -12, "shortage_pressure": 0.9},
        },
        {
            "station_id": "SA",
            "station_name": "서쪽 잉여 대여소",
            "location": {"lat": 36.36, "lng": 127.33},
            "weather": {"precip_band": "none", "temperature_c": 20},
            "ml": {"broken_suspected_count": 0},
            "stgnn": {"predicted_net_flow": 10, "shortage_pressure": 0.1},
        },
        {
            "station_id": "SB",
            "station_name": "동쪽 잉여 대여소",
            "location": {"lat": 36.36, "lng": 127.37},
            "weather": {"precip_band": "none", "temperature_c": 20},
            "ml": {"broken_suspected_count": 0},
            "stgnn": {"predicted_net_flow": 10, "shortage_pressure": 0.1},
        },
    ]
    payload["live_stations"] = None
    request = PlanRequest.model_validate(payload)
    matrix = TravelTimeMatrix(
        source="test",
        metrics={
            ("driver:D-1", "station:SA"): TravelMetric(1000, 60),
            ("driver:D-1", "station:SB"): TravelMetric(1000, 600),
            ("driver:D-2", "station:SA"): TravelMetric(1000, 600),
            ("driver:D-2", "station:SB"): TravelMetric(1000, 60),
            ("station:SA", "station:D"): TravelMetric(1500, 300),
            ("station:SB", "station:D"): TravelMetric(1500, 300),
        },
    )

    response = create_plan(
        request,
        None,
        "prediction_only",
        travel_matrix=matrix,
    )

    routes = {route.driver_id: route for route in response.routes}
    assert routes["D-1"].stops[0].station_id == "SA"
    assert routes["D-2"].stops[0].station_id == "SB"
    assert response.data_sources.allocation_travel_time == "tmap_route_matrix"
