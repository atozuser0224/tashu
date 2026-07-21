from __future__ import annotations

import argparse
import csv
import io
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

from fastapi.testclient import TestClient

from app.main import app


def _reader(args: argparse.Namespace) -> TextIO:
    if args.stdin:
        return io.StringIO(sys.stdin.read().lstrip("\ufeff"))
    if args.git_object:
        completed = subprocess.run(
            ["rtk", "proxy", "git", "show", args.git_object],
            check=True,
            capture_output=True,
        )
        return io.StringIO(completed.stdout.decode("utf-8-sig"))
    return Path(args.csv).open(encoding="utf-8-sig", newline="")


def _station_payload(
    row: dict[str, str],
    flow: int,
    pressure: float,
    broken: int,
) -> dict:
    return {
        "station_id": row["station_id"],
        "station_name": row["name"].strip(),
        "location": {"lat": float(row["lat"]), "lng": float(row["lng"])},
        "weather": {"precip_band": "none", "temperature_c": 20.0},
        "ml": {"broken_suspected_count": broken},
        "stgnn": {
            "predicted_net_flow": flow,
            "shortage_pressure": pressure,
        },
    }


def build_request(rows: list[dict[str, str]]) -> dict:
    if len(rows) < 10:
        raise ValueError("station CSV needs at least 10 rows for the E2E scenario")

    source_indexes = [0, 8, 16, 24, 32]
    destination_indexes = [5, 13, 21, 29, 39]
    sources = {rows[index]["station_id"] for index in source_indexes}
    destinations = {
        rows[index]["station_id"]: 0.95 - order * 0.1
        for order, index in enumerate(destination_indexes)
    }

    core_stations = []
    live_stations = []
    for index, row in enumerate(rows):
        station_id = row["station_id"]
        if station_id in sources:
            flow = 8
            pressure = 0.1
            broken = 1 if index == source_indexes[0] else 0
            available = 14
        elif station_id in destinations:
            flow = -8
            pressure = destinations[station_id]
            broken = 0
            available = 1
        else:
            flow = 0
            pressure = 0.0
            broken = 0
            available = 5
        core_stations.append(
            _station_payload(row, flow=flow, pressure=pressure, broken=broken)
        )
        live_stations.append(
            {
                "station_id": station_id,
                "station_name": row["name"].strip(),
                "location": {
                    "lat": float(row["lat"]),
                    "lng": float(row["lng"]),
                },
                "available_bikes": available,
                "address": f"{row['gu']} {row['dong']}",
            }
        )

    return {
        "core": {
            "meta": {
                "generated_at": "2026-07-21T15:55:00+09:00",
                "horizon": "16:00→20:00",
                "demo_mode": False,
                "fixture_source": "PR station_master.csv",
            },
            "stations": core_stations,
        },
        "drivers": [
            {
                "driver_id": "CSV-DRIVER-WEST",
                "driver_name": "서쪽 기사",
                "start_at": "2026-07-21T16:00:00+09:00",
                "start_location": {"lat": 36.3620, "lng": 127.3315},
                "vehicle_capacity": 8,
            },
            {
                "driver_id": "CSV-DRIVER-EAST",
                "driver_name": "동쪽 기사",
                "start_at": "2026-07-21T16:05:00+09:00",
                "start_location": {"lat": 36.3630, "lng": 127.3580},
                "vehicle_capacity": 8,
            },
            {
                "driver_id": "CSV-DRIVER-SOUTH",
                "driver_name": "남쪽 기사",
                "start_at": "2026-07-21T16:10:00+09:00",
                "start_location": {"lat": 36.3515, "lng": 127.3440},
                "vehicle_capacity": 8,
            },
        ],
        "live_stations": live_stations,
        "options": {
            "use_live_tashu": False,
            "use_tmap_planning_matrix": True,
            "use_tmap_navigation": True,
            "reserve_bikes_per_source": 2,
        },
    }


def summarize(response_body: dict, operation_results: list[dict] | None = None) -> dict:
    summary = {
        "executed_at": datetime.now().astimezone().isoformat(),
        "status": response_body["status"],
        "data_sources": response_body["data_sources"],
        "summary": response_body["summary"],
        "warnings": response_body["warnings"],
        "published_mission_ids": response_body["published_mission_ids"],
        "routes": [
            {
                "driver_id": route["driver_id"],
                "first_pickup": (
                    route["stops"][0]["station_name"] if route["stops"] else None
                ),
                "first_pickup_distance_km": route["first_pickup_distance_km"],
                "first_pickup_travel_seconds": route["first_pickup_travel_seconds"],
                "stop_order": [
                    f"{stop['action']}:{stop['station_name']}:{stop['quantity']}"
                    for stop in route["stops"]
                ],
                "bikes_moved": route["total_bikes_moved"],
                "road_distance_km": route["total_distance_km"],
                "estimated_finish_at": route["estimated_finish_at"],
                "road_coordinate_count": (
                    len(route["navigation"]["coordinates"])
                    if route["navigation"]
                    else 0
                ),
                "first_instruction": (
                    route["navigation"]["instructions"][0]["description"]
                    if route["navigation"]
                    and route["navigation"]["instructions"]
                    else None
                ),
            }
            for route in response_body["routes"]
        ],
    }
    if operation_results is not None:
        summary["completed_operations"] = operation_results
    return summary


