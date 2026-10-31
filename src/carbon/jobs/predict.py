"""Step 4: write forecasts for the champion model and record pipeline success.

If the champion cannot be loaded, fall back to the baseline and flag it so the
API can return a `model_fallback` warning. With CARBON_SHADOW=1 the newest
candidate is also forecast under its own version tag (never served).
"""

from __future__ import annotations

import logging
import os

import numpy as np

from carbon.common import keys
from carbon.common.store import Store, get_store
from carbon.common.timeutil import HOUR, iso, utcnow
from carbon.config import get_settings
from carbon.jobs._util import load_history, maybe_fail, run_main
from carbon.model import History, Model, load_model
from carbon.model.models import SeasonalNaive

log = logging.getLogger(__name__)


def _write(store: Store, location: str, version: str, model: Model, history: History, horizon: int, generated_at: str):
    fc = model.predict(history, horizon)
    rows = [
        {
            "ts": iso(history.end + k * HOUR),
            "intensity": round(float(max(fc.p50[k], 0.0)), 2),
            "p10": round(float(max(fc.p10[k], 0.0)), 2),
            "p90": round(float(max(fc.p90[k], 0.0)), 2),
        }
        for k in range(horizon)
    ]
    store.put_forecast(location, version, generated_at, rows)
    store.put_json(
        keys.archive(location, version, generated_at),
        {"generated_at": generated_at, "version": version, "rows": rows},
    )


def run(store: Store | None = None) -> dict:
    maybe_fail("predict")
    store = store or get_store()
    settings = get_settings()
    now = utcnow()
    generated_at = iso(now)
    horizon = settings.horizon_hours
    versions: dict[str, str] = {}
    shadow: dict[str, str] = {}
    fallback = False
    imputed = 0.0

    for location in settings.locations:
        history, table = load_history(store, location)
        imputed = max(imputed, float(table.get("imputed_fraction", 0.0)))
        try:
            champion = store.get_json(keys.champion(location))
            if champion is None:
                raise LookupError("no champion model")
            model = load_model(store.get_json(keys.model(location, champion["version"])))
            version = champion["version"]
        except Exception as exc:  # noqa: BLE001 - any load failure means fall back
            log.warning("predict %s: falling back to baseline (%s)", location, exc)
            model = SeasonalNaive.fit(history)
            version = f"baseline-fallback-{now:%Y%m%dT%H%M%S}"
            fallback = True
        _write(store, location, version, model, history, horizon, generated_at)
        versions[location] = version

        if os.environ.get("CARBON_SHADOW") == "1":
            candidate = store.get_json(keys.candidate(location))
            if candidate and candidate["version"] != version:
                blob = store.get_json(keys.model(location, candidate["version"]))
                if blob is not None:
                    _write(store, location, candidate["version"], load_model(blob), history, horizon, generated_at)
                    shadow[location] = candidate["version"]

    store.update_status(
        {
            "last_success_at": generated_at,
            "last_run_status": "success",
            "last_error": None,
            "current_model_versions": versions,
            "shadow_model_versions": shadow,
            "fallback": fallback,
            "imputed_fraction": imputed,
            "updated_at": generated_at,
        }
    )
    log.info("predict: wrote %d locations (fallback=%s)", len(versions), fallback)
    return {"generated_at": generated_at, "versions": versions, "shadow": shadow, "fallback": fallback}


if __name__ == "__main__":
    run_main(run)
