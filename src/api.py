"""Local stand-in for the EcoShift API.

``get_windows`` and ``get_forecast`` return the same JSON-ready responses as
the real API's ``/windows`` and ``/forecast`` endpoints. For now they run on
synthetic forecasts. When the API is deployed, they become HTTP calls and the
CLI doesn't change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.forecast import REGIONS
from src.forecast import get_forecast as _synthetic_forecast
from src.windows import Window, find_best_windows

DEFAULT_REGION = "CISO"
DEFAULT_TOP = 3
SUPPORTED_REGIONS = tuple(REGIONS)


class ApiError(Exception):
    """A request the API rejects. The message is safe to show the user."""


def get_windows(
    duration_hours: int,
    deadline: datetime | None = None,
    region: str = DEFAULT_REGION,
    top: int = DEFAULT_TOP,
    now: datetime | None = None,
) -> dict:
    """Return the best windows for a job, shaped like the API's JSON response.

    Args:
        duration_hours: Job length in whole hours.
        deadline: Latest time the job may finish, timezone-aware. ``None``
            means the end of the forecast. A later deadline is clamped to
            the end of the forecast.
        region: EIA balancing-authority code, one of ``SUPPORTED_REGIONS``.
        top: Maximum number of windows to return.
        now: Current time, timezone-aware. Defaults to the real current time.

    Returns:
        A JSON-serializable dict with ``region``, ``generated_at``, ``stale``,
        ``data_source``, ``job``, ``baseline`` and ranked ``windows``.

    Raises:
        ApiError: If the region is unknown or the job doesn't fit before the
            deadline.
    """
    try:
        forecast = _synthetic_forecast(region, now)
    except ValueError as err:
        raise ApiError(str(err)) from err
    forecast_end = forecast.points[-1].start + timedelta(hours=1)
    clamped = deadline is not None and deadline > forecast_end
    if deadline is None or clamped:
        deadline = forecast_end
    try:
        baseline, windows = find_best_windows(forecast.points, duration_hours, deadline, top)
    except ValueError as err:
        raise ApiError(str(err)) from err

    return {
        "region": forecast.region,
        "generated_at": _iso(forecast.generated_at),
        "stale": forecast.stale,
        "data_source": forecast.data_source,
        "job": {
            "duration_hours": duration_hours,
            "deadline": _iso(deadline),
            "deadline_clamped": clamped,
        },
        "baseline": {
            "start": _iso(baseline.start),
            "end": _iso(baseline.end),
            "avg_intensity_g_per_kwh": baseline.avg_intensity,
        },
        "windows": [_window_json(rank, w) for rank, w in enumerate(windows, start=1)],
    }


def get_forecast(region: str = DEFAULT_REGION, now: datetime | None = None) -> dict:
    """Return the hourly forecast, shaped like the API's ``/forecast`` response.

    Args:
        region: EIA balancing-authority code, one of ``SUPPORTED_REGIONS``.
        now: Current time, timezone-aware. Defaults to the real current time.

    Returns:
        A JSON-serializable dict with ``region``, ``generated_at``, ``stale``,
        ``data_source`` and ``points``: consecutive hours, each with its
        ``start`` and ``intensity`` in gCO2/kWh.

    Raises:
        ApiError: If the region is unknown.
    """
    try:
        forecast = _synthetic_forecast(region, now)
    except ValueError as err:
        raise ApiError(str(err)) from err
    return {
        "region": forecast.region,
        "generated_at": _iso(forecast.generated_at),
        "stale": forecast.stale,
        "data_source": forecast.data_source,
        "points": [{"start": _iso(p.start), "intensity": p.intensity} for p in forecast.points],
    }


def _window_json(rank: int, window: Window) -> dict:
    return {
        "rank": rank,
        "start": _iso(window.start),
        "end": _iso(window.end),
        "avg_intensity_g_per_kwh": window.avg_intensity,
        "co2_saved_pct": window.co2_saved_pct,
    }


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()
