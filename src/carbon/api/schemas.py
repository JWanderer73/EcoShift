"""Response shapes. These are the API contract the dashboard and CLI depend on."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ForecastRow(BaseModel):
    ts: str
    intensity: float
    p10: float
    p90: float


class ForecastResponse(BaseModel):
    location: str
    generated_at: str
    model_version: str
    stale: bool
    warnings: list[str]
    rows: list[ForecastRow]


class Window(BaseModel):
    start: str
    end: str
    wait_minutes: int
    avg: float
    avg_p10: float
    avg_p90: float
    savings_pct: float


class WaitSavings(BaseModel):
    max_wait_hours: int
    wait_minutes: int
    savings_pct: float


class WindowsRequest(BaseModel):
    duration_hours: int
    max_delay_hours: int


class WindowsResponse(BaseModel):
    location: str
    generated_at: str
    model_version: str
    stale: bool
    request: WindowsRequest
    run_now_avg: float
    best: Window
    alternatives: list[Window]
    savings_by_max_wait: list[WaitSavings]
    recommendation: Literal["run_now", "delay"]
    warnings: list[str]


class HealthResponse(BaseModel):
    status: str  # ok | degraded | no_data | store_unavailable
    checked_at: str
    pipeline: dict
    forecast_age_hours: float | None
    warnings: list[str]
    locations: list[str]
