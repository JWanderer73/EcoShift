"""Turn the model's output into the rows the API serves.

Two kinds of row, marked in `kind`:
  published  an hour CAISO has already published a day-ahead price for. Served as is.
  forecast   an hour after the last published one, predicted by the model (up to 72 hours on).

Each row has `price` ($/MWh, the nearest node that has one) and `nodes`, the price at each of the
campus's five nearest nodes. Prices are not clipped: a negative price is a real hour.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pandas as pd

from carbon.common.timeutil import floor_hour, iso
from carbon.price import sites
from carbon.price.bridge import load as load_model_code

log = logging.getLogger(__name__)

# A node counts toward "the last published hour" once this share of nodes has a price for it.
ANCHOR_COVERAGE = 0.9
LAST_WEEK = 168


def prices_frame(table: dict) -> pd.DataFrame:
    """The stored price table as an hourly UTC DataFrame, one column per node."""
    start = pd.Timestamp(table["start"]).tz_convert("UTC")
    nodes = table["nodes"]
    n = max((len(v) for v in nodes.values()), default=0)
    index = pd.date_range(start, periods=n, freq="h", tz="UTC")
    return pd.DataFrame({k: pd.Series(v, dtype=float).reindex(range(n)).to_numpy() for k, v in nodes.items()}, index=index)


def anchor_hour(prices: pd.DataFrame) -> pd.Timestamp:
    """The last hour with a published price at (nearly) every node."""
    covered = prices.notna().mean(axis=1) >= ANCHOR_COVERAGE
    if not covered.any():
        raise ValueError("no hour has prices at enough nodes")
    return covered[covered].index.max()


def _node_object(node: dict) -> SimpleNamespace:
    return SimpleNamespace(
        node_type=node["node_type"], latitude=node["latitude"], longitude=node["longitude"], distance_km=node["distance_km"]
    )


def _rows(campus_nodes: list[dict], series: dict[str, pd.Series], published: pd.DataFrame, hours: pd.DatetimeIndex, anchor) -> list[dict]:
    """One row per hour; `published` supplies hours up to the anchor, `series` the forecast hours after it."""
    order = [n["pnode_id"] for n in campus_nodes]
    rows = []
    for ts in hours:
        known = ts <= anchor
        values: dict[str, float] = {}
        for node in order:
            if known:
                value = published[node].get(ts, np.nan) if node in published.columns else np.nan
            else:
                value = series[node].get(ts, np.nan) if node in series else np.nan
            if np.isfinite(value):
                values[node] = round(float(value), 2)
        if not values:
            continue
        first = next(n for n in order if n in values)
        rows.append({"ts": iso(ts.to_pydatetime()), "price": values[first], "nodes": values, "kind": "published" if known else "forecast"})
    return rows


def forecast_campuses(
    saved: dict | None,
    prices: pd.DataFrame,
    now,
    *,
    fetch_weather: Callable | None = None,
    fetch_load: Callable | None = None,
    campus_filter: list[str] | None = None,
) -> tuple[dict[str, list[dict]], dict]:
    """Forecast every campus. `saved` is the model bundle, or None for the last-week baseline.

    Returns ({campus_id: rows}, info). A campus whose weather cannot be fetched, or whose nodes
    all lack a price, is left out and counted in `info["skipped"]`.
    """
    code = load_model_code()
    anchor = anchor_hour(prices)
    horizon = pd.date_range(anchor + pd.Timedelta(hours=1), periods=code.HORIZON_HOURS, freq="h", tz="UTC")
    first = max(floor_hour(now), prices.index.min().to_pydatetime())
    shown = pd.date_range(pd.Timestamp(first).tz_convert("UTC"), anchor, freq="h", tz="UTC").append(horizon)

    features = list(saved["features"]) if saved else []
    if saved:
        leaked = code.illegal_feature_names(features)
        if leaked:
            raise ValueError(f"model features are not legal three days ahead: {leaked}")
    needs_weather = any(f in code.WEATHER_FEATURES for f in features)
    needs_load = code.LOAD_FEATURE in features
    weather_fn = fetch_weather or code.fetch_weather
    load_fn = fetch_load or code.fetch_load
    load_series = None
    if needs_load:
        try:
            load_series = load_fn(horizon)
        except Exception as exc:  # noqa: BLE001 - the model tolerates a missing load forecast
            log.warning("load forecast unavailable (%s); continuing without it", exc)
            load_series = pd.Series(dtype=float)
    weather_cols = [f for f in features if f in code.WEATHER_FEATURES]

    out: dict[str, list[dict]] = {}
    skipped: dict[str, str] = {}
    for campus_id, campus_nodes in sites.candidates().items():
        if campus_filter is not None and campus_id not in campus_filter:
            continue
        usable = [n for n in campus_nodes if n["pnode_id"] in prices.columns and prices[n["pnode_id"]].notna().any()]
        if not usable:
            skipped[campus_id] = "no node has prices"
            continue
        series: dict[str, pd.Series] = {}
        if saved is None:
            for node in usable:
                p = prices[node["pnode_id"]].dropna()
                full = p.reindex(pd.date_range(p.index.min(), horizon.max(), freq="h", tz="UTC"))
                series[node["pnode_id"]] = full.shift(LAST_WEEK).reindex(horizon)
        else:
            weather = None
            if needs_weather:
                campus = sites.campuses()[campus_id]
                try:
                    weather = weather_fn(campus["latitude"], campus["longitude"], horizon, weather_cols)
                except Exception as exc:  # noqa: BLE001 - one bad pull must not stop the other campuses
                    skipped[campus_id] = f"weather: {exc}"
                    continue
            for node in usable:
                node_prices = prices[node["pnode_id"]].dropna()
                frame = code.feature_frame(horizon, node_prices, code.static_features(_node_object(node)), weather, load_series, features)
                predicted = np.array(code.predict_price(saved, frame), dtype=float)  # a copy: pandas 3 hands back read-only arrays
                required = [f for f in features if f not in {code.LOAD_FEATURE, code.GAS_FEATURE}]
                predicted[frame.loc[:, required].isna().any(axis=1).to_numpy()] = np.nan
                series[node["pnode_id"]] = pd.Series(predicted, index=horizon)
        rows = _rows(usable, series, prices, shown, anchor)
        if not any(r["kind"] == "forecast" for r in rows):
            skipped[campus_id] = "no forecast hours"
            continue
        out[campus_id] = rows
    return out, {"anchor": iso(anchor.to_pydatetime()), "skipped": skipped, "campuses": len(out)}
