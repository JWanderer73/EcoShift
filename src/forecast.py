"""Synthetic carbon-intensity forecasts.

The real forecasts will come from the ML pipeline through the API. Until that
exists, this module makes up a believable 48-hour forecast so the CLI has
something to run against. Every number in here is made up.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

FORECAST_HOURS = 48
DATA_SOURCE = "synthetic"
NOISE_FRACTION = 0.03  # ±3% jitter so the curve isn't perfectly smooth
SUNRISE_HOUR = 6  # local hour the solar dip starts
SUNSET_HOUR = 18  # local hour the solar dip ends
EVENING_PEAK_HOUR = 19  # local hour demand peaks after solar drops off
EVENING_PEAK_WIDTH_HOURS = 2.0


@dataclass(frozen=True)
class RegionProfile:
    """Made-up shape of one region's daily carbon-intensity curve.

    Attributes:
        base: Overnight intensity in gCO2/kWh.
        solar_dip: How far intensity drops at solar noon, in gCO2/kWh.
        evening_peak: How far intensity rises at the evening peak, in gCO2/kWh.
        utc_offset_hours: Fixed offset used to place the dip and peak in
            local time. Daylight saving is ignored.
    """

    base: float
    solar_dip: float
    evening_peak: float
    utc_offset_hours: int


# Rough, made-up shapes for three EIA balancing authorities: California has a
# deep solar dip, while Texas and PJM lean more on gas and coal.
REGIONS: dict[str, RegionProfile] = {
    "CISO": RegionProfile(base=260, solar_dip=140, evening_peak=60, utc_offset_hours=-8),
    "ERCO": RegionProfile(base=400, solar_dip=80, evening_peak=50, utc_offset_hours=-6),
    "PJM": RegionProfile(base=380, solar_dip=40, evening_peak=40, utc_offset_hours=-5),
}


@dataclass(frozen=True)
class ForecastPoint:
    """Forecast carbon intensity (gCO2/kWh) for the hour [start, start + 1h)."""

    start: datetime
    intensity: float


@dataclass(frozen=True)
class Forecast:
    """An hourly carbon-intensity forecast for one region."""

    region: str
    generated_at: datetime
    stale: bool
    data_source: str
    points: list[ForecastPoint]


def get_forecast(region: str, now: datetime | None = None) -> Forecast:
    """Return a synthetic 48-hour forecast starting at the current UTC hour.

    Args:
        region: EIA balancing-authority code, one of ``REGIONS``.
        now: Current time, timezone-aware. Defaults to the real current time.

    Returns:
        A forecast whose first point starts at the top of ``now``'s hour.

    Raises:
        ValueError: If ``region`` isn't in ``REGIONS``.
    """
    if region not in REGIONS:
        raise ValueError(f"unknown region {region!r}; choose one of {', '.join(REGIONS)}")
    now = now or datetime.now(UTC)
    first_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    points = [
        ForecastPoint(start, _intensity(region, start))
        for start in (first_hour + timedelta(hours=i) for i in range(FORECAST_HOURS))
    ]
    return Forecast(region, first_hour, stale=False, data_source=DATA_SOURCE, points=points)


def _intensity(region: str, start: datetime) -> float:
    """Made-up intensity for one hour: base, minus solar, plus evening peak."""
    profile = REGIONS[region]
    local_hour = (start.hour + profile.utc_offset_hours) % 24
    value = profile.base
    if SUNRISE_HOUR <= local_hour <= SUNSET_HOUR:
        daylight = (local_hour - SUNRISE_HOUR) / (SUNSET_HOUR - SUNRISE_HOUR)
        value -= profile.solar_dip * math.sin(math.pi * daylight)
    distance = (local_hour - EVENING_PEAK_HOUR) / EVENING_PEAK_WIDTH_HOURS
    value += profile.evening_peak * math.exp(-(distance**2))
    # Seeded from region + hour so the same hour always gets the same jitter.
    jitter = random.Random(f"{region}-{start.isoformat()}").uniform(-NOISE_FRACTION, NOISE_FRACTION)
    return round(value * (1 + jitter), 1)
