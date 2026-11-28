"""FastAPI app. Run with: uvicorn carbon.api.main:app"""

from __future__ import annotations

import math
import re

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from carbon import __version__
from carbon.api import service
from carbon.api.errors import ApiError
from carbon.api.schemas import ForecastResponse, HealthResponse, SitesResponse, WindowsResponse
from carbon.common.timeutil import HOUR, iso, parse_iso
from carbon.common.windows import best_windows, job_dollars
from carbon.config import get_settings

app = FastAPI(title="Electricity price windows API", version=__version__)

UNIT = "usd_per_mwh"


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


@app.get("/v1/sites", response_model=SitesResponse)
def get_sites():
    """Places that can be forecast. For the price model these are datacenter campuses."""
    return {"sites": service.list_sites()}


@app.get("/v1/forecast", response_model=ForecastResponse, response_model_exclude_none=True)
def get_forecast(location: str | None = None, node: str | None = None, hours: int = Query(None, ge=1, le=240)):
    view = service.load_view(location, node)
    return {
        "location": view.location,
        "node": view.node,
        "generated_at": iso(view.generated_at),
        "model_version": view.version,
        "data_source": view.data_source,
        "unit": UNIT,
        "stale": view.stale,
        "warnings": view.warnings,
        "rows": view.rows[:hours] if hours else view.rows,
    }


@app.get("/v1/windows", response_model=WindowsResponse)
def get_windows(
    duration_hours: int = Query(..., ge=1, le=168),
    location: str | None = None,
    node: str | None = None,
    kw: float | None = Query(None, gt=0, le=100000, description="Constant load in kW (default 8)"),
    max_wait: str | None = Query(None, description="Longest delay you accept, e.g. 3h or 1d"),
    deadline: str | None = Query(None, description="ISO time the job must finish by"),
    top: int = Query(3, ge=1, le=5),
):
    if max_wait and deadline:
        raise ApiError(422, "conflicting_parameters", "Provide either max_wait or deadline, not both.")
    if location == "any":
        if node is not None:
            raise ApiError(422, "conflicting_parameters", "A node requires a specific location.")
        candidates = []
        for view in service.load_fresh_site_views():
            try:
                candidates.append(_rank_windows(view, duration_hours, kw, max_wait, deadline, top))
            except ApiError as error:
                if error.code not in {"duration_exceeds_horizon", "deadline_too_soon"}:
                    raise
        if not candidates:
            raise ApiError(503, "no_eligible_forecast", "No location has a fresh forecast with a window that fits.")
        return min(candidates, key=lambda item: (item["best"]["cost_usd"], item["best"]["avg"],
                                                 item["best"]["start"], item["location"]))
    return _rank_windows(service.load_view(location, node), duration_hours, kw, max_wait, deadline, top)


def _rank_windows(
    view: service.View,
    duration_hours: int,
    kw: float | None,
    max_wait: str | None,
    deadline: str | None,
    top: int,
) -> dict:
    settings = get_settings()
    kw = kw or settings.kw
    values = [r["price"] for r in view.rows]
    allowed = len(values) - duration_hours  # latest start offset the forecast can cover
    if allowed < 0:
        raise ApiError(422, "duration_exceeds_horizon", f"The forecast covers {len(values)} hours.")

    warnings = list(view.warnings)
    start_ts = parse_iso(view.rows[0]["ts"])
    if max_wait:
        requested = parse_max_wait(max_wait)
    elif deadline:
        try:
            end_by = parse_iso(deadline)
        except ValueError:
            raise ApiError(422, "invalid_deadline", "deadline must be an ISO 8601 time.") from None
        requested = math.floor((end_by - start_ts) / HOUR) - duration_hours
        if requested < 0:
            raise ApiError(422, "deadline_too_soon", "The job cannot finish by that deadline.")
    else:
        requested = allowed
    max_delay = min(requested, allowed)
    if requested > allowed:
        warnings.append(service.WAIT_CLAMPED)

    def dollars(avg: float) -> float:
        return round(job_dollars(avg, kw, duration_hours), 4)

    def fmt(w: dict) -> dict:
        s = w["start_offset_h"]
        start = start_ts + s * HOUR
        return {
            "start": iso(start),
            "end": iso(start + duration_hours * HOUR),
            "wait_minutes": s * 60,
            "avg": round(w["avg"], 2),
            "cost_usd": dollars(w["avg"]),
            "savings_usd": round(job_dollars(w["savings"], kw, duration_hours), 4),
        }

    windows = [fmt(w) for w in best_windows(values, duration_hours, max_delay, top)]
    run_now_avg = sum(values[:duration_hours]) / duration_hours
    savings_by_wait = []
    for wait in settings.wait_options_hours:
        if wait <= allowed:
            w = best_windows(values, duration_hours, wait, 1)[0]
            savings_by_wait.append(
                {
                    "max_wait_hours": wait,
                    "wait_minutes": w["start_offset_h"] * 60,
                    "savings_usd": round(job_dollars(w["savings"], kw, duration_hours), 4),
                }
            )

    best = windows[0]
    saved_per_mwh = run_now_avg - best["avg"]
    delay = best["wait_minutes"] > 0 and saved_per_mwh >= settings.min_savings_usd_per_mwh
    return {
        "location": view.location,
        "node": view.node,
        "generated_at": iso(view.generated_at),
        "model_version": view.version,
        "data_source": view.data_source,
        "unit": UNIT,
        "stale": view.stale,
        "request": {"duration_hours": duration_hours, "max_delay_hours": max_delay, "kw": kw},
        "run_now_avg": round(run_now_avg, 2),
        "run_now_cost_usd": dollars(run_now_avg),
        "best": best,
        "alternatives": [w for w in windows[1:] if w["savings_usd"] > 0],
        "savings_by_max_wait": savings_by_wait,
        "recommendation": "delay" if delay else "run_now",
        "warnings": warnings,
    }
