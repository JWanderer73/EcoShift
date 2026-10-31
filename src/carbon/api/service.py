"""Reads precomputed forecasts and works out warnings. No ML runs here."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from carbon.api.errors import ApiError
from carbon.common.store import Store, get_store
from carbon.common.timeutil import floor_hour, iso, parse_iso, utcnow
from carbon.config import Settings, get_settings

# Warning codes returned in every response's `warnings` list.
PIPELINE_FAILED = "pipeline_failed"  # the last pipeline run failed
FORECAST_STALE = "forecast_stale"  # forecast is older than CARBON_STALE_AFTER_HOURS
MODEL_FALLBACK = "model_fallback"  # serving the baseline because the champion could not be loaded
DATA_QUALITY_DEGRADED = "data_quality_degraded"  # many hours were imputed
WAIT_CLAMPED = "wait_clamped_to_horizon"  # requested wait is longer than the forecast covers

_cache: dict[tuple[str, str], tuple[float, dict]] = {}


@dataclass
class View:
    location: str
    version: str
    generated_at: datetime
    rows: list[dict]  # from the current hour onward
    warnings: list[str]

    @property
    def stale(self) -> bool:
        return FORECAST_STALE in self.warnings


def compute_warnings(status: dict, generated_at: datetime, now: datetime, settings: Settings) -> list[str]:
    warnings: list[str] = []
    if status.get("last_run_status") == "failed":
        warnings.append(PIPELINE_FAILED)
    if (now - generated_at).total_seconds() / 3600 > settings.stale_after_hours:
        warnings.append(FORECAST_STALE)
    if status.get("fallback"):
        warnings.append(MODEL_FALLBACK)
    if float(status.get("imputed_fraction") or 0) > settings.degraded_fraction:
        warnings.append(DATA_QUALITY_DEGRADED)
    return warnings


def _read_forecast(store: Store, location: str, version: str, ttl: int) -> dict | None:
    key = (location, version)
    hit = _cache.get(key)
    if ttl > 0 and hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    forecast = store.get_forecast(location, version)
    if forecast and ttl > 0:
        _cache[key] = (time.monotonic(), forecast)
    return forecast


def load_view(location: str | None) -> View:
    settings = get_settings()
    location = location or settings.default_location
    if location not in settings.locations:
        raise ApiError(
            404, "unsupported_location", f"'{location}' is not available. Available: {', '.join(settings.locations)}"
        )
    store = get_store()
    status = store.get_status()
    version = (status.get("current_model_versions") or {}).get(location)
    forecast = _read_forecast(store, location, version, settings.cache_ttl_seconds) if version else None
    if forecast is None:
        raise ApiError(503, "no_forecast", "No forecast has been generated yet for this location.")

    now = utcnow()
    generated_at = parse_iso(forecast["generated_at"])
    rows = [r for r in forecast["rows"] if r["ts"] >= iso(floor_hour(now))]
    if not rows:
        raise ApiError(503, "forecast_expired", "The latest forecast has no hours left; the pipeline is not running.")
    return View(location, version, generated_at, rows, compute_warnings(status, generated_at, now, settings))


def health() -> dict:
    settings = get_settings()
    now = utcnow()
    try:
        status = get_store().get_status()
    except Exception:  # noqa: BLE001 - keep the ALB health check green during store outages
        return {
            "status": "store_unavailable",
            "checked_at": iso(now),
            "pipeline": {},
            "forecast_age_hours": None,
            "warnings": [],
            "locations": list(settings.locations),
        }
    if not status.get("last_success_at"):
        state, age, warnings = "no_data", None, [PIPELINE_FAILED] if status.get("last_run_status") == "failed" else []
    else:
        generated = parse_iso(status["last_success_at"])
        age = round((now - generated).total_seconds() / 3600, 2)
        warnings = compute_warnings(status, generated, now, settings)
        state = "degraded" if warnings else "ok"
    return {
        "status": state,
        "checked_at": iso(now),
        "pipeline": status,
        "forecast_age_hours": age,
        "warnings": warnings,
        "locations": list(settings.locations),
    }
