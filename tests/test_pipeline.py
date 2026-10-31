import pytest

from carbon.common import keys
from carbon.common.store import get_store
from carbon.jobs import gate, ingest, pipeline, predict, train


def test_pipeline_writes_forecasts_and_marks_success():
    pipeline.run()
    status = get_store().get_status()
    assert status["last_run_status"] == "success"
    assert status["fallback"] is False
    version = status["current_model_versions"]["demo-region"]
    forecast = get_store().get_forecast("demo-region", version)
    assert len(forecast["rows"]) == 48


def test_first_model_is_promoted_with_no_champion():
    ingest.run()
    train.run()
    result = gate.run()
    assert result["demo-region"]["promoted"] is True
    assert get_store().get_json(keys.champion("demo-region")) is not None


@pytest.mark.parametrize(
    "cand,champ,tol,expected",
    [(10, 10, 0.0, True), (11, 10, 0.0, False), (10.5, 10, 0.1, True), (9, 10, 0.0, True)],
)
def test_gate_decision(cand, champ, tol, expected):
    assert gate.should_promote(cand, champ, tol) is expected


def test_failed_step_records_failure_and_keeps_last_forecast():
    pipeline.run()
    good = get_store().get_status()["last_success_at"]

    import os

    os.environ["FAIL_STEP"] = "train"
    with pytest.raises(RuntimeError, match="train"):
        pipeline.run()
    status = get_store().get_status()
    assert status["last_run_status"] == "failed"
    assert "train" in status["last_error"]
    assert status["last_success_at"] == good  # last good run is remembered


def test_missing_champion_model_falls_back_to_baseline():
    ingest.run()
    predict_result = predict.run()  # no champion exists yet
    assert predict_result["fallback"] is True
    assert get_store().get_status()["fallback"] is True


def test_shadow_model_is_forecast_but_not_served(monkeypatch):
    pipeline.run()
    monkeypatch.setenv("CARBON_SHADOW", "1")
    monkeypatch.setenv("CARBON_MODEL", "hod_mean")
    monkeypatch.setenv("CARBON_NOW", "2026-10-27T17:30:00Z")
    ingest.run()
    train.run()
    result = predict.run()  # gate skipped on purpose: the candidate is not promoted
    assert result["shadow"]["demo-region"].startswith("hod_mean")
    assert result["versions"]["demo-region"].startswith("baseline")


def test_accuracy_job_scores_archived_forecasts_against_later_actuals(monkeypatch):
    from carbon.jobs import accuracy

    pipeline.run()  # forecast issued at 14:30 covers 14:00 onward
    monkeypatch.setenv("CARBON_NOW", "2026-10-27T17:30:00Z")
    ingest.run()  # actuals now exist up to 16:00
    result = accuracy.run()["demo-region/champion"]
    assert result["n"] == 3  # hours 14, 15, 16
    assert result["mae"] >= 0
    assert get_store().get_status()["rolling_mae"]["demo-region"] == result["mae"]
