"""The price model's pipeline steps. `carbon.jobs.*` call these when CARBON_MODEL=price_xgb."""

from __future__ import annotations

import hashlib
import io
import json
import logging
from typing import Callable

import numpy as np
import pandas as pd

from carbon.common import keys
from carbon.common.store import Store
from carbon.common.timeutil import iso, parse_iso, utcnow
from carbon.common.validate import ValidationError, validate_series
from carbon.config import get_settings
from carbon.price import sites
from carbon.price.bridge import load as load_model_code
from carbon.price.forecast import forecast_campuses, prices_frame

log = logging.getLogger(__name__)

DATA_SOURCE = "caiso-day-ahead"
KEEP_DAYS = 21  # lags reach back 14 days; keep a margin
FIRST_PULL_DAYS = 21
# CAISO's energy bid limits are far inside these. They only catch broken numbers, and the floor is
# below zero because negative prices are real.
MIN_PRICE, MAX_PRICE = -1000.0, 5000.0
MAX_GAP_HOURS = 3


# --- upload (run by a person, once per trained model) -------------------------------------------


def register_model(store: Store, model_blob: bytes, metrics: dict | None = None) -> str:
    """Store a trained model file and make it the candidate. Returns its version id."""
    version = f"price_xgb-{hashlib.sha256(model_blob).hexdigest()[:8]}"
    store.put_blob(keys.price_model(version), model_blob)
    meta = {"version": version, "uploaded_at": iso(utcnow()), **(metrics or {})}
    store.put_json(keys.price_metrics(version), meta)
    store.put_json(keys.PRICE_CANDIDATE, {"version": version, "model": "price_xgb"})
    return version


def _test_mae(metrics: dict | None) -> float | None:
    try:
        return float(metrics["test"]["mae_usd_per_mwh"])  # shape of price_windows/metrics.json
    except (TypeError, KeyError, ValueError):
        return None


# --- ingest -------------------------------------------------------------------------------------


