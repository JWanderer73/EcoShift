"""Step 1: pull data, validate it, write the clean table.

With CARBON_MODEL=price_xgb this refreshes CAISO day-ahead prices for every node the delivered
model uses (see carbon.price.run.ingest). With any other model it generates a synthetic hourly
price series so the system runs end to end without data or credentials. This is the only step
that knows where the data comes from.
"""

from __future__ import annotations

import logging

import numpy as np

from carbon.common import keys
from carbon.common.store import Store, get_store
from carbon.common.timeutil import HOUR, floor_hour, utcnow
from carbon.common.validate import validate_series
from carbon.config import PRICE_MODEL, get_settings
from carbon.jobs._util import maybe_fail, run_main
from carbon.model import History

log = logging.getLogger(__name__)


def _noise(hour_index: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic per-hour noise, so a given timestamp always has the same 'actual'."""
    u = (np.sin(hour_index * 12.9898 + seed * 78.233) * 43758.5453) % 1.0
    return (u - 0.5) * 30.0


def fetch_raw(location: str, start, n_hours: int) -> np.ndarray:
    """Synthetic $/MWh series: midday solar dip, evening peak, lower on weekends."""
    idx = np.arange(n_hours)
    hour = (start.hour + idx) % 24
    weekday = (start.weekday() + (start.hour + idx) // 24) % 7
    base = 330 - 130 * np.exp(-((hour - 13) ** 2) / 14) + 45 * np.exp(-((hour - 19) ** 2) / 6)
    base = base - 20 * (weekday >= 5)
    epoch_hours = int(start.timestamp() // 3600) + idx
    seed = sum(ord(c) for c in location)
    return np.clip(base + _noise(epoch_hours, seed), 50, None) / 6  # roughly $20-55/MWh


def run(store: Store | None = None) -> dict:
    maybe_fail("ingest")
    store = store or get_store()
    settings = get_settings()
    if settings.model == PRICE_MODEL:
        from carbon.price import run as price_run

        return price_run.ingest(store)
    summary = {}
    for location in settings.locations:
        end = floor_hour(utcnow())
        n = settings.history_days * 24
        start = end - n * HOUR
        raw = fetch_raw(location, start, n)
        values, imputed = validate_series(raw, min_value=-1000.0, max_value=5000.0)
        table = {
            "location": location,
            "source": "synthetic",
            "imputed_fraction": imputed,
            **History(start, values).to_dict(),
        }
        store.put_json(keys.clean_table(location), table)
        summary[location] = {"hours": n, "imputed_fraction": imputed}
        log.info("ingest %s: %d hours, %.1f%% imputed", location, n, 100 * imputed)
    return summary


if __name__ == "__main__":
    run_main(run)
