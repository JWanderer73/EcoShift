"""Generate API response fixtures from the real code, so they always match the contract.

Usage: python scripts/make_fixtures.py
Writes JSON files to ./fixtures for the CLI and dashboard to develop against.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "fixtures"


def main() -> None:
    tmp = tempfile.mkdtemp()
    os.environ.update(CARBON_STORE="local", CARBON_LOCAL_DIR=tmp, CARBON_CACHE_TTL="0", CARBON_NOW="2026-10-27T14:30:00Z")

    from fastapi.testclient import TestClient

    from carbon.api.main import app
    from carbon.common.store import get_store
    from carbon.jobs import pipeline

    pipeline.run()
    client = TestClient(app)
    OUT.mkdir(exist_ok=True)

    def save(name: str, response) -> None:
        (OUT / name).write_text(json.dumps(response.json(), indent=2) + "\n")
        print("wrote", name, response.status_code)

    q = {"duration_hours": 4, "max_wait": "1d"}
    save("health_ok.json", client.get("/v1/health"))
    save("forecast_ok.json", client.get("/v1/forecast", params={"hours": 24}))
    save("windows_ok.json", client.get("/v1/windows", params=q))
    save("windows_clamped.json", client.get("/v1/windows", params={**q, "max_wait": "10d"}))
    save("error_unsupported_location.json", client.get("/v1/windows", params={**q, "location": "nowhere"}))

    # Pipeline failed after a good run: last forecast is still served, with a warning.
    get_store().update_status({"last_run_status": "failed", "last_error": "train: simulated failure"})
    save("windows_pipeline_failed.json", client.get("/v1/windows", params=q))
    save("health_pipeline_failed.json", client.get("/v1/health"))

    # Pipeline stopped running entirely: nothing wrote a failure record, the forecast just ages.
    get_store().update_status({"last_run_status": "success", "last_error": None})
    os.environ["CARBON_NOW"] = "2026-10-27T23:30:00Z"
    save("windows_stale.json", client.get("/v1/windows", params=q))
    save("health_stale.json", client.get("/v1/health"))

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
