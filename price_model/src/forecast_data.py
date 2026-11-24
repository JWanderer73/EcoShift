"""Shared data for the model scripts.

The question is: how many megawatthours of electricity will CAISO serve
this hour?

The table is ``data/processed/demand_dataset.csv``, built by
``python -m src.build_demand_dataset``. Its ``.meta.json`` lists the
features. The audit in ``src/column_audit.py`` already removed the
columns that restate demand (the fuel mix and carbon), exact copies,
and near-duplicates.

Every model does the same three things:

1. Read that table and its feature list.
2. Train on every hour before the last 56 days. Test on the last 56 days.
3. Score the test hours once. The grid search never sees those hours.

The test block is late summer into fall 2026. Training includes late
summer 2025 and all of summer 2026, so the models have seen peak demand
before they are scored on it.

``benchmark_caiso_forecast_mwh`` is CAISO's own day-ahead forecast. It is
scored beside the models as the number to beat, and it is never a feature.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from src.build_demand_dataset import BENCHMARK, DEFAULT_VARIANT, meta_path, output_path
from src.carbon_data import repo_root
from src.column_audit import DROPPED

# The electricity we are forecasting, in megawatthours.
TARGET = "demand_mwh"
TARGET_UNIT = "MWh"

# The last 56 days are the test block. Eight weeks covers every weekday
# eight times and the end of the summer peak.
TEST_DAYS = 56

# Forward folds inside the training block.
CV_SPLITS = 3

# Baselines scored beside the models: a column of the test block that is
# already a forecast of demand.
BASELINES = {
    "Same hour yesterday": "demand_lag_24",
    "Same hour last week": "demand_lag_168",
    "CAISO forecast": BENCHMARK,
}


def data_path(variant: str = DEFAULT_VARIANT) -> Path:
    """The demand dataset for a variant. The comparison does not fall back to another file."""
    path = output_path(variant)
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Build it with: python -m src.build_demand_dataset")
    return path


def load_dataset(path: Path | None = None) -> pd.DataFrame:
    """Read a demand dataset and attach its metadata.

    Args:
        path: CSV to read. Defaults to the honest variant.

    Returns:
        Hourly rows indexed in UTC. ``attrs`` holds the feature list, the
        variant, the content hash, and the file it came from.
    """
    path = data_path() if path is None else path
    meta = json.loads(meta_path(path).read_text())
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    missing = [column for column in [TARGET, BENCHMARK, *meta["features"]] if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    frame = frame.sort_index()
    frame.attrs.update(
        {
            "source_path": str(path),
            "features": list(meta["features"]),
            "variant": meta["variant"],
            "content_hash": meta["content_hash"],
            "model_dir": str(_model_dir(path, meta["variant"])),
        }
    )
    return frame


def _model_dir(path: Path, variant: str) -> Path:
    """Saved models go in ``models/`` for the repo's own datasets, and beside any other file."""
    if path.resolve() == output_path(variant).resolve():
        root = repo_root() / "models"
        return root if variant == DEFAULT_VARIANT else root / variant
    return path.parent / "models"


def feature_columns(path: Path | None = None) -> list[str]:
    """The feature list from the dataset's metadata."""
    path = data_path() if path is None else path
    return list(json.loads(meta_path(path).read_text())["features"])


