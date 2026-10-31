"""Step 3: promotion gate.

A new model replaces the current champion only if it is not worse on recent data
it was not trained on. This is the only rollout mechanism: no traffic splitting.
"""

from __future__ import annotations

import logging

from carbon.common import keys
from carbon.common.store import Store, get_store
from carbon.common.timeutil import iso, utcnow
from carbon.config import get_settings
from carbon.jobs._util import load_history, maybe_fail, run_main
from carbon.model import load_model, mae

log = logging.getLogger(__name__)


def should_promote(candidate_mae: float, champion_mae: float, tolerance: float) -> bool:
    """Promote if the candidate's error is no more than `tolerance` (fraction) above the champion's."""
    return candidate_mae <= champion_mae * (1.0 + tolerance)


def run(store: Store | None = None) -> dict:
    maybe_fail("gate")
    store = store or get_store()
    settings = get_settings()
    horizon = settings.horizon_hours
    summary = {}
    for location in settings.locations:
        candidate = store.get_json(keys.candidate(location))
        if candidate is None:
            raise RuntimeError(f"No candidate model for '{location}'. Run the train step first.")
        metrics = store.get_json(keys.metrics(location, candidate["version"]))

        champion = store.get_json(keys.champion(location))
        champion_blob = champion and store.get_json(keys.model(location, champion["version"]))
        if champion_blob is None:
            promote, reason, champion_mae = True, "no champion yet", None
        else:
            # Score the champion on the same holdout the candidate was scored on.
            history, _ = load_history(store, location)
            train_hist = history.head(len(history) - horizon)
            champion_mae = mae(history.values[-horizon:], load_model(champion_blob).predict(train_hist, horizon).p50)
            promote = should_promote(metrics["mae_holdout"], champion_mae, settings.promotion_tolerance)
            reason = f"candidate MAE {metrics['mae_holdout']:.2f} vs champion {champion_mae:.2f}"

        if promote:
            store.put_json(
                keys.champion(location),
                {
                    "version": candidate["version"],
                    "model": candidate["model"],
                    "promoted_at": iso(utcnow()),
                    "mae_holdout": metrics["mae_holdout"],
                },
            )
        summary[location] = {"promoted": promote, "version": candidate["version"], "reason": reason}
        log.info("gate %s: promoted=%s (%s)", location, promote, reason)
    return summary


if __name__ == "__main__":
    run_main(run)
