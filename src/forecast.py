"""Synthetic carbon-intensity and power-price forecasts.

The real forecasts will come from the ML pipeline through the API. Until that
exists, this module makes up a believable 48-hour forecast so the CLI and the
dashboard have something to run against. Every number in here is made up.

Forecasts come in two kinds. A balancing authority (``REGIONS``, e.g. CISO) has
carbon intensity only. A data-center site (``SITES``, e.g. coresite-sv7) takes
its intensity from its balancing authority and adds the wholesale power price
at its nearest pricing node, since prices differ by location within one grid.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

FORECAST_HOURS = 48
DATA_SOURCE = "synthetic"
NOISE_FRACTION = 0.03  # ±3% jitter so the curve isn't perfectly smooth
PRICE_NOISE_FRACTION = 0.06  # prices are jumpier than intensity
MIN_PRICE = -30.0  # oversupplied solar hours go negative, but not without limit
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


# Rough, made-up shapes for EIA balancing authorities: California has a deep
# solar dip, Sacramento (BANC) leans on hydro, Los Angeles (LDWP) on gas, and
# Texas and PJM more on gas and coal.
REGIONS: dict[str, RegionProfile] = {
    "CISO": RegionProfile(base=260, solar_dip=140, evening_peak=60, utc_offset_hours=-8),
    "BANC": RegionProfile(base=200, solar_dip=60, evening_peak=45, utc_offset_hours=-8),
    "LDWP": RegionProfile(base=360, solar_dip=120, evening_peak=50, utc_offset_hours=-8),
    "ERCO": RegionProfile(base=400, solar_dip=80, evening_peak=50, utc_offset_hours=-6),
    "PJM": RegionProfile(base=380, solar_dip=40, evening_peak=40, utc_offset_hours=-5),
}


@dataclass(frozen=True)
class PriceProfile:
    """Made-up shape of one pricing node's daily wholesale price, in USD/MWh.

    Attributes:
        base: Overnight price.
        solar_dip: How far price drops at solar noon.
        evening_peak: How far price rises at the evening peak.
    """

    base: float
    solar_dip: float
    evening_peak: float


@dataclass(frozen=True)
class Site:
    """A data center: its grid for carbon, and its nearest pricing node for cost.

    Attributes:
        balancing_authority: Key into ``REGIONS``; sets the carbon intensity.
        price: Shape of the site's wholesale price.
    """

    balancing_authority: str
    price: PriceProfile


# Specific California data centers (same codes as frontend/lib/regions.ts).
# The CAISO sites share CISO's carbon but price at different nodes: Bay Area
# nodes sit near NP15, El Segundo near SP15, San Diego at SDG&E's higher,
# more congested prices. NTT CA1 (SMUD) and CoreSite LA1 (LADWP) are in their
# own balancing authorities.
SITES: dict[str, Site] = {
    "coresite-sv7": Site("CISO", PriceProfile(base=56, solar_dip=40, evening_peak=62)),
    "equinix-sv1": Site("CISO", PriceProfile(base=55, solar_dip=42, evening_peak=58)),
    "he-fremont2": Site("CISO", PriceProfile(base=54, solar_dip=40, evening_peak=60)),
    "equinix-la4": Site("CISO", PriceProfile(base=50, solar_dip=55, evening_peak=65)),
    "databank-san2": Site("CISO", PriceProfile(base=62, solar_dip=50, evening_peak=80)),
    "ntt-ca1": Site("BANC", PriceProfile(base=48, solar_dip=30, evening_peak=55)),
    "coresite-la1": Site("LDWP", PriceProfile(base=52, solar_dip=45, evening_peak=60)),
}


@dataclass(frozen=True)
class ForecastPoint:
    """Forecast for the hour [start, start + 1h).

    Attributes:
        start: Start of the hour, UTC.
        intensity: Grid carbon intensity in gCO2/kWh.
        price: Wholesale power price in USD/MWh, or ``None`` for a balancing
            authority, which has no single price.
    """

    start: datetime
    intensity: float
    price: float | None = None


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
        region: An EIA balancing-authority code from ``REGIONS``, or a site
            from ``SITES``. Sites also get a price for every hour.
        now: Current time, timezone-aware. Defaults to the real current time.

    Returns:
        A forecast whose first point starts at the top of ``now``'s hour.

    Raises:
        ValueError: If ``region`` isn't in ``REGIONS`` or ``SITES``.
    """
    site = SITES.get(region)
    if site is None and region not in REGIONS:
        choices = ", ".join([*REGIONS, *SITES])
        raise ValueError(f"unknown region {region!r}; choose one of {choices}")
    grid = site.balancing_authority if site else region
    now = now or datetime.now(UTC)
    first_hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    points = [
        ForecastPoint(start, _intensity(grid, start), _price(region, site, start) if site else None)
        for start in (first_hour + timedelta(hours=i) for i in range(FORECAST_HOURS))
    ]
    return Forecast(region, first_hour, stale=False, data_source=DATA_SOURCE, points=points)


def _daily_shape(base: float, solar_dip: float, evening_peak: float, local_hour: int) -> float:
    """Base, minus a midday solar dip, plus an evening demand peak."""
    value = base
    if SUNRISE_HOUR <= local_hour <= SUNSET_HOUR:
        daylight = (local_hour - SUNRISE_HOUR) / (SUNSET_HOUR - SUNRISE_HOUR)
        value -= solar_dip * math.sin(math.pi * daylight)
    distance = (local_hour - EVENING_PEAK_HOUR) / EVENING_PEAK_WIDTH_HOURS
    return value + evening_peak * math.exp(-(distance**2))


def _intensity(region: str, start: datetime) -> float:
    """Made-up intensity for one hour of a balancing authority."""
    profile = REGIONS[region]
    local_hour = (start.hour + profile.utc_offset_hours) % 24
    value = _daily_shape(profile.base, profile.solar_dip, profile.evening_peak, local_hour)
    # Seeded from region + hour so the same hour always gets the same jitter.
    jitter = random.Random(f"{region}-{start.isoformat()}").uniform(-NOISE_FRACTION, NOISE_FRACTION)
    return round(value * (1 + jitter), 1)


def _price(name: str, site: Site, start: datetime) -> float:
    """Made-up wholesale price for one hour at a site, in USD/MWh."""
    local_hour = (start.hour + REGIONS[site.balancing_authority].utc_offset_hours) % 24
    p = site.price
    value = _daily_shape(p.base, p.solar_dip, p.evening_peak, local_hour)
    noise = random.Random(f"{name}-price-{start.isoformat()}").uniform(-1, 1)
    jitter = noise * PRICE_NOISE_FRACTION * p.base
    return round(max(MIN_PRICE, value + jitter), 2)
