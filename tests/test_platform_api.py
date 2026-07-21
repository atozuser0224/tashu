import base64
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from tests.auth_helpers import PASSWORD, setup_auth
from tests.test_planner import request_payload


def _plan(client: TestClient, admin: dict[str, str]) -> dict:
    payload = request_payload()
    payload["options"]["use_tmap_navigation"] = False
    payload["options"]["use_tmap_planning_matrix"] = False
    response = client.post(
        "/api/v1/rebalancing/plans", headers=admin, json=payload
    )
    assert response.status_code == 200
    return response.json()


def test_expo_web_cors_origin_is_allowed():
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/test/core-scenarios/sample",
            headers={
                "Origin": "http://localhost:8081",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Test-Role",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == (
            "http://localhost:8081"
        )


def test_auth_refresh_rotation_and_object_ownership():
    with TestClient(app) as client:
        auth = setup_auth(client)
        login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "driver-D-1",
                "password": PASSWORD,
                "device_id": "phone-1",
            },
        ).json()
        me = client.get("/api/v1/auth/me", headers=auth.drivers["D-1"])
        assert me.json()["driver_id"] == "D-1"

        refreshed = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": login["refresh_token"]},
        )
        assert refreshed.status_code == 200
        replay = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": login["refresh_token"]},
        )
        assert replay.status_code == 401

        plan = _plan(client, auth.admin)
        d1_mission = next(
            route for route in plan["routes"] if route["driver_id"] == "D-1"
        )
        mission = client.get(
            "/api/v1/operations/missions",
            headers=auth.drivers["D-1"],
            params={"driver_id": "D-1"},
        ).json()["missions"][0]
        assert mission["driver_id"] == d1_mission["driver_id"]
        forbidden = client.get(
            "/api/v1/operations/missions",
            headers=auth.drivers["D-1"],
            params={"driver_id": "D-2"},
        )
        assert forbidden.status_code == 403


def test_reassignment_incident_live_location_notifications_and_audit():
    with TestClient(app) as client:
        auth = setup_auth(client)
        plan = _plan(client, auth.admin)
        mission_id = plan["published_mission_ids"][0]

        reassigned = client.post(
            f"/api/v1/admin/missions/{mission_id}/reassign",
            headers=auth.admin,
            json={
                "driver_id": "D-2",
                "driver_name": "이기사",
                "reason": "D-1 차량 점검으로 재배정",
            },
        )
        assert reassigned.status_code == 200
        assert reassigned.json()["driver_id"] == "D-2"
        assert reassigned.json()["route"]["driver_id"] == "D-2"

        d1_forbidden = client.get(
            f"/api/v1/operations/missions/{mission_id}",
            headers=auth.drivers["D-1"],
        )
        assert d1_forbidden.status_code == 403

        client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=auth.drivers["D-2"],
            json={"driver_id": "D-2"},
        ).raise_for_status()
        client.post(
            f"/api/v1/operations/missions/{mission_id}/start",
            headers=auth.drivers["D-2"],
            json={"driver_id": "D-2"},
        ).raise_for_status()

        incident_body = {
            "incident_type": "access_blocked",
            "description": "공사 차량 때문에 대여소 진입 불가",
            "location": {"lat": 36.36, "lng": 127.35},
            "client_event_id": "offline-event-0001",
        }
        first = client.post(
            f"/api/v1/operations/missions/{mission_id}/incidents",
            headers=auth.drivers["D-2"],
            json=incident_body,
        )
        repeated = client.post(
            f"/api/v1/operations/missions/{mission_id}/incidents",
            headers=auth.drivers["D-2"],
            json=incident_body,
        )
        assert first.json()["incident_id"] == repeated.json()["incident_id"]

        damage = client.post(
            "/api/v1/operations/bikes/damage-reports",
            headers=auth.drivers["D-2"],
            json={
                "bike_qr_code": "DAMAGED-BIKE-001",
                "mission_id": mission_id,
                "description": "앞바퀴가 휘어 운행할 수 없음",
                "location": {"lat": 36.36, "lng": 127.35},
            },
        )
        assert damage.status_code == 200
        assert len(damage.json()["bike_qr_fingerprint"]) == 16

        skipped = client.post(
            f"/api/v1/admin/missions/{mission_id}/stops/1/skip",
            headers=auth.admin,
            json={"reason": "현장 접근 불가로 다음 정차지 진행"},
        )
        assert skipped.status_code == 200
        assert skipped.json()["stops"][0]["status"] == "skipped"

        now = datetime.now(timezone.utc)
        first_location = client.post(
            "/api/v1/operations/drivers/me/location",
            headers=auth.drivers["D-2"],
            json={
                "location": {"lat": 36.36, "lng": 127.35},
                "recorded_at": now.isoformat(),
                "accuracy_meters": 8,
                "speed_kmh": 20,
                "device_id": "phone-d2",
            },
        )
        assert first_location.status_code == 200
        impossible = client.post(
            "/api/v1/operations/drivers/me/location",
            headers=auth.drivers["D-2"],
            json={
                "location": {"lat": 37.36, "lng": 127.35},
                "recorded_at": (now + timedelta(seconds=1)).isoformat(),
                "accuracy_meters": 8,
                "speed_kmh": 20,
                "device_id": "phone-d2",
            },
        )
        assert impossible.json()["anomaly"] == "impossible_travel_speed"

        offline_event = {
            "events": [
                {
                    "event_id": "offline-location-0001",
                    "event_type": "location",
                    "payload": {
                        "location": {"lat": 37.36, "lng": 127.35},
                        "recorded_at": (now + timedelta(seconds=2)).isoformat(),
                        "accuracy_meters": 10,
                        "speed_kmh": 0,
                        "device_id": "phone-d2",
                    },
                }
            ]
        }
        synced = client.post(
            "/api/v1/operations/offline/sync",
            headers=auth.drivers["D-2"],
            json=offline_event,
        ).json()
        duplicate = client.post(
            "/api/v1/operations/offline/sync",
            headers=auth.drivers["D-2"],
            json=offline_event,
        ).json()
        assert synced["processed"] == 1
        assert duplicate["duplicates"] == 1

        live = client.get(
            "/api/v1/admin/operations/live", headers=auth.admin
        ).json()
        assert live["drivers"][0]["driver_id"] == "D-2"
        assert live["drivers"][0]["active_mission_id"] == mission_id

        notifications = client.get(
            "/api/v1/operations/notifications", headers=auth.drivers["D-2"]
        ).json()
        assert notifications["count"] >= 1
        marked = client.post(
            f"/api/v1/operations/notifications/"
            f"{notifications['notifications'][0]['notification_id']}/read",
            headers=auth.drivers["D-2"],
        )
        assert marked.json()["read_at"] is not None

        incidents = client.get(
            "/api/v1/admin/incidents", headers=auth.admin
        ).json()
        assert incidents["count"] == 1
        analytics = client.get(
            "/api/v1/admin/analytics/operations", headers=auth.admin
        ).json()
        assert analytics["incident_counts"]["open"] == 1
        audit = client.get("/api/v1/admin/audit-logs", headers=auth.admin).json()
        assert audit["count"] >= 2


