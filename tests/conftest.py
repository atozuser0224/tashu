import pytest


@pytest.fixture(autouse=True)
def isolated_operation_database(monkeypatch, tmp_path):
    monkeypatch.setenv("TASHU_DB_PATH", str(tmp_path / "operations.db"))
    monkeypatch.setenv("STATION_QR_ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("ALLOW_DEVELOPMENT_INTEGRITY", "true")
    monkeypatch.setenv("TEST_MODE", "false")
