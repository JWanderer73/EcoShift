"""Time an XGBoost forecast of CAISO carbon intensity and score the holdout.

The fit reads ``data/processed/cleaned_weather_carbon.csv`` when that
10,000-hour table is present, and the cached hourly panel otherwise.
Fuel megawatthours are not features. The last 28 days are scored once.
``N_ESTIMATORS`` is 10,000 so the timed fit is the 10,000-tree run.
Holdout error is reported as MAE (gCO₂/kWh) and MSE.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.carbon_data import PANEL_COLUMNS, cache_path, model_frame, repo_root
from src.modeling import (
    DAY_AHEAD_CATEGORICAL,
    DAY_AHEAD_NUMERIC,
    TARGET,
    feature_matrix,
    score_predictions,
    train_test_split,
)

N_ESTIMATORS = 10_000
MAX_DEPTH = 6
LEARNING_RATE = 0.08


def cleaned_csv_path() -> Path:
    """Path of the 10,000-hour weather and carbon table."""
    return repo_root() / "data" / "processed" / "cleaned_weather_carbon.csv"


def panel_path() -> Path:
    """Prefer the cleaned 10,000-hour table, then the cached hourly panel."""
    cleaned = cleaned_csv_path()
    if cleaned.exists():
        return cleaned
    return cache_path()


def load_panel(path: Path | None = None) -> pd.DataFrame:
    """Read an hourly table and keep the columns the forecast is allowed to start from.

    Fuel megawatthour columns in the cleaned export are dropped here.

    Args:
        path: CSV to read. Defaults to ``panel_path``.

    Returns:
        Observations indexed by UTC hour, with ``PANEL_COLUMNS`` only.
    """
    path = panel_path() if path is None else path
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    missing = [column for column in PANEL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    return frame.loc[:, PANEL_COLUMNS].sort_index()


def _matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Day-ahead inputs. Hour and weekday stay integers the trees can split on."""
    matrix = feature_matrix(frame, DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC).copy()
    for column in DAY_AHEAD_CATEGORICAL:
        matrix[column] = matrix[column].astype(int)
    return matrix


def fit_xgb(train: pd.DataFrame, n_estimators: int = N_ESTIMATORS):
    """Fit XGBoost on the day-ahead columns.

    Args:
        train: Modeling table, including the target.
        n_estimators: Number of trees. The timed run uses 10,000.

    Returns:
        The fitted model and the fit time in seconds.
    """
    from xgboost import XGBRegressor

    model = XGBRegressor(
        n_estimators=n_estimators,
        max_depth=MAX_DEPTH,
        learning_rate=LEARNING_RATE,
        objective="reg:squarederror",
        tree_method="hist",
        n_jobs=-1,
        random_state=0,
        verbosity=0,
    )
    started = time.perf_counter()
    model.fit(_matrix(train), train[TARGET])
    return model, time.perf_counter() - started


def predict_xgb(model, frame: pd.DataFrame) -> np.ndarray:
    """Predict with a model from ``fit_xgb``, clipping intensity at zero."""
    return np.maximum(model.predict(_matrix(frame)), 0.0)


def run(n_estimators: int = N_ESTIMATORS, path: Path | None = None) -> dict[str, float | int | str]:
    """Fit on the training block and score the last 28 days.

    Args:
        n_estimators: Trees in the timed fit.
        path: Hourly CSV. Defaults to the cleaned table, then the cached panel.

    Returns:
        File, row counts, fit seconds, and holdout MAE and MSE.
    """
    path = panel_path() if path is None else path
    frame = model_frame(load_panel(path))
    train, test = train_test_split(frame)
    model, elapsed = fit_xgb(train, n_estimators=n_estimators)
    predicted = predict_xgb(model, test)
    scores = score_predictions(test[TARGET], predicted)
    residual = test[TARGET].to_numpy(dtype=float) - predicted
    return {
        "path": str(path),
        "rows": int(len(frame)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "n_estimators": int(n_estimators),
        "fit_seconds": float(elapsed),
        "mae": scores["mae"],
        "mse": float(np.mean(np.square(residual))),
    }


def main() -> None:
    """Print how long the 10,000-tree fit took and the holdout error."""
    result = run()
    print(f"file: {result['path']}")
    print(f"rows: {result['rows']}")
    print(f"train rows: {result['train_rows']}")
    print(f"test rows: {result['test_rows']}")
    print(f"trees: {result['n_estimators']}")
    print(f"fit seconds: {result['fit_seconds']:.2f}")
    print(f"holdout MAE g/kWh: {result['mae']:.3f}")
    print(f"holdout MSE: {result['mse']:.3f}")


if __name__ == "__main__":
    main()
