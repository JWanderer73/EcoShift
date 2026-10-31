"""Runtime configuration, read from environment variables.

Everything data-specific (locations, history length, horizon, refresh cadence,
model choice) lives here so it can change without touching the code or the
infrastructure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in os.environ.get(name, default).split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    store: str  # "local" or "aws"
    local_dir: str
    forecasts_table: str
    status_table: str
    artifacts_bucket: str
    locations: tuple[str, ...]
    default_location: str
    horizon_hours: int
    history_days: int
    stale_after_hours: float
    min_savings_pct: float
    promotion_tolerance: float
    model: str
    cache_ttl_seconds: int
    degraded_fraction: float
    wait_options_hours: tuple[int, ...]


def get_settings() -> Settings:
    env = os.environ.get
    locations = _csv("CARBON_LOCATIONS", "demo-region")
    return Settings(
        store=env("CARBON_STORE", "local"),
        local_dir=env("CARBON_LOCAL_DIR", ".local"),
        forecasts_table=env("CARBON_FORECASTS_TABLE", "carbon-windows-forecasts"),
        status_table=env("CARBON_STATUS_TABLE", "carbon-windows-status"),
        artifacts_bucket=env("CARBON_ARTIFACTS_BUCKET", ""),
        locations=locations,
        default_location=env("CARBON_DEFAULT_LOCATION", locations[0]),
        horizon_hours=int(env("CARBON_HORIZON_HOURS", "48")),
        history_days=int(env("CARBON_HISTORY_DAYS", "28")),
        stale_after_hours=float(env("CARBON_STALE_AFTER_HOURS", "6")),
        min_savings_pct=float(env("CARBON_MIN_SAVINGS_PCT", "5")),
        promotion_tolerance=float(env("CARBON_PROMOTION_TOLERANCE", "0.0")),
        model=env("CARBON_MODEL", "baseline"),
        cache_ttl_seconds=int(env("CARBON_CACHE_TTL", "120")),
        degraded_fraction=float(env("CARBON_DEGRADED_FRACTION", "0.1")),
        wait_options_hours=tuple(int(x) for x in _csv("CARBON_WAIT_OPTIONS", "3,12,24")),
    )
