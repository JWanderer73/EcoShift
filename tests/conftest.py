import pytest
from fastapi.testclient import TestClient

NOW = "2026-10-27T14:30:00Z"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    """Every test gets an empty local store and a frozen clock."""
    monkeypatch.setenv("CARBON_STORE", "local")
    monkeypatch.setenv("CARBON_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("CARBON_CACHE_TTL", "0")
    monkeypatch.setenv("CARBON_NOW", NOW)
    monkeypatch.delenv("FAIL_STEP", raising=False)
    monkeypatch.delenv("CARBON_SHADOW", raising=False)
    monkeypatch.delenv("CARBON_MODEL", raising=False)


@pytest.fixture
def seeded():
    from carbon.jobs import pipeline

    pipeline.run()


@pytest.fixture
def client():
    from carbon.api.main import app

    return TestClient(app)
