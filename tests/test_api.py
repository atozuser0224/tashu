from fastapi.testclient import TestClient

from app.main import app
from tests.auth_helpers import setup_auth
from tests.test_planner import request_payload


def test_health_and_plan_endpoints():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        auth = setup_auth(client)
        response = client.post(
            "/api/v1/rebalancing/plans",
            headers=auth.admin,
            json=request_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_bikes_moved"] == 16
    assert body["data_sources"]["live_inventory"] == "provided_tashu_snapshot"
    assert body["data_sources"]["live_station_match_count"] == 4
    assert body["map_data"]["geometry_source"] == "straight_line_preview"


def test_rejects_naive_driver_datetime():
    payload = request_payload()
    payload["drivers"][0]["start_at"] = "2026-07-21T16:00:00"
    with TestClient(app) as client:
        auth = setup_auth(client)
        response = client.post(
            "/api/v1/rebalancing/plans", headers=auth.admin, json=payload
        )
    assert response.status_code == 422
