"""Step 2: train the configured model, backtest it on a holdout, write it to the registry."""

from __future__ import annotations

import logging

from carbon.common import keys
from carbon.common.store import Store, get_store
from carbon.common.timeutil import iso, utcnow
from carbon.config import get_settings
from carbon.jobs._util import load_history, maybe_fail, run_main
from carbon.model import get_model_class, mae
from carbon.model.models import SeasonalNaive

log = logging.getLogger(__name__)


def run(store: Store | None = None) -> dict:
    maybe_fail("train")
    store = store or get_store()
    settings = get_settings()
    cls = get_model_class(settings.model)
    horizon = settings.horizon_hours
    summary = {}
    for location in settings.locations:
        history, _ = load_history(store, location)
        if len(history) < horizon + 48:
            raise RuntimeError(f"Not enough history for '{location}': {len(history)} hours")

        # Time-based split: train on older data, score on the newest `horizon` hours.
        train_hist = history.head(len(history) - horizon)
        holdout = history.values[-horizon:]
        mae_holdout = mae(holdout, cls.fit(train_hist).predict(train_hist, horizon).p50)
        mae_baseline = mae(holdout, SeasonalNaive.fit(train_hist).predict(train_hist, horizon).p50)

        now = utcnow()
        version = f"{cls.name}-{now:%Y%m%dT%H%M%S}"
        final = cls.fit(history)
        store.put_json(keys.model(location, version), final.to_dict())
        store.put_json(
            keys.metrics(location, version),
            {
                "version": version,
                "model_name": cls.name,
                "trained_at": iso(now),
                "train_start": iso(history.start),
                "train_end": iso(history.end),
                "n_points": len(history),
                "holdout_hours": horizon,
                "mae_holdout": mae_holdout,
                "mae_baseline": mae_baseline,
            },
        )
        store.put_json(keys.candidate(location), {"version": version, "model": cls.name})
        summary[location] = {"version": version, "mae_holdout": mae_holdout, "mae_baseline": mae_baseline}
        log.info("train %s: %s holdout MAE %.2f (baseline %.2f)", location, version, mae_holdout, mae_baseline)
    return summary


if __name__ == "__main__":
    run_main(run)
