"""Run the whole pipeline locally: ingest -> train -> gate -> predict.

In AWS, Step Functions runs the same four steps as separate ECS tasks and its Catch
state records failures. This runner does the equivalent for local development.
"""

from __future__ import annotations

from carbon.common.store import get_store
from carbon.common.timeutil import iso, utcnow
from carbon.jobs import gate, ingest, predict, train
from carbon.jobs._util import run_main

STEPS = [("ingest", ingest.run), ("train", train.run), ("gate", gate.run), ("predict", predict.run)]


def run() -> dict:
    store = get_store()
    results: dict = {}
    for name, step in STEPS:
        try:
            results[name] = step(store)
        except Exception as exc:
            store.update_status(
                {"last_run_status": "failed", "last_error": f"{name}: {exc}", "updated_at": iso(utcnow())}
            )
            raise
    return results


if __name__ == "__main__":
    run_main(run)
