"""The comparison forecasts demand from the audited dataset, holding out the last 56 days."""

import json
from pathlib import Path

import numpy as np
import pytest

from src.build_demand_dataset import BENCHMARK, build, meta_path
from src.forecast_data import TARGET, TEST_DAYS, baseline_rows, features, load_dataset, train_test_hours
from src.xgb_benchmark import run


def _write_dataset(tmp_path: Path, raw) -> Path:
    table, meta = build(raw, "honest")
    path = tmp_path / "demand_dataset.csv"
    table.to_csv(path)
    meta_path(path).write_text(json.dumps(meta))
    return path


def test_dataset_loads_with_its_feature_list(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    loaded = load_dataset(path)
    assert TARGET in loaded.columns
    assert BENCHMARK in loaded.columns
    assert TARGET not in loaded.attrs["features"]
    assert BENCHMARK not in loaded.attrs["features"]
    assert "ng_mwh" not in loaded.columns


def test_split_holds_out_the_last_56_days(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    train, test = train_test_hours(path)
    assert len(test) == TEST_DAYS * 24
    assert train.index.max() < test.index.min()
    assert TARGET == "demand_mwh"


def test_features_refuse_the_benchmark(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    train, _ = train_test_hours(path)
    train.attrs["features"] = [*train.attrs["features"], BENCHMARK]
    with pytest.raises(ValueError):
        features(train)


def test_baselines_include_the_caiso_forecast(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    _, test = train_test_hours(path)
    names = {row["model"] for row in baseline_rows(test)}
    assert names == {"Same hour yesterday", "Same hour last week", "CAISO forecast"}


def test_short_xgb_fit_is_scored_and_saved(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    result = run(path=path, param_grid={"n_estimators": [20], "max_depth": [2], "learning_rate": [0.1]})
    assert result["target"] == "demand_mwh"
    assert result["test_rows"] == TEST_DAYS * 24
    assert result["fit_seconds"] >= 0.0
    assert np.isfinite(result["mae"])
    assert np.isfinite(result["mape"])
    assert Path(result["model_path"]).exists()
    assert Path(result["model_path"]).parent == tmp_path / "models"
