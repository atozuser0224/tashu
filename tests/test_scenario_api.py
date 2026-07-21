from fastapi.testclient import TestClient

from app.main import app


ADMIN_HEADERS = {"X-Test-Role": "admin"}


def test_real_core_model_drives_phone_scenario_and_qr_sequence(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "true")
    with TestClient(app) as client:
        status = client.get(
            "/api/v1/test/core-model/status",
            headers=ADMIN_HEADERS,
        )
        assert status.status_code == 200
        assert status.json()["available"] is True
        assert status.json()["loaded"] is True
        assert "b3e9133726b5eee5ac3472f7282dcc5d5bb16f09" in status.json()[
            "source"
        ]
        assert status.json()["inventory_source"].startswith("synthetic_")
        assert status.json()["available_dates"][0] == "2024-08-03"
        assert "C" in status.json()["available_rounds_by_date"]["2026-03-17"]

        overnight = client.get(
            "/api/v1/test/core-model/snapshot",
            headers=ADMIN_HEADERS,
            params={"date": "2026-03-17", "round_id": "D"},
        )
        assert overnight.status_code == 200, overnight.text
        assert overnight.json()["assumed_at"] == "2026-03-18T03:00:00+09:00"

        created = client.post(
            "/api/v1/test/scenarios",
            headers=ADMIN_HEADERS,
            json={
                "core_model": {"date": "2026-03-17", "round_id": "C"},
                "assumed_at": "2026-03-17T16:00:00+09:00",
                "driver_count_min": 2,
                "driver_count_max": 2,
                "random_seed": 7317,
                "vehicle_capacity": 8,
                "work_minutes": 240,
                "use_tmap": False,
            },
        )
        assert created.status_code == 200, created.text
        scenario = created.json()
        assert scenario["assumed_at"] == "2026-03-17T16:00:00+09:00"
        assert len(scenario["drivers"]) == 2
        assigned_route = next(
            route for route in scenario["plan"]["routes"] if route["stops"]
        )
        driver_id = assigned_route["driver_id"]

        bound = client.put(
            "/api/v1/test/devices/RIDEGO-TEST-DEVICE-01/assignment",
            headers=ADMIN_HEADERS,
            json={"driver_id": driver_id},
        )
        assert bound.status_code == 200
        assert bound.json()["driver_id"] == driver_id

        assignment = client.get(
            "/api/v1/test/devices/RIDEGO-TEST-DEVICE-01/assignment"
        )
        assert assignment.status_code == 200
        assert assignment.json()["plan_id"] == scenario["plan"]["plan_id"]

        before = client.get(f"/api/v1/test/drivers/{driver_id}/state")
        assert before.status_code == 200
        assert before.json()["arrived"] is False

        moved = client.post(
            (
                f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                f"/drivers/{driver_id}/move-next"
            ),
            headers=ADMIN_HEADERS,
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["arrived"] is True
        assert moved.json()["mission_status"] == "in_progress"
        assert moved.json()["current_location"] == moved.json()["next_stop"]["location"]

        qr_sequence = client.get(
            (
                f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                f"/drivers/{driver_id}/qr-sequence"
            ),
            headers=ADMIN_HEADERS,
        )
        assert qr_sequence.status_code == 200, qr_sequence.text
        sequence = qr_sequence.json()
        assert sequence["stop_action"] == "pickup"
        assert len(sequence["items"]) == moved.json()["next_stop"]["planned_quantity"]
        assert all(item["kind"] == "bike" for item in sequence["items"])
        assert all(
            item["svg_data_url"].startswith("data:image/svg+xml;base64,")
            for item in sequence["items"]
        )

        driver_headers = {
            "X-Test-Role": "driver",
            "X-Test-Driver-Id": driver_id,
        }
        pickup_codes = [item["payload"] for item in sequence["items"]]
        completed_pickup = client.post(
            (
                f"/api/v1/operations/missions/{sequence['mission_id']}"
                f"/stops/{sequence['stop_sequence']}/complete"
            ),
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": moved.json()["current_location"],
                "actual_quantity": len(pickup_codes),
                "bike_qr_codes": pickup_codes,
            },
        )
        assert completed_pickup.status_code == 200, completed_pickup.text

        moved_dropoff = client.post(
            (
                f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                f"/drivers/{driver_id}/move-next"
            ),
            headers=ADMIN_HEADERS,
        )
        assert moved_dropoff.status_code == 200, moved_dropoff.text
        assert moved_dropoff.json()["next_stop"]["action"] == "dropoff"

        dropoff_qrs = client.get(
            (
                f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                f"/drivers/{driver_id}/qr-sequence"
            ),
            headers=ADMIN_HEADERS,
        )
        assert dropoff_qrs.status_code == 200, dropoff_qrs.text
        dropoff_sequence = dropoff_qrs.json()
        assert dropoff_sequence["items"][0]["kind"] == "station"
        assert [
            item["payload"]
            for item in dropoff_sequence["items"]
            if item["kind"] == "bike"
        ] == pickup_codes

        challenge = client.post(
            (
                f"/api/v1/operations/missions/{sequence['mission_id']}"
                f"/stops/{dropoff_sequence['stop_sequence']}/qr-challenge"
            ),
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "device_id": "RIDEGO-TEST-DEVICE-01",
            },
        )
        assert challenge.status_code == 200, challenge.text
        verified = client.post(
            (
                f"/api/v1/operations/missions/{sequence['mission_id']}"
                f"/stops/{dropoff_sequence['stop_sequence']}/verify-qr"
            ),
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": moved_dropoff.json()["current_location"],
                "qr_payload": dropoff_sequence["items"][0]["payload"],
                "challenge_id": challenge.json()["challenge_id"],
                "device_id": "RIDEGO-TEST-DEVICE-01",
                "integrity_provider": "development",
            },
        )
        assert verified.status_code == 200, verified.text

        dropoff_codes = [
            item["payload"]
            for item in dropoff_sequence["items"]
            if item["kind"] == "bike"
        ]
        completed = client.post(
            (
                f"/api/v1/operations/missions/{sequence['mission_id']}"
                f"/stops/{dropoff_sequence['stop_sequence']}/complete"
            ),
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": moved_dropoff.json()["current_location"],
                "actual_quantity": len(dropoff_codes),
                "bike_qr_codes": dropoff_codes,
            },
        )
        assert completed.status_code == 200, completed.text
        mission = completed.json()

        # Some core snapshots create routes with more than one pickup/drop-off pair.
        # Finish every remaining stop through the same admin-arrival + phone-QR flow.
        while mission["status"] != "completed":
            moved_next = client.post(
                (
                    f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                    f"/drivers/{driver_id}/move-next"
                ),
                headers=ADMIN_HEADERS,
            )
            assert moved_next.status_code == 200, moved_next.text
            next_state = moved_next.json()
            next_qrs_response = client.get(
                (
                    f"/api/v1/test/scenarios/{scenario['scenario_id']}"
                    f"/drivers/{driver_id}/qr-sequence"
                ),
                headers=ADMIN_HEADERS,
            )
            assert next_qrs_response.status_code == 200, next_qrs_response.text
            next_qrs = next_qrs_response.json()
            bike_codes = [
                item["payload"]
                for item in next_qrs["items"]
                if item["kind"] == "bike"
            ]
            if next_qrs["stop_action"] == "dropoff":
                station_item = next(
                    item for item in next_qrs["items"] if item["kind"] == "station"
                )
                next_challenge = client.post(
                    (
                        f"/api/v1/operations/missions/{sequence['mission_id']}"
                        f"/stops/{next_qrs['stop_sequence']}/qr-challenge"
                    ),
                    headers=driver_headers,
                    json={
                        "driver_id": driver_id,
                        "device_id": "RIDEGO-TEST-DEVICE-01",
                    },
                )
                assert next_challenge.status_code == 200, next_challenge.text
                next_verified = client.post(
                    (
                        f"/api/v1/operations/missions/{sequence['mission_id']}"
                        f"/stops/{next_qrs['stop_sequence']}/verify-qr"
                    ),
                    headers=driver_headers,
                    json={
                        "driver_id": driver_id,
                        "location": next_state["current_location"],
                        "qr_payload": station_item["payload"],
                        "challenge_id": next_challenge.json()["challenge_id"],
                        "device_id": "RIDEGO-TEST-DEVICE-01",
                        "integrity_provider": "development",
                    },
                )
                assert next_verified.status_code == 200, next_verified.text

            completed = client.post(
                (
                    f"/api/v1/operations/missions/{sequence['mission_id']}"
                    f"/stops/{next_qrs['stop_sequence']}/complete"
                ),
                headers=driver_headers,
                json={
                    "driver_id": driver_id,
                    "location": next_state["current_location"],
                    "actual_quantity": len(bike_codes),
                    "bike_qr_codes": bike_codes,
                },
            )
            assert completed.status_code == 200, completed.text
            mission = completed.json()

        assert mission["awarded_reward"] == mission["estimated_reward"]
        assert mission["awarded_reward"]["total_points"] > 0
        wallet = client.get(
            f"/api/v1/rewards/wallets/{driver_id}",
            headers=driver_headers,
        )
        assert wallet.status_code == 200, wallet.text
        assert wallet.json()["pending_points"] == mission["awarded_reward"][
            "total_points"
        ]
