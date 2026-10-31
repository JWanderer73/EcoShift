"""Accuracy job (runs hourly): score archived forecasts against actuals that have since arrived.

Publishes a rolling MAE per location. A CloudWatch alarm on `RollingMAE` can start an
extra retrain. Shadow models are scored too, under a `Role=shadow` dimension.
"""

from __future__ import annotations

import logging

from carbon.common import keys
from carbon.common.store import Store, get_store
from carbon.common.timeutil import HOUR, iso, parse_iso, utcnow
from carbon.config import get_settings
from carbon.jobs._util import load_history, run_main

log = logging.getLogger(__name__)
WINDOW_HOURS = 48


def score(store: Store, location: str, version: str, history, now) -> tuple[float, int] | None:
    """MAE over (archived forecast, actual) pairs from the last WINDOW_HOURS hours."""
    cutoff = iso(now - WINDOW_HOURS * HOUR)
    errors: list[float] = []
    for key in store.list_blobs(keys.archive_prefix(location, version)):
        archive = store.get_json(key)
        if archive is None or archive["generated_at"] < cutoff:
            continue
        for row in archive["rows"]:
            i = int((parse_iso(row["ts"]) - history.start) / HOUR)
            if 0 <= i < len(history):  # the actual for this hour has arrived
                errors.append(abs(row["intensity"] - float(history.values[i])))
    return (sum(errors) / len(errors), len(errors)) if errors else None


def run(store: Store | None = None) -> dict:
    store = store or get_store()
    settings = get_settings()
    status = store.get_status()
    now = utcnow()
    summary: dict = {}
    rolling: dict[str, float] = {}
    for location in settings.locations:
        history, _ = load_history(store, location)
        roles = {
            "champion": (status.get("current_model_versions") or {}).get(location),
            "shadow": (status.get("shadow_model_versions") or {}).get(location),
        }
        for role, version in roles.items():
            if not version:
                continue
            result = score(store, location, version, history, now)
            if result is None:
                summary[f"{location}/{role}"] = "no overlap yet"
                continue
            value, n = result
            dims = {"Location": location} if role == "champion" else {"Location": location, "Role": role}
            store.put_metric("RollingMAE", value, dims)
            if role == "champion":
                rolling[location] = value
            summary[f"{location}/{role}"] = {"mae": value, "n": n}
            log.info("accuracy %s/%s: MAE %.2f over %d points", location, role, value, n)
    if rolling:
        store.update_status({"rolling_mae": rolling})
    return summary


if __name__ == "__main__":
    run_main(run)