def _series_to_hours(frame: pd.DataFrame, target: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    s = frame.drop_duplicates("timestamp", keep="last").set_index("timestamp")[target]
    s.index = pd.to_datetime(s.index, utc=True)
    return pd.to_numeric(s, errors="coerce").sort_index()


def ingest(store: Store, fetch_lmp: Callable | None = None, nodes: list[str] | None = None) -> dict:
    """Refresh the day-ahead price table: every node, a few weeks back through tomorrow.

    Only days not already stored are requested. A node with a long gap or broken values is left
    out; too many left out stops the run so the previous table stays in use.
    """
    settings = get_settings()
    code = load_model_code()
    fetch = fetch_lmp or code.fetch_lmp
    now = utcnow()
    today = pd.Timestamp(now).tz_convert("UTC").floor("D")
    stop = today + pd.Timedelta(days=2)  # exclusive: through the end of tomorrow, when CAISO has published it

    existing = store.get_json(keys.PRICE_TABLE)
    old = prices_frame(existing) if existing else pd.DataFrame()
    all_nodes = nodes or sites.all_nodes()
    if old.empty:
        begin = today - pd.Timedelta(days=FIRST_PULL_DAYS)
    else:
        begin = max(old.index.max().floor("D") - pd.Timedelta(days=1), today - pd.Timedelta(days=KEEP_DAYS))

    fresh: dict[str, pd.Series] = {}
    for i, node in enumerate(all_nodes, 1):
        try:
            fresh[node] = _series_to_hours(fetch(node, begin, stop), code.TARGET)
        except Exception as exc:  # noqa: BLE001 - one node's failure is handled below
            log.warning("ingest: %s failed (%s)", node, exc)
            fresh[node] = pd.Series(dtype=float)
        if i % 25 == 0:
            log.info("ingest: %d/%d nodes", i, len(all_nodes))

    index = pd.date_range(today - pd.Timedelta(days=KEEP_DAYS), stop - pd.Timedelta(hours=1), freq="h", tz="UTC")
    merged: dict[str, list] = {}
    dropped: dict[str, str] = {}
    imputed_total = n_total = 0
    for node in all_nodes:
        s = fresh[node]
        if node in old.columns:
            s = pd.concat([old[node].dropna(), s]).groupby(level=0).last()  # newer pulls win
        s = s.reindex(index)
        if not s.notna().any():
            dropped[node] = "no prices"
            continue
        inner = s.loc[s.first_valid_index() : s.last_valid_index()]
        try:
            clean, imputed = validate_series(inner.to_numpy(), MIN_PRICE, MAX_PRICE, MAX_GAP_HOURS)
        except ValidationError as exc:
            dropped[node] = str(exc)
            continue
        s.loc[inner.index] = clean
        imputed_total += round(imputed * len(inner))
        n_total += len(inner)
        merged[node] = [None if np.isnan(v) else round(float(v), 2) for v in s.to_numpy()]
    if not merged or len(dropped) / len(all_nodes) > settings.degraded_fraction:
        raise ValidationError(f"{len(dropped)} of {len(all_nodes)} nodes failed validation; keeping the previous price table")

    imputed_fraction = imputed_total / n_total if n_total else 0.0
    store.put_json(
        keys.PRICE_TABLE,
        {"start": iso(index[0].to_pydatetime()), "nodes": merged, "updated_at": iso(now), "imputed_fraction": imputed_fraction, "dropped": dropped},
    )
    log.info("ingest: %d nodes kept, %d dropped", len(merged), len(dropped))
    return {"nodes": len(merged), "dropped": len(dropped), "imputed_fraction": imputed_fraction, "through": iso(index[-1].to_pydatetime())}


# --- train (offline) and gate --------------------------------------------------------------------


def check_trained_model(store: Store) -> dict:
    """The model is trained offline. This step only confirms an uploaded candidate exists."""
    candidate = store.get_json(keys.PRICE_CANDIDATE)
    if candidate is None or store.get_blob(keys.price_model(candidate["version"])) is None:
        raise RuntimeError("No trained price model. Upload one: python -m carbon.price.upload_model PATH_TO_model.joblib")
    return {"version": candidate["version"], "trained": "offline"}


def gate(store: Store) -> dict:
    """Promote the candidate unless its recorded test MAE is worse than the champion's."""
    from carbon.jobs.gate import should_promote

    settings = get_settings()
    candidate = store.get_json(keys.PRICE_CANDIDATE)
    if candidate is None:
        raise RuntimeError("No candidate price model. Run the train step first.")
    metrics = store.get_json(keys.price_metrics(candidate["version"]))
    champion = store.get_json(keys.PRICE_CHAMPION)
    cand_mae = _test_mae(metrics)
    if champion is None:
        promote, reason = True, "no champion yet"
    elif champion["version"] == candidate["version"]:
        promote, reason = False, "already the champion"
    elif cand_mae is None or champion.get("mae_usd_per_mwh") is None:
        promote, reason = False, "no recorded test MAE to compare; promote by hand"
    else:
        promote = should_promote(cand_mae, float(champion["mae_usd_per_mwh"]), settings.promotion_tolerance)
        reason = f"candidate MAE {cand_mae:.2f} vs champion {champion['mae_usd_per_mwh']:.2f}"
    if promote:
        store.put_json(
            keys.PRICE_CHAMPION,
            {"version": candidate["version"], "model": "price_xgb", "promoted_at": iso(utcnow()), "mae_usd_per_mwh": cand_mae},
        )
    return {"promoted": promote, "version": candidate["version"], "reason": reason}


# --- predict -------------------------------------------------------------------------------------


def _load_bundle(store: Store, version: str) -> dict:
    import joblib

    blob = store.get_blob(keys.price_model(version))
    if blob is None:
        raise LookupError(f"model file for {version} is missing")
    return joblib.load(io.BytesIO(blob))


def predict(store: Store, **injected) -> dict:
    """Write a forecast for every campus, or the last-week baseline if the model cannot be loaded."""
    now = utcnow()
    generated_at = iso(now)
    table = store.get_json(keys.PRICE_TABLE)
    if table is None:
        raise RuntimeError("No price table. Run the ingest step first.")
    prices = prices_frame(table)

    fallback = False
    try:
        champion = store.get_json(keys.PRICE_CHAMPION)
        if champion is None:
            raise LookupError("no champion model")
        saved, version = _load_bundle(store, champion["version"]), champion["version"]
    except Exception as exc:  # noqa: BLE001 - any load failure means fall back
        log.warning("predict: falling back to the last-week baseline (%s)", exc)
        saved, version, fallback = None, f"baseline-lastweek-{now:%Y%m%dT%H%M%S}", True

    forecasts, info = forecast_campuses(saved, prices, now, **injected)
    if not forecasts:
        raise RuntimeError(f"no campus could be forecast: {info['skipped']}")
    for campus, rows in forecasts.items():
        store.put_forecast(campus, version, generated_at, rows)
        store.put_json(keys.archive(campus, version, generated_at), {"generated_at": generated_at, "version": version, "rows": rows})
    store.update_status(
        {
            "last_success_at": generated_at,
            "last_run_status": "success",
            "last_error": None,
            "current_model_versions": {campus: version for campus in forecasts},
            "shadow_model_versions": {},
            "fallback": fallback,
            "imputed_fraction": float(table.get("imputed_fraction") or 0.0),
            "data_source": DATA_SOURCE,
            "prices_through": info["anchor"],
            "campuses_skipped": info["skipped"],
            "updated_at": generated_at,
        }
    )
    log.info("predict: %d campuses (fallback=%s, skipped=%d)", len(forecasts), fallback, len(info["skipped"]))
    return {"generated_at": generated_at, "version": version, "campuses": len(forecasts), "skipped": len(info["skipped"]), "fallback": fallback}


# --- accuracy ------------------------------------------------------------------------------------

WINDOW_HOURS = 72


def accuracy(store: Store) -> dict:
    """Score archived forecast hours against the day-ahead prices that have since been published.

    Published rows are skipped, and one `RollingMAE` is sent for the whole fleet (a metric per
    campus would add cost).
    """
    now = utcnow()
    table = store.get_json(keys.PRICE_TABLE)
    status = store.get_status()
    if table is None:
        return {"all": "no price table yet"}
    prices = prices_frame(table)
    cutoff = iso(now - pd.Timedelta(hours=WINDOW_HOURS))
    errors: list[float] = []
    for campus, version in (status.get("current_model_versions") or {}).items():
        first_node = sites.candidates()[campus][0]["pnode_id"] if campus in sites.candidates() else None
        for key in store.list_blobs(keys.archive_prefix(campus, version)):
            archive = store.get_json(key)
            if archive is None or archive["generated_at"] < cutoff:
                continue
            for row in archive["rows"]:
                if row.get("kind") != "forecast":
                    continue
                node = first_node if first_node in row.get("nodes", {}) else next(iter(row.get("nodes", {})), None)
                ts = pd.Timestamp(parse_iso(row["ts"]))
                if node in prices.columns and ts in prices.index and np.isfinite(prices.at[ts, node]):
                    errors.append(abs(row["nodes"][node] - float(prices.at[ts, node])))
    if not errors:
        return {"all": "no overlap yet"}
    value = float(np.mean(errors))
    store.put_metric("RollingMAE", value, {"Location": "all"})
    store.update_status({"rolling_mae": {"all": value}})
    return {"all": {"mae_usd_per_mwh": value, "n": len(errors)}}