def train_test_hours(path: Path | None = None, test_days: int = TEST_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cut off the last ``test_days`` days as the test block.

    Returns:
        Training rows, then test rows. Training ends before the test starts.
    """
    table = load_dataset(path)
    cutoff = table.index.max() - pd.Timedelta(days=test_days)
    train = table.loc[table.index <= cutoff].copy()
    test = table.loc[table.index > cutoff].copy()
    if train.empty or test.empty:
        raise ValueError("the time split produced an empty side")
    if train.index.max() >= test.index.min():
        raise ValueError("training hours overlap the test hours")
    for side in (train, test):
        side.attrs.update(table.attrs)
        side.attrs["model_rows"] = int(len(table))
    return train, test


def features(frame: pd.DataFrame) -> pd.DataFrame:
    """The columns the model sees, from the dataset's metadata.

    Raises if the list includes the target, the CAISO benchmark, or any
    column the audit dropped.
    """
    columns = frame.attrs["features"]
    banned = sorted(set(columns) & ({TARGET, BENCHMARK} | set(DROPPED)))
    if banned:
        raise ValueError(f"features include columns that restate demand: {banned}")
    return frame.loc[:, columns].astype(float)


def score(actual, predicted) -> dict[str, float]:
    """MAE, RMSE, and MSE in megawatthours, and MAPE in percent."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    residual = actual - predicted
    return {
        "mae": float(np.mean(np.abs(residual))),
        "mape": float(100.0 * np.mean(np.abs(residual) / np.abs(actual))),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "mse": float(np.mean(np.square(residual))),
    }


def baseline_rows(test: pd.DataFrame) -> list[dict]:
    """Score the baselines on the test block. Nothing is fit."""
    rows = []
    for name, column in BASELINES.items():
        if column not in test.columns:
            continue
        pair = test[[TARGET, column]].dropna()
        if pair.empty:
            continue
        rows.append(
            {
                "model": name,
                "kind": "baseline",
                "target": TARGET,
                "unit": TARGET_UNIT,
                "variant": test.attrs.get("variant"),
                "dataset_hash": test.attrs.get("content_hash"),
                **score(pair[TARGET], pair[column]),
                "test_rows": int(len(pair)),
                "test_start": str(pair.index.min()),
            }
        )
    return rows


def print_split(train: pd.DataFrame, test: pd.DataFrame) -> None:
    """Print the cut and the error of simply trusting CAISO's own forecast."""
    total = len(train) + len(test)
    print(f"target: {TARGET} ({TARGET_UNIT})")
    print(f"file: {train.attrs.get('source_path', '')} (variant {train.attrs.get('variant', '')})")
    print(f"rows: {train.attrs.get('model_rows', total)}, features: {len(train.attrs.get('features', []))}")
    print(f"TRAIN: {len(train)} hours, {train.index.min()} -> {train.index.max()}")
    print(f"TEST:  {len(test)} hours, {test.index.min()} -> {test.index.max()}")
    comparable = test[[TARGET, BENCHMARK]].dropna()
    caiso = score(comparable[TARGET], comparable[BENCHMARK])
    print(f"CAISO forecast alone, test MAE: {caiso['mae']:.1f} {TARGET_UNIT} ({caiso['mape']:.2f}%)")


def _plain(value):
    """Turn numpy values into ordinary Python so the result can be printed and saved."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def model_slug(name: str) -> str:
    """File name for a saved model: ``Hist gradient boosting`` becomes ``hist_gradient_boosting``."""
    return name.lower().replace(" ", "_")


def search_and_score(name: str, estimator, param_grid: dict, train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Pick settings on the training hours, then score the test hours once.

    The grid search walks forward through the training block. It does not
    look at the test block. After a winner is chosen, that winner is fit
    again on all of the training hours and saved with joblib.
    ``fit_seconds`` is that one fit. ``search_seconds`` is the whole grid search.

    An empty ``param_grid`` means the model has nothing to tune. It is fit once.
    """
    x_train = features(train)
    y_train = train[TARGET]
    x_test = features(test)
    y_test = test[TARGET]

    if param_grid:
        search = GridSearchCV(
            estimator,
            param_grid,
            cv=TimeSeriesSplit(n_splits=CV_SPLITS),
            scoring="neg_mean_absolute_error",
            n_jobs=1,
            refit=False,
        )
        started = time.perf_counter()
        search.fit(x_train, y_train)
        search_seconds = time.perf_counter() - started
        chosen = clone(estimator).set_params(**search.best_params_)
        best_params = _plain(search.best_params_)
        cv_mae = float(-search.best_score_)
    else:
        chosen = clone(estimator)
        best_params = {}
        search_seconds = 0.0
        folds = []
        for fit_index, valid_index in TimeSeriesSplit(n_splits=CV_SPLITS).split(x_train):
            fold = clone(estimator).fit(x_train.iloc[fit_index], y_train.iloc[fit_index])
            folds.append(mean_absolute_error(y_train.iloc[valid_index], np.maximum(fold.predict(x_train.iloc[valid_index]), 0.0)))
        cv_mae = float(np.mean(folds))

    started = time.perf_counter()
    chosen.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started
    started = time.perf_counter()
    predicted = np.maximum(chosen.predict(x_test), 0.0)
    predict_seconds = time.perf_counter() - started
    train_mae = float(mean_absolute_error(y_train, np.maximum(chosen.predict(x_train), 0.0)))

    model_dir = Path(train.attrs["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{model_slug(name)}.joblib"
    joblib.dump(chosen, model_path)

    return {
        "model": name,
        "kind": "model",
        "target": TARGET,
        "unit": TARGET_UNIT,
        "variant": train.attrs.get("variant"),
        "dataset_hash": train.attrs.get("content_hash"),
        "best_params": best_params,
        "train_mae": train_mae,
        "cv_mae": cv_mae,
        **score(y_test, predicted),
        "fit_seconds": float(fit_seconds),
        "search_seconds": float(search_seconds),
        "predict_seconds": float(predict_seconds),
        "n_features": int(x_train.shape[1]),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_end": str(train.index.max()),
        "test_start": str(test.index.min()),
        "model_path": str(model_path),
    }


def print_score(result: dict) -> None:
    """Print the winning settings, how long the fit took, and the test error."""
    unit = result.get("unit", TARGET_UNIT)
    print(result["model"])
    if result["best_params"]:
        settings = ", ".join(f"{key}={value}" for key, value in result["best_params"].items())
        print(f"  best settings: {settings}")
    else:
        print("  best settings: none (nothing to tune)")
    print(f"  training MAE: {result['train_mae']:.1f} {unit}")
    print(f"  forward-fold MAE: {result['cv_mae']:.1f} {unit}")
    print(f"  fit: {result['fit_seconds']:.3f} s")
    print(f"  grid search: {result['search_seconds']:.3f} s")
    print(f"  test MAE: {result['mae']:.1f} {unit} ({result['mape']:.2f}%)")
    print(f"  test RMSE: {result['rmse']:.1f} {unit}")
