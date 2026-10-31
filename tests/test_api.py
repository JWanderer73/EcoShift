import pytest

from carbon.common.store import get_store


def test_health_before_any_run_reports_no_data(client):
    r = client.get("/v1/health")
    assert r.status_code == 200  # stays 200 so the load balancer keeps the task
    assert r.json()["status"] == "no_data"


def test_forecast_before_any_run_is_503(client):
    r = client.get("/v1/forecast")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "no_forecast"


def test_forecast_rows_start_at_the_current_hour(client, seeded):
    body = client.get("/v1/forecast", params={"hours": 24}).json()
    assert len(body["rows"]) == 24
    assert body["rows"][0]["ts"] == "2026-10-27T14:00:00Z"
    assert body["warnings"] == [] and body["stale"] is False


def test_windows_shape_and_recommendation(client, seeded):
    body = client.get("/v1/windows", params={"duration_hours": 4, "max_wait": "1d"}).json()
    assert body["recommendation"] in {"run_now", "delay"}
    assert body["best"]["savings_pct"] >= max(w["savings_pct"] for w in body["alternatives"] or [body["best"]])
    assert [s["max_wait_hours"] for s in body["savings_by_max_wait"]] == [3, 12, 24]
    assert body["request"]["max_delay_hours"] == 24
    # waiting longer can never be worse than waiting less
    saved = [s["savings_pct"] for s in body["savings_by_max_wait"]]
    assert saved == sorted(saved)


def test_deadline_limits_the_wait(client, seeded):
    body = client.get(
        "/v1/windows", params={"duration_hours": 4, "deadline": "2026-10-27T23:00:00Z"}
    ).json()
    assert body["best"]["end"] <= "2026-10-27T23:00:00Z"


def test_wait_longer_than_the_forecast_is_clamped_with_a_warning(client, seeded):
    body = client.get("/v1/windows", params={"duration_hours": 4, "max_wait": "10d"}).json()
    assert "wait_clamped_to_horizon" in body["warnings"]
    assert body["request"]["max_delay_hours"] == 44


@pytest.mark.parametrize(
    "params,status,code",
    [
        ({"duration_hours": 4, "location": "nowhere"}, 404, "unsupported_location"),
        ({"duration_hours": 4, "max_wait": "1d", "deadline": "2026-10-28T00:00:00Z"}, 422, "conflicting_parameters"),
        ({"duration_hours": 4, "max_wait": "soon"}, 422, "invalid_max_wait"),
        ({"duration_hours": 4, "deadline": "2026-10-27T10:00:00Z"}, 422, "deadline_too_soon"),
        ({"duration_hours": 100}, 422, "duration_exceeds_horizon"),
    ],
)
def test_bad_requests_return_clear_errors(client, seeded, params, status, code):
    r = client.get("/v1/windows", params=params)
    assert r.status_code == status
    assert r.json()["error"]["code"] == code


def test_pipeline_failure_still_serves_the_last_forecast_with_a_warning(client, seeded):
    get_store().update_status({"last_run_status": "failed", "last_error": "train: boom"})
    r = client.get("/v1/windows", params={"duration_hours": 4})
    assert r.status_code == 200
    assert "pipeline_failed" in r.json()["warnings"]
    assert client.get("/v1/health").json()["status"] == "degraded"


def test_a_pipeline_that_stops_running_is_reported_as_stale(client, seeded, monkeypatch):
    monkeypatch.setenv("CARBON_NOW", "2026-10-27T23:30:00Z")  # 9 hours later, no new run
    body = client.get("/v1/windows", params={"duration_hours": 4}).json()
    assert body["stale"] is True and "forecast_stale" in body["warnings"]


def test_forecast_expires_when_no_hours_are_left(client, seeded, monkeypatch):
    monkeypatch.setenv("CARBON_NOW", "2026-10-30T00:00:00Z")
    r = client.get("/v1/forecast")
    assert r.status_code == 503 and r.json()["error"]["code"] == "forecast_expired"


def test_fallback_and_degraded_data_warnings(client, seeded):
    get_store().update_status({"fallback": True, "imputed_fraction": 0.5})
    warnings = client.get("/v1/forecast").json()["warnings"]
    assert "model_fallback" in warnings and "data_quality_degraded" in warnings