def complete_missions(
    client: TestClient,
    response_body: dict,
    admin_headers: dict[str, str],
    driver_headers: dict[str, dict[str, str]],
) -> list[dict]:
    results = []
    for mission_id in response_body["published_mission_ids"]:
        mission = client.get(
            f"/api/v1/operations/missions/{mission_id}", headers=admin_headers
        ).json()
        driver_id = mission["driver_id"]
        headers = driver_headers[driver_id]
        client.post(
            f"/api/v1/operations/missions/{mission_id}/accept",
            headers=headers,
            json={"driver_id": driver_id},
        ).raise_for_status()
        mission = client.post(
            f"/api/v1/operations/missions/{mission_id}/start",
            headers=headers,
            json={"driver_id": driver_id},
        ).json()
        loaded_bikes: list[str] = []
        bike_number = 1
        for stop in mission["stops"]:
            quantity = stop["planned_quantity"]
            if stop["action"] == "pickup":
                bike_qr_codes = [
                    f"E2E-{mission_id}-{bike_number + offset}"
                    for offset in range(quantity)
                ]
                bike_number += quantity
                loaded_bikes.extend(bike_qr_codes)
            else:
                qr_response = client.post(
                    f"/api/v1/admin/stations/{stop['station_id']}/qr",
                    headers={
                        **admin_headers,
                        "X-Admin-Key": os.environ["STATION_QR_ADMIN_KEY"]
                    },
                )
                qr_response.raise_for_status()
                challenge = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/qr-challenge",
                    headers=headers,
                    json={"driver_id": driver_id, "device_id": "csv-e2e-device"},
                )
                challenge.raise_for_status()
                verification = client.post(
                    f"/api/v1/operations/missions/{mission_id}/stops/"
                    f"{stop['sequence']}/verify-qr",
                    headers=headers,
                    json={
                        "driver_id": driver_id,
                        "location": stop["location"],
                        "qr_payload": qr_response.json()["qr_payload"],
                        "challenge_id": challenge.json()["challenge_id"],
                        "device_id": "csv-e2e-device",
                        "integrity_provider": "development",
                        "integrity_token": "development-ok",
                    },
                )
                verification.raise_for_status()
                bike_qr_codes = loaded_bikes[:quantity]
                del loaded_bikes[:quantity]
            response = client.post(
                f"/api/v1/operations/missions/{mission_id}/stops/"
                f"{stop['sequence']}/complete",
                headers=headers,
                json={
                    "driver_id": driver_id,
                    "location": stop["location"],
                    "actual_quantity": quantity,
                    "bike_qr_codes": bike_qr_codes,
                },
            )
            response.raise_for_status()
            mission = response.json()
        reviews = client.get(
            "/api/v1/admin/rewards/reviews",
            headers=admin_headers,
            params={"status": "pending"},
        ).json()["transactions"]
        reward = next(item for item in reviews if item["mission_id"] == mission_id)
        client.post(
            f"/api/v1/admin/rewards/{reward['transaction_id']}/approved",
            headers=admin_headers,
            json={"reason": "CSV E2E 자동 검증 완료"},
        ).raise_for_status()
        wallet = client.get(
            f"/api/v1/rewards/wallets/{driver_id}", headers=headers
        ).json()
        results.append(
            {
                "mission_id": mission_id,
                "driver_id": driver_id,
                "status": mission["status"],
                "verified_dropoff_count": sum(
                    stop["action"] == "dropoff"
                    and stop["qr_verification"] == "verified"
                    for stop in mission["stops"]
                ),
                "scanned_bike_qr_count": sum(
                    stop["bike_qr_count"]
                    for stop in mission["stops"]
                    if stop["action"] == "dropoff"
                ),
                "awarded_reward": mission["awarded_reward"],
                "wallet_balance_points": wallet["balance_points"],
            }
        )
    return results


def authenticate_e2e(
    client: TestClient, payload: dict
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    password = "csv-e2e-password-1234"
    client.post(
        "/api/v1/auth/bootstrap",
        json={
            "username": "csv-admin",
            "password": password,
            "display_name": "CSV 관리자",
        },
    ).raise_for_status()
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "csv-admin", "password": password},
    ).json()
    admin_headers = {"Authorization": f"Bearer {login['access_token']}"}
    driver_headers = {}
    for driver in payload["drivers"]:
        username = driver["driver_id"].lower()
        client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "username": username,
                "password": password,
                "display_name": driver["driver_name"],
                "role": "driver",
                "driver_id": driver["driver_id"],
            },
        ).raise_for_status()
        driver_login = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        ).json()
        driver_headers[driver["driver_id"]] = {
            "Authorization": f"Bearer {driver_login['access_token']}"
        }
    return admin_headers, driver_headers


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv")
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--git-object")
    parser.add_argument("--complete-missions", action="store_true")
    parser.add_argument("--database-path")
    args = parser.parse_args()

    if args.database_path:
        os.environ["TASHU_DB_PATH"] = args.database_path
    if args.complete_missions and not os.getenv("STATION_QR_ADMIN_KEY"):
        os.environ["STATION_QR_ADMIN_KEY"] = secrets.token_urlsafe(32)
    if args.complete_missions:
        os.environ["ALLOW_DEVELOPMENT_INTEGRITY"] = "true"

    stream = _reader(args)
    try:
        rows = list(csv.DictReader(stream))
    finally:
        if stream is not sys.stdin:
            stream.close()
    payload = build_request(rows)
    with TestClient(app) as client:
        admin_headers, driver_headers = authenticate_e2e(client, payload)
        response = client.post(
            "/api/v1/rebalancing/plans", headers=admin_headers, json=payload
        )
        if response.status_code != 200:
            print(response.text, file=sys.stderr)
            return 1
        body = response.json()
        operation_results = (
            complete_missions(client, body, admin_headers, driver_headers)
            if args.complete_missions
            else None
        )
    print(
        json.dumps(
            summarize(body, operation_results), ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
