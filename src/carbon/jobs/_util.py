from __future__ import annotations

import json
import logging
import os
from typing import Callable

from carbon.common import keys
from carbon.common.store import Store
from carbon.model import History


def maybe_fail(step: str) -> None:
    """Failure injection for demos and tests: FAIL_STEP=train makes `train` crash."""
    if os.environ.get("FAIL_STEP", "") == step:
        raise RuntimeError(f"Simulated failure in step '{step}' (FAIL_STEP={step})")


def load_history(store: Store, location: str) -> tuple[History, dict]:
    data = store.get_json(keys.clean_table(location))
    if data is None:
        raise RuntimeError(f"No clean table for '{location}'. Run the ingest step first.")
    return History.from_dict(data), data


def run_main(run: Callable[[], dict]) -> None:
    """Entry point shared by every job: log, run, print the summary as JSON."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(run(), default=str))
