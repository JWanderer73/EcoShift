"""FastAPI app. Run with: uvicorn carbon.api.main:app"""

from __future__ import annotations

import math
import re
from datetime import timedelta

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from carbon import __version__
from carbon.api import service
from carbon.api.errors import ApiError
from carbon.api.schemas import ForecastResponse, HealthResponse, WindowsResponse
from carbon.common.timeutil import HOUR, floor_hour, iso, parse_iso, utcnow
from carbon.common.windows import best_windows
from carbon.config import get_settings

app = FastAPI(title="Carbon windows API", version=__version__)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


def parse_max_wait(text: str) -> int:
    """'3h' -> 3, '1d' -> 24, '90m' -> 2 (rounded up)."""
    m = re.fullmatch(r"(\d+)\s*([mhd])", text.strip().lower())
    if not m:
        raise ApiError(422, "invalid_max_wait", "max_wait must look like 90m, 3h or 1d.")
    amount, unit = int(m.group(1)), m.group(2)
    return math.ceil({"m": amount / 60, "h": amount, "d": amount * 24}[unit])


@app.get("/v1/health", response_model=HealthResponse)
def get_health():
    """Always returns 200 so the load balancer does not cycle tasks when the pipeline is down."""
    return service.health()


@app.get("/v1/forecast", response_model=ForecastResponse)
def get_forecast(location: str | None = None, hours: int = Query(None, ge=1, le=168)):
    view = service.load_view(location)
    hours = hours or get_settings().horizon_hours
    return {
        "location": view.location,
        "generated_at": iso(view.generated_at),
        "model_version": view.version,
        "stale": view.stale,
        "warnings": view.warnings,
        "rows": view.rows[:hours],
    }


@app.get("/v1/windows", response_model=WindowsResponse)
def get_windows(
    duration_hours: int = Query(..., ge=1, le=168),
    location: str | None = None,
    max_wait: str | None = Query(None, description="Longest delay you accept, e.g. 3h or 1d"),
    deadline: str | None = Query(None, description="ISO time the job must finish by"),
    top: int = Query(3, ge=1, le=5),
):
    if max_wait and deadline:
        raise ApiError(422, "conflicting_parameters", "Provide either max_wait or deadline, not both.")
    view = service.load_view(location)
    settings = get_settings()
    values = [r["intensity"] for r in view.rows]
    allowed = len(values) - duration_hours  # latest start offset the forecast can cover
    if allowed < 0:
        raise ApiError(422, "duration_exceeds_horizon", f"The forecast covers {len(values)} hours.")

    warnings = list(view.warnings)
    if max_wait:
        requested = parse_max_wait(max_wait)
    elif deadline:
        try:
            end_by = parse_iso(deadline)
        except ValueError:
            raise ApiError(422, "invalid_deadline", "deadline must be an ISO 8601 time.") from None
        requested = math.floor((end_by - floor_hour(utcnow())) / HOUR) - duration_hours
        if requested < 0:
            raise ApiError(422, "deadline_too_soon", "The job cannot finish by that deadline.")
    else:
        requested = allowed
    max_delay = min(requested, allowed)
    if requested > allowed:
        warnings.append(service.WAIT_CLAMPED)

    start_ts = parse_iso(view.rows[0]["ts"])
    p10 = [r["p10"] for r in view.rows]
    p90 = [r["p90"] for r in view.rows]

    def fmt(w: dict) -> dict:
        s = w["start_offset_h"]
        start = start_ts + s * HOUR
        return {
            "start": iso(start),
            "end": iso(start + duration_hours * HOUR),
            "wait_minutes": s * 60,
            "avg": round(w["avg"], 1),
            "avg_p10": round(sum(p10[s : s + duration_hours]) / duration_hours, 1),
            "avg_p90": round(sum(p90[s : s + duration_hours]) / duration_hours, 1),
            "savings_pct": round(w["savings_pct"], 1),
        }

    windows = [fmt(w) for w in best_windows(values, duration_hours, max_delay, top)]
    savings_by_wait = []
    for wait in settings.wait_options_hours:
        if wait <= allowed:
            w = best_windows(values, duration_hours, wait, 1)[0]
            savings_by_wait.append(
                {"max_wait_hours": wait, "wait_minutes": w["start_offset_h"] * 60, "savings_pct": round(w["savings_pct"], 1)}
            )

    best = windows[0]
    delay = best["wait_minutes"] > 0 and best["savings_pct"] >= settings.min_savings_pct
    return {
        "location": view.location,
        "generated_at": iso(view.generated_at),
        "model_version": view.version,
        "stale": view.stale,
        "request": {"duration_hours": duration_hours, "max_delay_hours": max_delay},
        "run_now_avg": round(sum(values[:duration_hours]) / duration_hours, 1),
        "best": best,
        "alternatives": [w for w in windows[1:] if w["savings_pct"] > 0],
        "savings_by_max_wait": savings_by_wait,
        "recommendation": "delay" if delay else "run_now",
        "warnings": warnings,
    }
