"""The price-window plan, checked in one place. No network and no Optuna search.

Run this after the dataset build and the trainer have written their files:

    pytest tests/test_price_acceptance.py
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from price_windows.build_dataset import folder
from price_windows.recommend import format_report, job_dollars, recommend
from price_windows.schema import (
    BANNED_PARTS,
    MIN_LAG_HOURS,
    PERCENT_PRICE_FLOOR,
    TARGET,
    illegal_feature_names,
)
from price_windows.train_xgboost import _errors


def _missing(path):
    if not path.exists():
        pytest.fail(f"{path.name} is not written yet")


def test_each_campus_has_one_row_and_five_nodes():
    sites_path = folder() / "sites.csv"
    nodes_path = folder() / "candidates.csv"
    _missing(sites_path)
    _missing(nodes_path)
    sites = pd.read_csv(sites_path)
    nodes = pd.read_csv(nodes_path)
    assert sites["campus_id"].is_unique
    assert len(sites) >= 1
    counts = nodes.groupby("campus_id").size()
    assert set(counts.index) == set(sites["campus_id"])
    assert bool(counts.eq(5).all())
    assert set(nodes["rank"]) <= {1, 2, 3, 4, 5}


def test_saved_features_have_no_component_and_no_short_lag():
    assert illegal_feature_names(["lmp_lag_71", "lmp_cong_lag_168", "mce_lag_120", TARGET]) == [
        "lmp_lag_71",
        "lmp_cong_lag_168",
        "mce_lag_120",
        TARGET,
    ]
    assert illegal_feature_names(["lmp_lag_72"]) == []
    path = folder() / "price_dataset.meta.json"
    _missing(path)
    meta = json.loads(path.read_text())
    features = meta["features"]
    assert illegal_feature_names(features) == []
    assert TARGET not in features
    assert meta["minimum_price_lag_hours"] >= MIN_LAG_HOURS
    for name in features:
        lowered = name.casefold()
        assert not any(part in lowered for part in BANNED_PARTS)


def test_percent_error_ignores_prices_at_or_below_five_dollars_and_mae_is_finite():
    actual = np.array([-10.0, 5.0, 10.0])
    predicted = np.array([-12.0, 0.0, 8.0])
    scored = _errors(actual, predicted)
    assert math.isfinite(scored["mae_usd_per_mwh"])
    assert scored["mae_usd_per_mwh"] == pytest.approx(np.mean([2.0, 5.0, 2.0]))
    assert scored["percent_error_mean"] == pytest.approx(20.0)
    path = folder() / "metrics.json"
    _missing(path)
    metrics = json.loads(path.read_text())
    assert metrics["clipped_at_zero"] is False
    assert metrics["percent_error_min_price_usd_per_mwh"] == PERCENT_PRICE_FLOOR
    assert math.isfinite(metrics["test"]["mae_usd_per_mwh"])
    assert math.isfinite(metrics["test"]["rmse_usd_per_mwh"])
    assert (folder() / "model.joblib").exists()


def test_an_8kw_four_hour_job_prints_dollars():
    # 8 kW * 4 h = 32 kWh. 40 $/MWh * 32 / 1000 = 1.28 dollars.
    assert job_dollars(40.0, 8, 4) == pytest.approx(1.28)
    anchor = pd.Timestamp("2026-11-14 23:00", tz="UTC")
    history = pd.date_range(anchor - pd.Timedelta(hours=200), anchor, freq="h", tz="UTC")
    cheap = pd.Series(40.0, index=history)
    costly = pd.Series(40.0, index=history)
    for step in range(1, 5):
        cheap.loc[anchor + pd.Timedelta(hours=step - 120)] = 40.0
    sites = pd.DataFrame(
        [
            {
                "campus_id": "santa-clara-main",
                "name": "Main",
                "street": "1 Main St",
                "city": "Santa Clara",
                "latitude": 37.35,
                "longitude": -121.95,
                "dlap_id": "DLAP_PGAE-APND",
            }
        ]
    )
    nodes = pd.DataFrame(
        [
            {
                "campus_id": "santa-clara-main",
                "rank": rank,
                "pnode_id": f"NODE_{rank}",
                "node_type": "Load Node",
                "latitude": 37.35,
                "longitude": -121.95,
                "distance_km": float(rank),
            }
            for rank in range(1, 6)
        ]
    )
    prices = {f"NODE_{rank}": cheap if rank == 1 else costly for rank in range(1, 6)}
    frames = []
    for pnode_id, series in prices.items():
        block = pd.DataFrame({TARGET: series, "pnode_id": pnode_id, "campus_id": "santa-clara-main"})
        block.index.name = "timestamp"
        frames.append(block)
    table = pd.concat(frames).sort_index()

    class _Flat:
        def predict(self, frame):
            return np.full(len(frame), 40.0)

    result = recommend(
        "Santa Clara",
        duration=4,
        days=9,
        kw=8,
        table=table,
        sites=sites,
        candidates=nodes,
        saved={"model": _Flat(), "features": ["hour_sin"], "target": TARGET},
    )
    assert result["clamped_to_3_days"] is True
    assert result["horizon_hours"] == 72
    assert len(result["options"]) == 5
    assert result["winner"]["job_dollars"] == pytest.approx(1.28)
    text = format_report(result)
    assert "1.28 dollars" in text
    assert "0.04000 $/kWh" in text
    assert "days clamped to 3" in text
    assert "DLAP_PGAE-APND" in text


def test_readme_and_gitignore_match_the_plan():
    readme = (folder() / "README.md").read_text()
    assert "python -m price_windows.build_dataset" in readme
    assert "python -m price_windows.train_xgboost" in readme
    assert "python -m price_windows.recommend" in readme
    assert "dollars per megawatt-hour" in readme
    ignore = (folder().parent / ".gitignore").read_text()
    assert "price_windows/price_dataset.csv" in ignore
    assert "price_windows/*.joblib" in ignore
    assert "price_windows/cache/" in ignore
