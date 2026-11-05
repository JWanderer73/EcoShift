"""Shared data for the model scripts.

The question is: how many megawatthours of electricity will CAISO use
this hour?

The file is ``data/processed/cleaned_weather_carbon.csv``. Carbon
intensity is not the target. It is computed from the fuel columns in
that same file, so predicting it is rebuilding a column. This file has
no hourly electricity price. The electricity measurement it does have
is ``demand_mwh``.

Every model does the same three things:

1. Read that cleaned CSV.
2. Train on the first 60% of hours. Test on the last 40%.
3. Score the test hours once. The grid search never sees those hours.

The split is in time order. Later hours are not used to fit the model.

What the model is allowed to see, before the hour happens:

- the time of day and the time of year
- electricity use at this hour yesterday and last week
- yesterday's weather
- the demand forecast CAISO already published for this hour

What it is not allowed to see:

- this hour's demand (that is the answer)
- the fuel megawatthours
- carbon intensity
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit

from src.carbon_data import repo_root

# The electricity we are forecasting, in megawatthours.
TARGET = "demand_mwh"
TARGET_UNIT = "MWh"

# First 60% trains. Last 40% is the test.
TRAIN_FRACTION = 0.60

# Forward folds inside the training block.
CV_SPLITS = 3

# Taken straight from the cleaned CSV. Fuel and carbon are not in this list.
RAW_COLUMNS = [
    "demand_mwh",
    "demand_forecast_mwh",
    "temp",
    "radiation",
    "radiation_fresno",
    "wind_10m",
]

# Built from past hours, plus the forecast CAISO published ahead of time.
FEATURE_COLUMNS = [
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
    "demand_lag_24",
    "demand_lag_168",
    "temp_lag_24",
    "radiation_lag_24",
    "radiation_fresno_lag_24",
    "wind_10m_lag_24",
    "demand_forecast_mwh",
]


def cleaned_csv_path() -> Path:
    """The 10,000-hour cleaned table."""
    return repo_root() / "data" / "processed" / "cleaned_weather_carbon.csv"


def data_path() -> Path:
    """The cleaned CSV. The comparison does not fall back to another file."""
    path = cleaned_csv_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Build it with: python -m src.build_cleaned_dataset"
        )
    return path


def load_hours(path: Path | None = None) -> pd.DataFrame:
    """Read the cleaned CSV and keep demand, the demand forecast, and weather.

    Args:
        path: CSV to read. Defaults to the cleaned table.

    Returns:
        Hourly rows indexed in UTC. Fuel columns and carbon intensity are omitted.
    """
    path = data_path() if path is None else path
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    missing = [column for column in RAW_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    hours = frame.loc[:, RAW_COLUMNS].sort_index()
    hours.attrs["source_path"] = str(path)
    hours.attrs["csv_rows"] = int(len(frame))
    return hours


def modeling_table(path: Path | None = None) -> pd.DataFrame:
    """Add the clock and yesterday / last week, then drop hours that lack them.

    The first 168 hours fall away because last week's demand is not known yet.
    A missing hour does not shorten a lag: the lag is taken on a complete
    hourly clock.
    """
    hours = load_hours(path)
    frame = hours[~hours.index.duplicated(keep="last")].sort_index()
    full_index = pd.date_range(frame.index.min(), frame.index.max(), freq="h", tz="UTC")
    frame = frame.reindex(full_index)
    local = frame.index.tz_convert("America/Los_Angeles")
    hour = local.hour.to_numpy()
    dow = local.dayofweek.to_numpy()
    day_of_year = local.dayofyear.to_numpy()
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    frame["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)
    frame["demand_lag_24"] = frame[TARGET].shift(24)
    frame["demand_lag_168"] = frame[TARGET].shift(168)
    frame["temp_lag_24"] = frame["temp"].shift(24)
    frame["radiation_lag_24"] = frame["radiation"].shift(24)
    frame["radiation_fresno_lag_24"] = frame["radiation_fresno"].shift(24)
    frame["wind_10m_lag_24"] = frame["wind_10m"].shift(24)
    keep = [TARGET, *FEATURE_COLUMNS]
    table = frame.dropna(subset=keep).loc[:, keep]
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
    """The columns the model sees. The demand target is not one of them."""
    if TARGET in FEATURE_COLUMNS:
        raise ValueError("the model is being shown the electricity use it is supposed to predict")
    return frame.loc[:, FEATURE_COLUMNS].astype(float)


def print_split(train: pd.DataFrame, test: pd.DataFrame) -> None:
    """Print the cut and the error of simply trusting CAISO's own forecast."""
    total = len(train) + len(test)
    forecast_error = np.abs(test[TARGET] - test["demand_forecast_mwh"])
    print(f"target: {TARGET} ({TARGET_UNIT})")
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
    print(f"CAISO forecast alone, test MAE: {float(forecast_error.mean()):.1f} {TARGET_UNIT}")


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

    fresh = clone(chosen)
    started = time.perf_counter()
    fresh.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - started
    predicted = np.maximum(fresh.predict(x_test), 0.0)
    actual = y_test.to_numpy(dtype=float)
    residual = actual - predicted
    return {
        "model": name,
        "target": TARGET,
        "unit": TARGET_UNIT,
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
    unit = result.get("unit", TARGET_UNIT)
    print(result["model"])
    if result["best_params"]:
        settings = ", ".join(f"{key}={value}" for key, value in result["best_params"].items())
        print(f"  best settings: {settings}")
    else:
        print("  best settings: none (nothing to tune)")
    if result["cv_mae"] is not None:
        print(f"  training-block MAE: {result['cv_mae']:.1f} {unit}")
    print(f"  fit: {result['fit_seconds']:.3f} s")
    print(f"  grid search: {result['search_seconds']:.3f} s")
    print(f"  test MAE: {result['mae']:.1f} {unit}")
    print(f"  test MSE: {result['mse']:.1f}")
