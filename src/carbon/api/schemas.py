"""Response shapes. These are the API contract the dashboard and CLI depend on.

All prices are CAISO $/MWh and can be zero or negative. Dollar amounts are for a constant load of
`kw` kilowatts: price x kWh / 1000.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ForecastRow(BaseModel):
    ts: str
    price: float
    kind: Literal["published", "forecast"] | None = None  # None for synthetic data
    nodes: dict[str, float] | None = None  # price at each of the campus's nearest nodes


class ForecastResponse(BaseModel):
    location: str
    node: str | None
    generated_at: str
    model_version: str
    data_source: str
    unit: str
    stale: bool
    warnings: list[str]
    rows: list[ForecastRow]


class Window(BaseModel):
    start: str
    end: str
    wait_minutes: int
    avg: float  # $/MWh
    cost_usd: float
    savings_usd: float  # versus running now


class WaitSavings(BaseModel):
    max_wait_hours: int
    wait_minutes: int
    savings_usd: float


class WindowsRequest(BaseModel):
    duration_hours: int
    max_delay_hours: int
    kw: float


class WindowsResponse(BaseModel):
    location: str
    node: str | None
    generated_at: str
    model_version: str
    data_source: str
    unit: str
    stale: bool
    request: WindowsRequest
    run_now_avg: float
    run_now_cost_usd: float
    best: Window
    alternatives: list[Window]
    savings_by_max_wait: list[WaitSavings]
    recommendation: Literal["run_now", "delay"]
    warnings: list[str]


class Site(BaseModel):
    location: str
    name: str
    city: str
    street: str
    nodes: list[str]


class SitesResponse(BaseModel):
    sites: list[Site]


class HealthResponse(BaseModel):
    status: str  # ok | degraded | no_data | store_unavailable
    checked_at: str
    pipeline: dict
    forecast_age_hours: float | None
    warnings: list[str]
    locations: list[str]
