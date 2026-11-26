from datetime import UTC, datetime, timedelta

import pytest

from src.forecast import ForecastPoint
from src.windows import find_best_windows

START = datetime(2026, 10, 21, 0, tzinfo=UTC)


def make_points(intensities: list[float]) -> list[ForecastPoint]:
    return [ForecastPoint(START + timedelta(hours=i), value) for i, value in enumerate(intensities)]


def forecast_end(points: list[ForecastPoint]) -> datetime:
    return points[-1].start + timedelta(hours=1)


def test_picks_lowest_window() -> None:
    points = make_points([300, 300, 100, 100, 300, 300])
    _, windows = find_best_windows(points, 2, forecast_end(points), top=1)
    assert windows[0].start == START + timedelta(hours=2)
    assert windows[0].end == START + timedelta(hours=4)
    assert windows[0].avg_intensity == 100


def test_co2_saved_is_relative_to_running_now() -> None:
    points = make_points([200, 200, 100, 100])
    baseline, windows = find_best_windows(points, 2, forecast_end(points), top=1)
    assert baseline.start == START
    assert baseline.avg_intensity == 200
    assert windows[0].co2_saved_pct == 50.0


def test_windows_do_not_overlap() -> None:
    # Hours 1-3 average 105, but they overlap the best window (hours 0-2).
    points = make_points([100, 100, 110, 300, 120, 120])
    _, windows = find_best_windows(points, 2, forecast_end(points), top=3)
    assert [w.start.hour for w in windows] == [0, 4, 2]


def test_windows_end_by_deadline() -> None:
    points = make_points([300, 300, 300, 100, 100])
    deadline = START + timedelta(hours=3)
    _, windows = find_best_windows(points, 2, deadline, top=3)
    assert [w.start.hour for w in windows] == [0]
    assert all(w.end <= deadline for w in windows)


def test_ties_go_to_earlier_start() -> None:
    points = make_points([200, 100, 200, 100, 200])
    _, windows = find_best_windows(points, 1, forecast_end(points), top=1)
    assert windows[0].start.hour == 1


def test_running_now_can_be_best() -> None:
    points = make_points([100, 200, 300])
    baseline, windows = find_best_windows(points, 1, forecast_end(points), top=1)
    assert windows[0] == baseline
    assert windows[0].co2_saved_pct == 0.0


def test_returns_fewer_than_top_when_windows_would_overlap() -> None:
    points = make_points([100, 100, 100, 100])
    _, windows = find_best_windows(points, 3, forecast_end(points), top=3)
    assert len(windows) == 1


def test_job_that_does_not_fit_raises() -> None:
    points = make_points([100, 100])
    with pytest.raises(ValueError, match="doesn't fit"):
        find_best_windows(points, 3, forecast_end(points))


@pytest.mark.parametrize(("duration_hours", "top"), [(0, 3), (2, 0)])
def test_rejects_non_positive_inputs(duration_hours: int, top: int) -> None:
    points = make_points([100, 100, 100])
    with pytest.raises(ValueError):
        find_best_windows(points, duration_hours, forecast_end(points), top)
