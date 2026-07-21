from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from tests.auth_helpers import AuthHeaders, setup_auth
from tests.test_planner import request_payload


def _publish_plan(client: TestClient) -> tuple[str, dict, AuthHeaders]:
    auth = setup_auth(client)
    payload = request_payload()
    payload["options"]["use_tmap_navigation"] = False
    payload["options"]["use_tmap_planning_matrix"] = False
    response = client.post(
        "/api/v1/rebalancing/plans", headers=auth.admin, json=payload
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["published_mission_ids"]) == 2
    return body["published_mission_ids"][0], body, auth


def test_full_mission_flow_awards_reward_once():
    with TestClient(app) as client:
        _, plan, auth = _publish_plan(client)
        driver_id = plan["routes"][0]["driver_id"]
        driver_headers = auth.drivers[driver_id]

        listed = client.get(
            "/api/v1/operations/missions",
            headers=driver_headers,
            params={"driver_id": driver_id},
        )
        assert listed.status_code == 200
        mission = listed.json()["missions"][0]
        mission_id = mission["mission_id"]
        assert mission["status"] == "offered"
        assert mission["estimated_reward"]["total_points"] > 0

        bootstrap = client.get(
            "/api/v1/operations/bootstrap",
            headers=driver_headers,
            params={"driver_id": driver_id},
        ).json()
        assert bootstrap["wallet"]["balance_points"] == 0
        assert bootstrap["missions"][0]["mission_id"] == mission_id

        accepted = client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        assert accepted.json()["status"] == "accepted"

        started = client.post(
            f"/api/v1/operations/missions/{mission_id}/start",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        assert started.json()["status"] == "in_progress"
        stops = started.json()["stops"]

        far = client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/1/complete",
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": {"lat": 37.5, "lng": 127.0},
                "actual_quantity": stops[0]["planned_quantity"],
                "bike_qr_codes": [
                    f"FAR-BIKE-{index}"
                    for index in range(stops[0]["planned_quantity"])
                ],
            },
        )
        assert far.status_code == 422
        assert "너무 멉니다" in far.json()["detail"]

        if len(stops) > 1:
            out_of_order = client.post(
                f"/api/v1/operations/missions/{mission_id}/stops/2/complete",
                headers=driver_headers,
                json={
                    "driver_id": driver_id,
                    "location": stops[1]["location"],
                    "actual_quantity": stops[1]["planned_quantity"],
                    "bike_qr_codes": [],
                },
            )
            assert out_of_order.status_code == 409

        loaded_bikes: list[str] = []
        next_bike_number = 1
        for stop in stops:
            quantity = stop["planned_quantity"]
            if stop["action"] == "pickup":
                bike_qr_codes = [
                    f"BIKE-{next_bike_number + offset}" for offset in range(quantity)
                ]
                next_bike_number += quantity
                loaded_bikes.extend(bike_qr_codes)
            else:
                without_station_qr = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/complete",
                    headers=driver_headers,
                    json={
                        "driver_id": driver_id,
                        "location": stop["location"],
                        "actual_quantity": quantity,
                        "bike_qr_codes": loaded_bikes[:quantity],
                    },
                )
                assert without_station_qr.status_code == 409
                assert "QR" in without_station_qr.json()["detail"]

                provisioned = client.post(
                    f"/api/v1/admin/stations/{stop['station_id']}/qr",
                    headers={**auth.admin, "X-Admin-Key": "test-admin-key"},
                )
                assert provisioned.status_code == 200
                challenge = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/qr-challenge",
                    headers=driver_headers,
                    json={"driver_id": driver_id, "device_id": "test-device"},
                )
                assert challenge.status_code == 200
                verified = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/verify-qr",
                    headers=driver_headers,
                    json={
                        "driver_id": driver_id,
                        "location": stop["location"],
                        "qr_payload": provisioned.json()["qr_payload"],
                        "challenge_id": challenge.json()["challenge_id"],
                        "device_id": "test-device",
                        "integrity_provider": "development",
                        "integrity_token": "development-ok",
                    },
                )
                assert verified.status_code == 200
                verified_stop = verified.json()["stops"][stop["sequence"] - 1]
                assert verified_stop["qr_verification"] == "verified"
                assert verified_stop["qr_verified_location"] == stop["location"]
                replayed = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/verify-qr",
                    headers=driver_headers,
                    json={
                        "driver_id": driver_id,
                        "location": stop["location"],
                        "qr_payload": provisioned.json()["qr_payload"],
                        "challenge_id": challenge.json()["challenge_id"],
                        "device_id": "test-device",
                        "integrity_provider": "development",
                        "integrity_token": "development-ok",
                    },
                )
                assert replayed.status_code == 409
                bike_qr_codes = loaded_bikes[:quantity]
                del loaded_bikes[:quantity]

            completed = client.post(
                f"/api/v1/operations/missions/{mission_id}/stops/"
                f"{stop['sequence']}/complete",
                headers=driver_headers,
                json={
                    "driver_id": driver_id,
                    "location": stop["location"],
                    "actual_quantity": quantity,
                    "bike_qr_codes": bike_qr_codes,
                },
            )
            assert completed.status_code == 200

        mission = completed.json()
        assert mission["status"] == "completed"
        assert mission["awarded_reward"] == mission["estimated_reward"]

        repeated = client.post(
            f"/api/v1/operations/missions/{mission_id}/complete",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        assert repeated.status_code == 200
        assert repeated.json()["status"] == "completed"

        wallet = client.get(
            f"/api/v1/rewards/wallets/{driver_id}", headers=driver_headers
        ).json()
        assert wallet["balance_points"] == 0
        assert wallet["pending_points"] == mission["awarded_reward"]["total_points"]

        pending = client.get(
            "/api/v1/admin/rewards/reviews",
            headers=auth.admin,
            params={"status": "pending"},
        ).json()
        transaction_id = pending["transactions"][0]["transaction_id"]
        approved = client.post(
            f"/api/v1/admin/rewards/{transaction_id}/approved",
            headers=auth.admin,
            json={"reason": "QR, GPS 및 수량 검증 완료"},
        )
        assert approved.status_code == 200

        wallet = client.get(
            f"/api/v1/rewards/wallets/{driver_id}", headers=driver_headers
        ).json()
        assert wallet["balance_points"] == mission["awarded_reward"]["total_points"]
        assert wallet["completed_mission_count"] == 1

        transactions = client.get(
            f"/api/v1/rewards/wallets/{driver_id}/transactions",
            headers=driver_headers,
        ).json()
        assert transactions["count"] == 1
        assert transactions["transactions"][0]["mission_id"] == mission_id

        leaderboard = client.get(
            "/api/v1/rewards/leaderboard", headers=driver_headers
        ).json()
        assert leaderboard["entries"][0]["driver_id"] == driver_id
        assert leaderboard["entries"][0]["rank"] == 1

        now = datetime.now(timezone.utc)
        settlement = client.post(
            "/api/v1/admin/settlements",
            headers=auth.admin,
            json={
                "period_start": (now - timedelta(days=1)).isoformat(),
                "period_end": (now + timedelta(days=1)).isoformat(),
            },
        )
        assert settlement.status_code == 200
        assert settlement.json()["total_points"] == wallet["balance_points"]
        paid = client.post(
            f"/api/v1/admin/settlements/{settlement.json()['settlement_id']}/paid",
            headers=auth.admin,
            json={"reason": "테스트 정산 송금 완료"},
        )
        assert paid.json()["status"] == "paid"

        reversed_reward = client.post(
            f"/api/v1/admin/rewards/{transaction_id}/reversed",
            headers=auth.admin,
            json={"reason": "사후 재고 검증 불일치로 회수"},
        )
        assert reversed_reward.json()["status"] == "reversed"
        reversed_wallet = client.get(
            f"/api/v1/rewards/wallets/{driver_id}", headers=driver_headers
        ).json()
        assert reversed_wallet["balance_points"] == 0
        assert reversed_wallet["reversed_points"] == wallet["balance_points"]


def test_station_qr_cannot_be_forged_or_provisioned_without_admin_key():
    with TestClient(app) as client:
        _, plan, auth = _publish_plan(client)
        driver_id = plan["routes"][0]["driver_id"]
        driver_headers = auth.drivers[driver_id]
        mission = client.get(
            "/api/v1/operations/missions",
            headers=driver_headers,
            params={"driver_id": driver_id},
        ).json()["missions"][0]
        mission_id = mission["mission_id"]
        client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=driver_headers,
            json={"driver_id": driver_id},
        )
        detail = client.post(
            f"/api/v1/operations/missions/{mission_id}/start",
            headers=driver_headers,
            json={"driver_id": driver_id},
        ).json()
        pickup = detail["stops"][0]
        bike_codes = [
            f"FORGE-TEST-{index}" for index in range(pickup["planned_quantity"])
        ]
        client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/1/complete",
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": pickup["location"],
                "actual_quantity": pickup["planned_quantity"],
                "bike_qr_codes": bike_codes,
            },
        ).raise_for_status()
        dropoff = detail["stops"][1]

        unauthorized = client.post(
            f"/api/v1/admin/stations/{dropoff['station_id']}/qr",
            headers=auth.admin,
        )
        assert unauthorized.status_code == 403

        forged_challenge = client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/2/qr-challenge",
            headers=driver_headers,
            json={"driver_id": driver_id, "device_id": "test-device"},
        ).json()
        forged = client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/2/verify-qr",
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": dropoff["location"],
                "qr_payload": f"tashu-station:v1:{dropoff['station_id']}:forged",
                "challenge_id": forged_challenge["challenge_id"],
                "device_id": "test-device",
                "integrity_provider": "development",
                "integrity_token": "development-ok",
            },
        )
        assert forged.status_code == 422
        assert "위조" in forged.json()["detail"]

        wrong_station_qr = client.post(
            "/api/v1/admin/stations/WRONG-STATION/qr",
            headers={**auth.admin, "X-Admin-Key": "test-admin-key"},
        ).json()["qr_payload"]
        challenge = client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/2/qr-challenge",
            headers=driver_headers,
            json={"driver_id": driver_id, "device_id": "test-device"},
        ).json()
        wrong_station = client.post(
            f"/api/v1/operations/missions/{mission_id}/stops/2/verify-qr",
            headers=driver_headers,
            json={
                "driver_id": driver_id,
                "location": dropoff["location"],
                "qr_payload": wrong_station_qr,
                "challenge_id": challenge["challenge_id"],
                "device_id": "test-device",
                "integrity_provider": "development",
                "integrity_token": "development-ok",
            },
        )
        assert wrong_station.status_code == 422
        assert "현재 반납 대여소" in wrong_station.json()["detail"]


def test_only_assigned_driver_can_operate_mission():
    with TestClient(app) as client:
        mission_id, _, auth = _publish_plan(client)
        response = client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=auth.drivers["D-1"],
            json={"driver_id": "not-assigned"},
        )
    assert response.status_code == 403


def test_plan_publication_is_idempotent():
    with TestClient(app) as client:
        _, first, auth = _publish_plan(client)
        _, second, _ = _publish_plan(client)
        missions = client.get(
            "/api/v1/operations/missions", headers=auth.admin
        ).json()

    assert first["published_mission_ids"] == second["published_mission_ids"]
    assert missions["count"] == 2
