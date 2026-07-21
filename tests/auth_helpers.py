from dataclasses import dataclass

from fastapi.testclient import TestClient


PASSWORD = "test-password-1234"


@dataclass
class AuthHeaders:
    admin: dict[str, str]
    drivers: dict[str, dict[str, str]]


def setup_auth(client: TestClient) -> AuthHeaders:
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    if login.status_code != 200:
        bootstrap = client.post(
            "/api/v1/auth/bootstrap",
            json={
                "username": "admin",
                "password": PASSWORD,
                "display_name": "테스트 관리자",
            },
        )
        assert bootstrap.status_code == 200
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": PASSWORD},
        )
    admin = {"Authorization": f"Bearer {login.json()['access_token']}"}

    drivers = {}
    for driver_id, name in (("D-1", "김기사"), ("D-2", "이기사")):
        created = client.post(
            "/api/v1/admin/users",
            headers=admin,
            json={
                "username": f"driver-{driver_id}",
                "password": PASSWORD,
                "display_name": name,
                "role": "driver",
                "driver_id": driver_id,
            },
        )
        assert created.status_code in {200, 409}
        driver_login = client.post(
            "/api/v1/auth/login",
            json={"username": f"driver-{driver_id}", "password": PASSWORD},
        )
        assert driver_login.status_code == 200
        drivers[driver_id] = {
            "Authorization": f"Bearer {driver_login.json()['access_token']}"
        }
    return AuthHeaders(admin=admin, drivers=drivers)
