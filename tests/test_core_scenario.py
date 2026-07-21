from fastapi.testclient import TestClient

from app.main import app
from app.test_scenario import build_test_plan_request, create_sample_core_scenario


def test_core_json_builds_virtual_drivers_and_inventory_snapshot():
    scenario = create_sample_core_scenario()
    request = build_test_plan_request(scenario)

    assert len(request.drivers) == 2
    assert request.drivers[0].driver_id == "DRIVER-01"
    assert request.live_stations is not None
    assert request.live_stations[0].available_bikes == 18
    assert request.options.use_tmap_navigation is True


def test_core_scenario_plan_publishes_map_routes_and_driver_missions(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "true")
    with TestClient(app) as client:
        client.post("/api/v1/test/reset").raise_for_status()
        sample = client.get("/api/v1/test/core-scenarios/sample")
        assert sample.status_code == 200
        payload = sample.json()
        payload["use_tmap"] = False

        response = client.post("/api/v1/test/core-scenarios/plan", json=payload)
        assert response.status_code == 200
        plan = response.json()
        assert plan["routes"]
        assert plan["map_data"]["routes"]
        assert plan["map_data"]["markers"]
        assert plan["published_mission_ids"]
        assert {route["driver_id"] for route in plan["routes"]} <= {
            "DRIVER-01",
            "DRIVER-02",
        }

        driver_missions = client.get(
            "/api/v1/operations/missions",
            headers={
                "X-Test-Role": "driver",
                "X-Test-Driver-Id": "DRIVER-01",
            },
        )
        assert driver_missions.status_code == 200
        assert all(
            mission["driver_id"] == "DRIVER-01"
            for mission in driver_missions.json()["missions"]
        )
