import json
from datetime import UTC, datetime, timedelta

import pytest

from src.api import ApiError, get_windows

NOW = datetime(2026, 10, 21, 14, 35, tzinfo=UTC)
FORECAST_END = "2026-10-23T14:00:00+00:00"


def test_response_shape() -> None:
    response = get_windows(2, now=NOW)
    assert set(response) == {
        "region",
        "generated_at",
        "stale",
        "data_source",
        "job",
        "baseline",
        "windows",
    }
    assert response["region"] == "CISO"
    assert response["generated_at"] == "2026-10-21T14:00:00+00:00"
    assert response["data_source"] == "synthetic"
    assert response["job"] == {
        "duration_hours": 2,
        "deadline": FORECAST_END,
        "deadline_clamped": False,
    }
    assert set(response["baseline"]) == {"start", "end", "avg_intensity_g_per_kwh"}
    assert [w["rank"] for w in response["windows"]] == [1, 2, 3]
    assert set(response["windows"][0]) == {
        "rank",
        "start",
        "end",
        "avg_intensity_g_per_kwh",
        "co2_saved_pct",
    }
    json.dumps(response)


def test_windows_ranked_cleanest_first() -> None:
    windows = get_windows(3, now=NOW, top=5)["windows"]
    averages = [w["avg_intensity_g_per_kwh"] for w in windows]
    assert averages == sorted(averages)


def test_windows_end_by_deadline() -> None:
    deadline = NOW + timedelta(hours=10)
    windows = get_windows(2, deadline, now=NOW)["windows"]
    assert all(datetime.fromisoformat(w["end"]) <= deadline for w in windows)


def test_deadline_past_forecast_is_clamped() -> None:
    job = get_windows(2, NOW + timedelta(days=5), now=NOW)["job"]
    assert job["deadline_clamped"] is True
    assert job["deadline"] == FORECAST_END


def test_unknown_region_raises() -> None:
    with pytest.raises(ApiError, match="unknown region"):
        get_windows(2, region="NOPE", now=NOW)


def test_job_that_does_not_fit_raises() -> None:
    with pytest.raises(ApiError, match="doesn't fit"):
        get_windows(2, NOW + timedelta(hours=1), now=NOW)
