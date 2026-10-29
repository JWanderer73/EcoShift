"""Shared data for the model scripts.

Every model file does the same three things before it fits:

1. Read ``data/processed/cleaned_weather_carbon.csv``.
2. Keep the first 60% of hours for training and the last 40% for testing.
3. Score the test hours once. The grid search never sees those hours.

The split is in time order. Shuffling would let a model train on Tuesday
and then be scored on Monday of the same week.

Fuel megawatthour columns stay in the CSV, but they are not features.
They are the ingredients of ``carbon_intensity_g_per_kwh``. A model that
saw them would be copying that formula.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from src.carbon_data import PANEL_COLUMNS, cache_path, model_frame, repo_root
from src.modeling import CYCLICAL_NUMERIC, TARGET, check_features

# First 60% trains. Last 40% is the test. This is the only split the
# comparison scripts use. The notebooks still hold out their own last 28 days.
TRAIN_FRACTION = 0.60

# Forward folds inside the training block. Three is enough to pick a setting
# without spending the whole run on cross-validation.
CV_SPLITS = 3

# Things a forecast can know the day before the hour it is predicting:
# time of day, time of year, carbon at this hour yesterday and last week,
# yesterday's weather, and the demand forecast CAISO already published.
FEATURE_COLUMNS = list(CYCLICAL_NUMERIC)


def cleaned_csv_path() -> Path:
    """The 10,000-hour weather and carbon table."""
    return repo_root() / "data" / "processed" / "cleaned_weather_carbon.csv"


def data_path() -> Path:
    """Use the cleaned 10,000-hour file, or the shorter notebook cache if it is missing."""
    cleaned = cleaned_csv_path()
    if cleaned.exists():
        return cleaned
    return cache_path()


def load_hours(path: Path | None = None) -> pd.DataFrame:
    """Read the CSV and keep only the columns a forecast is allowed to start from.

    Args:
        path: CSV to read. Defaults to the cleaned table.

    Returns:
        Hourly rows indexed in UTC. Fuel columns are not included.
    """
    path = data_path() if path is None else path
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    missing = [column for column in PANEL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    hours = frame.loc[:, PANEL_COLUMNS].sort_index()
    hours.attrs["source_path"] = str(path)
    hours.attrs["csv_rows"] = int(len(frame))
    return hours


def modeling_table(path: Path | None = None) -> pd.DataFrame:
    """Add the clock and the yesterday / last-week columns, then drop incomplete hours.

    The first 168 hours fall away because last week's carbon is not known yet.
    """
    hours = load_hours(path)
    table = model_frame(hours)
    table.attrs["source_path"] = hours.attrs["source_path"]
    table.attrs["csv_rows"] = hours.attrs["csv_rows"]
    return table


def train_test_hours(path: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cut the table at 60%.

    Returns:
        Training rows, then test rows. Training ends before the test starts.
    """
    table = modeling_table(path)
    cut = int(len(table) * TRAIN_FRACTION)
    train = table.iloc[:cut].copy()
    test = table.iloc[cut:].copy()
    if train.empty or test.empty:
        raise ValueError("the 60/40 split produced an empty side")
    if train.index.max() >= test.index.min():
        raise ValueError("training hours overlap the test hours")
    for side in (train, test):
        side.attrs["source_path"] = table.attrs["source_path"]
        side.attrs["csv_rows"] = table.attrs["csv_rows"]
        side.attrs["model_rows"] = int(len(table))
    return train, test


def features(frame: pd.DataFrame) -> pd.DataFrame:
    """The columns the model actually sees, in a fixed order."""
    check_features(FEATURE_COLUMNS)
    return frame.loc[:, FEATURE_COLUMNS].astype(float)


def print_split(train: pd.DataFrame, test: pd.DataFrame) -> None:
    """Print the cut so it is obvious which hours were trained on."""
    total = len(train) + len(test)
    print(f"file: {train.attrs.get('source_path', '')}")
    print(f"csv rows: {train.attrs.get('csv_rows', '')}")
    print(f"rows after lags: {train.attrs.get('model_rows', total)}")
    print(
        f"TRAIN {TRAIN_FRACTION:.0%}: {len(train)} hours, "
        f"{train.index.min()} -> {train.index.max()}"
    )
    print(
        f"TEST  {1 - TRAIN_FRACTION:.0%}: {len(test)} hours, "
        f"{test.index.min()} -> {test.index.max()}"
    )


def _plain(value):
    """Turn numpy values into ordinary Python so the result can be printed and saved."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def search_and_score(name: str, estimator, param_grid: dict, train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """Pick settings on the training hours, then score the test hours once.

    The grid search walks forward through the training block. It does not
    look at the test block. After a winner is chosen, that winner is fit
    again on all of the training hours. ``fit_seconds`` is that one fit.
    ``search_seconds`` is the whole grid search.

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
            refit=True,
        )
        started = time.perf_counter()
        search.fit(x_train, y_train)
        search_seconds = time.perf_counter() - started
        chosen = search.best_estimator_
        best_params = _plain(search.best_params_)
        cv_mae = float(-search.best_score_)
    else:
        started = time.perf_counter()
        estimator.fit(x_train, y_train)
        search_seconds = time.perf_counter() - started
        chosen = estimator
        best_params = {}
        cv_mae = None

    # Time one clean fit of the winning settings. The search time above
    # includes every candidate, so it is not the training speed of the model.
    fresh = clone(chosen)
    started = time.perf_counter()
    fresh.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started
    predicted = np.maximum(fresh.predict(x_test), 0.0)
    actual = y_test.to_numpy(dtype=float)
    residual = actual - predicted
    return {
        "model": name,
        "best_params": best_params,
        "cv_mae": cv_mae,
        "mae": float(mean_absolute_error(actual, predicted)),
        "mse": float(np.mean(np.square(residual))),
        "fit_seconds": float(fit_seconds),
        "search_seconds": float(search_seconds),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_end": str(train.index.max()),
        "test_start": str(test.index.min()),
    }


def print_score(result: dict) -> None:
    """Print the winning settings, how long the fit took, and the test error."""
    print(result["model"])
    if result["best_params"]:
        settings = ", ".join(f"{key}={value}" for key, value in result["best_params"].items())
        print(f"  best settings: {settings}")
    else:
        print("  best settings: none (nothing to tune)")
    if result["cv_mae"] is not None:
        print(f"  training-block MAE: {result['cv_mae']:.3f} g/kWh")
    print(f"  fit: {result['fit_seconds']:.3f} s")
    print(f"  grid search: {result['search_seconds']:.3f} s")
    print(f"  test MAE: {result['mae']:.3f} g/kWh")
    print(f"  test MSE: {result['mse']:.3f}")