def test_cancel_and_reoptimize_plan():
    with TestClient(app) as client:
        auth = setup_auth(client)
        original = _plan(client, auth.admin)
        mission_id = original["published_mission_ids"][0]
        cancelled = client.post(
            f"/api/v1/admin/missions/{mission_id}/cancel",
            headers=auth.admin,
            json={"reason": "운영 테스트 취소"},
        )
        assert cancelled.json()["status"] == "cancelled"

        payload = request_payload()
        payload["drivers"][0]["start_location"]["lat"] += 0.001
        payload["options"]["use_tmap_navigation"] = False
        payload["options"]["use_tmap_planning_matrix"] = False
        reoptimized = client.post(
            f"/api/v1/rebalancing/plans/{original['plan_id']}/reoptimize",
            headers=auth.admin,
            json=payload,
        )
        assert reoptimized.status_code == 200
        assert reoptimized.json()["plan_id"] != original["plan_id"]
        old = client.get(
            "/api/v1/operations/missions",
            headers=auth.admin,
            params={"status": "cancelled"},
        ).json()
        assert old["count"] >= 1


def test_test_mode_panel_bypasses_security_and_resets(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "true")
    with TestClient(app) as client:
        panel = client.get("/test-panel")
        assert panel.status_code == 200
        assert panel.headers["cache-control"] == "no-store"
        assert 'id="scenarioDate"' in panel.text
        assert 'id="roundId"' in panel.text
        assert 'id="tmapMap"' in panel.text
        assert "https://apis.openapi.sk.com/tmap/jsv2" in panel.text
        assert "httpsMode:true" in panel.text
        assert "document.createElement('script')" not in panel.text
        status = client.get("/api/v1/test/status").json()
        assert status["authentication_bypassed"] is True

        plan = client.post("/api/v1/test/demo/plan")
        assert plan.status_code == 200
        assert plan.json()["published_mission_ids"]
        missions = client.get("/api/v1/operations/missions").json()
        assert missions["count"] >= 1

        mission_id = missions["missions"][0]["mission_id"]
        mission = client.get(f"/api/v1/operations/missions/{mission_id}").json()
        driver_id = mission["driver_id"]
        first_stop = mission["stops"][0]

        qr = client.post(
            f"/api/v1/test/stations/{first_stop['station_id']}/qr",
            headers={"X-Test-Role": "admin"},
        )
        assert qr.status_code == 200
        qr_body = qr.json()
        assert qr_body["qr_payload"]
        assert qr_body["svg_data_url"].startswith("data:image/svg+xml;base64,")
        encoded_svg = qr_body["svg_data_url"].split(",", 1)[1]
        assert b"<svg" in base64.b64decode(encoded_svg)

        driver_headers = {
            "X-Test-Role": "driver",
            "X-Test-Driver-Id": driver_id,
        }
        own_missions = client.get(
            "/api/v1/operations/missions", headers=driver_headers
        ).json()
        assert own_missions["count"] >= 1
        assert all(item["driver_id"] == driver_id for item in own_missions["missions"])

        accepted = client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        assert accepted.status_code == 200
        started = client.post(
            f"/api/v1/operations/missions/{mission_id}/start",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        assert started.status_code == 200
        arrived = client.post(
            "/api/v1/operations/drivers/me/location",
            headers=driver_headers,
            json={
                "location": first_stop["location"],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "accuracy_meters": 3,
                "speed_kmh": 0,
                "device_id": "test-panel-device",
            },
        )
        assert arrived.status_code == 200
        assert arrived.json()["location"] == first_stop["location"]

        reset = client.post("/api/v1/test/reset")
        assert reset.json()["reset"] is True
        assert client.get("/api/v1/operations/missions").json()["count"] == 0
