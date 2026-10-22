from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from src.forecast import FORECAST_HOURS, REGIONS, get_forecast

NOW = datetime(2026, 10, 21, 14, 35, tzinfo=UTC)


def test_hourly_points_from_current_hour() -> None:
    forecast = get_forecast("CISO", NOW)
    assert len(forecast.points) == FORECAST_HOURS
    assert forecast.points[0].start == datetime(2026, 10, 21, 14, tzinfo=UTC)
    assert forecast.generated_at == forecast.points[0].start
    gaps = {b.start - a.start for a, b in pairwise(forecast.points)}
    assert gaps == {timedelta(hours=1)}


def test_labeled_synthetic_and_fresh() -> None:
    forecast = get_forecast("CISO", NOW)
    assert forecast.data_source == "synthetic"
    assert forecast.stale is False


def test_same_inputs_give_same_forecast() -> None:
    assert get_forecast("ERCO", NOW) == get_forecast("ERCO", NOW)


@pytest.mark.parametrize("region", REGIONS)
def test_intensities_are_positive(region: str) -> None:
    assert all(point.intensity > 0 for point in get_forecast(region, NOW).points)


def test_regions_differ() -> None:
    ciso = [point.intensity for point in get_forecast("CISO", NOW).points]
    pjm = [point.intensity for point in get_forecast("PJM", NOW).points]
    assert ciso != pjm


def test_california_is_cleanest_around_midday() -> None:
    forecast = get_forecast("CISO", NOW)
    cleanest = min(forecast.points, key=lambda point: point.intensity)
    local_hour = (cleanest.start.hour + REGIONS["CISO"].utc_offset_hours) % 24
    assert 10 <= local_hour <= 14


def test_unknown_region_raises() -> None:
    with pytest.raises(ValueError, match="CISO"):
        get_forecast("NOPE", NOW)
