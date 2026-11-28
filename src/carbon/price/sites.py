"""Campuses and their five nearest pricing nodes, read from the model team's CSV files.

Plain `csv` on purpose: the API reads this too and should not need pandas.
"""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path


def model_dir() -> Path:
    """Folder that holds the model's `price_windows/` package (the repo root, or /app in the image).

    Override with PRICE_MODEL_DIR.
    """
    override = os.environ.get("PRICE_MODEL_DIR")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:  # repo checkout (src/carbon/price/ -> repo root) or the image's /app
        if (parent / "price_windows" / "sites.csv").is_file():
            return parent
    return Path("/app")


def _rows(name: str) -> list[dict]:
    with (model_dir() / "price_windows" / name).open(newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def campuses() -> dict[str, dict]:
    """campus_id -> {campus_id, name, city, street, latitude, longitude, dlap_id}."""
    out: dict[str, dict] = {}
    for row in _rows("sites.csv"):
        out[row["campus_id"]] = {
            "campus_id": row["campus_id"],
            "name": row["name"],
            "city": row["city"],
            "street": row["street"],
            "dlap_id": row["dlap_id"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
        }
    return out


@lru_cache(maxsize=1)
def candidates() -> dict[str, list[dict]]:
    """campus_id -> its nodes, nearest first (rank 1 .. 5)."""
    out: dict[str, list[dict]] = {}
    for row in _rows("candidates.csv"):
        out.setdefault(row["campus_id"], []).append(
            {
                "rank": int(row["rank"]),
                "pnode_id": row["pnode_id"],
                "node_type": row["node_type"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "distance_km": float(row["distance_km"]),
            }
        )
    for nodes in out.values():
        nodes.sort(key=lambda n: n["rank"])
    return out


def campus_ids() -> tuple[str, ...]:
    return tuple(campuses())


def all_nodes() -> list[str]:
    """Every distinct pricing node any campus uses."""
    return sorted({n["pnode_id"] for nodes in candidates().values() for n in nodes})
