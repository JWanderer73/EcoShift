"""The morning price job scores a frozen model. No network and no Optuna search."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from urllib.error import URLError

import joblib
import numpy as np
import pandas as pd
import pytest
from xgboost import XGBRegressor

from price_windows.build_dataset import folder
from price_windows.daily import (
    acquire_lock,
    henry_hub_for_hours,
    parse_henry_hub_zip,
    plan_lmp_fetches,
    run_daily,
    score_campuses,
)
from price_windows.schema import (
    BANNED_PARTS,
    GAS_FEATURE,
    MIN_LAG_HOURS,
    TARGET,
    feature_columns,
    illegal_feature_names,
)
from price_windows.train_xgboost import _release_workers, update_model


class _EchoLag:
    """Returns the 120-hour price lag, which is what a frozen model is allowed to see."""

    def predict(self, frame):
        return frame["lmp_lag_120"].to_numpy(dtype=float)


def _forbid_training(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("the morning path called the trainer")

    monkeypatch.setattr("price_windows.train_xgboost.train", fail)
    monkeypatch.setattr("price_windows.train_xgboost.update_model", fail)
    monkeypatch.setattr("price_windows.train_xgboost.continue_saved_model", fail)


def _sites() -> pd.DataFrame:
    return pd.DataFrame(
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


def _nodes() -> pd.DataFrame:
    rows = []
    for rank, price_node in ((1, "NODE_A"), (2, "NODE_B")):
        rows.append(
            {
                "campus_id": "santa-clara-main",
                "rank": rank,
                "pnode_id": price_node,
                "node_type": "Load Node",
                "latitude": 37.35,
                "longitude": -121.95,
                "distance_km": float(rank),
            }
        )
    return pd.DataFrame(rows)


def _prices() -> dict[str, pd.Series]:
    anchor = pd.Timestamp("2026-11-20 23:00", tz="UTC")
    history = pd.date_range(anchor - pd.Timedelta(hours=200), anchor, freq="h", tz="UTC")
    cheap = pd.Series(30.0, index=history)
    costly = pd.Series(30.0, index=history)
    start = anchor + pd.Timedelta(hours=1)
    for step in range(4):
        cheap.loc[start + pd.Timedelta(hours=step) - pd.Timedelta(hours=120)] = -10.0
    return {"NODE_A": cheap, "NODE_B": costly}


def _table(prices: dict[str, pd.Series]) -> pd.DataFrame:
    frames = []
    for node, series in prices.items():
        block = series.to_frame(TARGET)
        block["pnode_id"] = node
        block.index.name = "timestamp"
        frames.append(block)
    return pd.concat(frames).sort_index()


def _saved(features: list[str] | None = None) -> dict:
    return {
        "model": _EchoLag(),
        "features": features or ["hour_sin", "lmp_lag_120"],
        "target": TARGET,
    }


def _write_cache(root: Path, prices: dict[str, pd.Series]) -> None:
    directory = root / "cache" / "lmp"
    directory.mkdir(parents=True)
    for node, series in prices.items():
        frame = series.rename(TARGET).rename_axis("timestamp").reset_index()
        frame.to_csv(directory / f"{node}_20261112_20261120.csv", index=False)
    _sites().to_csv(root / "sites.csv", index=False)
    _nodes().to_csv(root / "candidates.csv", index=False)
    joblib.dump(_saved(), root / "model.joblib")


def test_henry_hub_column_is_legal_and_not_in_the_frozen_feature_list() -> None:
    assert GAS_FEATURE == "henry_hub_lag_120"
    assert int(GAS_FEATURE.rsplit("_", 1)[-1]) >= MIN_LAG_HOURS
    assert illegal_feature_names([GAS_FEATURE]) == []
    for part in BANNED_PARTS:
        assert part not in GAS_FEATURE.casefold()
    # The 8-million-row build does not gain this column until a manual rebuild.
    assert GAS_FEATURE not in feature_columns(include_load=True)


def test_henry_hub_keeps_a_five_day_old_print_and_drops_a_newer_one() -> None:
    hours = pd.DatetimeIndex([pd.Timestamp("2026-11-22 00:00", tz="UTC")])
    daily = pd.Series(
        [9.0, 1.0],
        index=pd.to_datetime(["2026-11-16", "2026-11-21"], utc=True),
    )
    assert henry_hub_for_hours(daily, hours).iloc[0] == pytest.approx(9.0)
    too_new = pd.Series([1.0], index=pd.to_datetime(["2026-11-21"], utc=True))
    assert np.isnan(henry_hub_for_hours(too_new, hours).iloc[0])
    assert np.isnan(henry_hub_for_hours(pd.Series(dtype=float), hours).iloc[0])


def test_henry_hub_zip_parser_reads_the_daily_spot() -> None:
    line = json.dumps(
        {"series_id": "NG.RNGWHHD.D", "data": [["2026-11-10", 3.25], ["2026-11-12", 3.4]]}
    )
    other = json.dumps({"series_id": "NG.OTHER.D", "data": [["2026-11-12", 99.0]]})
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("NG.txt", other + "\n" + line + "\n")
    series = parse_henry_hub_zip(raw.getvalue())
    assert series.loc[pd.Timestamp("2026-11-12", tz="UTC")] == pytest.approx(3.4)
    assert 99.0 not in set(series.to_numpy())


def test_a_node_with_no_cache_is_not_backfilled() -> None:
    expected = pd.Timestamp("2026-11-23 07:00", tz="UTC")
    newest = {
        "CURRENT": pd.Timestamp("2026-11-23 07:00", tz="UTC"),
        "STALE": pd.Timestamp("2026-11-20 23:00", tz="UTC"),
        "EMPTY": None,
    }
    assert plan_lmp_fetches(newest, expected) == ["STALE"]


def test_daily_score_uses_the_120_hour_lag_and_does_not_train(tmp_path, monkeypatch) -> None:
    _forbid_training(monkeypatch)

    def offline(*_args, **_kwargs):
        raise AssertionError("network")

    for target in (
        "price_windows.daily.urlopen",
        "price_windows.build_dataset.urlopen",
        "price_windows.recommend.urlopen",
    ):
        monkeypatch.setattr(target, offline)
    source = Path(__import__("price_windows.daily", fromlist=["daily"]).__file__).read_text()
    assert "update_model" not in source
    assert "continue_saved_model" not in source
    prices = _prices()
    _write_cache(tmp_path, prices)
    code = run_daily(
        tmp_path,
        now=pd.Timestamp("2026-11-22 08:00", tz="America/Los_Angeles"),
        fetch=False,
    )
    assert code == 0
    report = (tmp_path / "reports" / "2026-11-22.txt").read_text()
    assert "does not train" in report
    assert "-0.32 dollars" in report
    assert "120 hours" in report
    assert "days clamped to 5" not in report


def test_a_short_lag_is_refused_and_the_trainer_is_not_called(monkeypatch) -> None:
    _forbid_training(monkeypatch)
    with pytest.raises(ValueError, match="legal"):
        score_campuses(_sites(), _nodes(), _table(_prices()), _saved(["lmp_lag_24"]))


def test_a_missing_henry_hub_value_does_not_crash_the_daily_score() -> None:
    saved = _saved(["hour_sin", "lmp_lag_120", GAS_FEATURE])
    results, clamped = score_campuses(
        _sites(),
        _nodes(),
        _table(_prices()),
        saved,
        days=5,
        gas=None,
    )
    assert clamped is False
    assert results[0]["horizon_hours"] == 120
    assert results[0]["winner"]["average_usd_per_mwh"] == pytest.approx(-10.0)
    assert results[0]["winner"]["job_dollars"] == pytest.approx(-0.32)


def test_days_above_five_are_clamped_on_the_daily_path() -> None:
    results, clamped = score_campuses(_sites(), _nodes(), _table(_prices()), _saved(), days=9)
    assert clamped is True
    assert results[0]["horizon_hours"] == 120
    assert results[0]["clamped_to_3_days"] is False


def test_a_second_copy_exits_zero(tmp_path) -> None:
    held = acquire_lock(tmp_path / "cache" / "daily.lock")
    assert held is not None
    try:
        assert run_daily(tmp_path, fetch=False) == 0
    finally:
        held.close()


def test_a_missing_model_exits_without_training(tmp_path, monkeypatch) -> None:
    _forbid_training(monkeypatch)
    assert run_daily(tmp_path, fetch=False) == 1
    assert not (tmp_path / "reports").exists()


def test_a_network_failure_exits_zero_and_still_scores_the_cache(tmp_path, monkeypatch) -> None:
    _forbid_training(monkeypatch)
    monkeypatch.setattr("price_windows.daily.time.sleep", lambda _seconds: None)

    def down(*_args, **_kwargs):
        raise URLError("oasis down")

    monkeypatch.setattr("price_windows.daily.fetch_new_lmp", down)
    monkeypatch.setattr("price_windows.daily.urlopen", down)
    monkeypatch.setattr("price_windows.build_dataset.urlopen", down)
    monkeypatch.setattr("price_windows.recommend.urlopen", down)
    _write_cache(tmp_path, _prices())
    code = run_daily(
        tmp_path,
        now=pd.Timestamp("2026-11-22 08:00", tz="America/Los_Angeles"),
        fetch=True,
    )
    assert code == 0
    assert "-0.32 dollars" in (tmp_path / "reports" / "2026-11-22.txt").read_text()


def test_warm_start_adds_trees_without_touching_the_saved_model(tmp_path) -> None:
    real = folder() / "model.joblib"
    before = real.stat().st_mtime if real.exists() else None
    hours = pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "campus_id": "campus",
            "pnode_id": "NODE_A",
            TARGET: np.linspace(10.0, 20.0, len(hours)),
            "lmp_lag_168": np.linspace(9.0, 19.0, len(hours)),
            "hour_sin": 0.2,
        },
        index=hours,
    )
    features = ["lmp_lag_168", "hour_sin"]
    model = XGBRegressor(n_estimators=3, max_depth=2, n_jobs=1, verbosity=0, random_state=0)
    model.fit(frame.loc[:, features].astype(float), frame[TARGET].astype(float))
    saved = {"model": model, "features": features, "target": TARGET}
    out = tmp_path / "updated.joblib"
    try:
        update_model(saved, frame.iloc[:24], out, extra_trees=2)
        loaded = joblib.load(out)
        assert loaded["model"].get_booster().num_boosted_rounds() == 5
        assert out.resolve() != real.resolve()
        if before is not None:
            assert real.stat().st_mtime == before
    finally:
        _release_workers()
