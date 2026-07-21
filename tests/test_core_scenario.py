from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.main import app
from app.test_scenario import (
    CreateTestScenarioRequest,
    build_scenario_plan_request,
    build_test_plan_request,
    create_sample_core_scenario,
)


def test_core_json_builds_virtual_drivers_and_inventory_snapshot():
    scenario = create_sample_core_scenario()
    request = build_test_plan_request(scenario)

    assert len(request.drivers) == 2
    assert request.drivers[0].driver_id == "DRIVER-01"
    assert request.live_stations is not None
    assert request.live_stations[0].available_bikes == 18
    assert request.options.use_tmap_navigation is True


def test_seeded_scenario_drivers_are_reproducible_and_inside_daejeon():
    core = create_sample_core_scenario().core
    assumed_at = datetime(2025, 7, 1, 8, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    scenario = CreateTestScenarioRequest(
        core=core,
        assumed_at=assumed_at,
        driver_count_min=3,
        driver_count_max=7,
        random_seed=20250701,
        use_tmap=False,
    )

    first = build_scenario_plan_request(scenario)
    second = build_scenario_plan_request(scenario)

    assert first.random_seed == second.random_seed == 20250701
    assert first.drivers == second.drivers
    assert 3 <= len(first.drivers) <= 7
    assert len({driver.driver_name for driver in first.drivers}) == len(first.drivers)
    assert len(
        {
            (driver.start_location.lat, driver.start_location.lng)
            for driver in first.drivers
        }
    ) == len(first.drivers)
    assert all(driver.start_at == assumed_at for driver in first.drivers)
    assert all(
        36.18 <= driver.start_location.lat <= 36.50
        and 127.25 <= driver.start_location.lng <= 127.56
        for driver in first.drivers
    )


def test_scenario_requires_timezone_and_valid_driver_range():
    core = create_sample_core_scenario().core
    with pytest.raises(ValidationError, match="timezone offset"):
        CreateTestScenarioRequest(
            core=core,
            assumed_at=datetime(2025, 7, 1, 8, 0),
        )

    with pytest.raises(ValidationError, match="driver_count_min"):
        CreateTestScenarioRequest(
            core=core,
            assumed_at=datetime(
                2025,
                7,
                1,
                8,
                0,
                tzinfo=ZoneInfo("Asia/Seoul"),
            ),
            driver_count_min=8,
            driver_count_max=3,
        )


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
