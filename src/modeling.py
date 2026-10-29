"""Splits, feature sets, and metrics shared by the carbon-intensity notebooks.

Every notebook forecasts ``carbon_intensity_g_per_kwh`` and scores a later
block of hours that was not used to choose settings. Feature lists here are
the only columns a model is allowed to see. Fuel generation is omitted because
the target is computed from it.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET = "carbon_intensity_g_per_kwh"
TEST_DAYS = 28
VAL_DAYS = 14
N_SPLITS = 4
RANDOM_STATE = 0

# Ingredients of the carbon formula, plus the target itself.
LEAKED_COLUMNS = frozenset(
    {
        "NG",
        "COL",
        "OIL",
        "SUN",
        "WND",
        "WAT",
        "NUC",
        "GEO",
        "OTH",
        "BAT",
        "PS",
        "gas_share",
        "solar_share",
        "wind_share",
        "generation_mwh",
        "net_generation_mwh",
        TARGET,
    }
)

HOUR_DOW = ["hour_local", "dow"]
SEASON = ["doy_sin", "doy_cos"]
HISTORY = ["carbon_lag_24", "carbon_lag_168"]
WEATHER_LAG = [
    "temp_lag_24",
    "radiation_lag_24",
    "radiation_fresno_lag_24",
    "wind_10m_lag_24",
]
DEMAND_FORECAST = ["demand_forecast_mwh"]
OBSERVED_NOW = ["temp", "radiation", "radiation_fresno", "wind_10m", "demand_mwh"]
PREVIOUS_HOUR = ["carbon_lag_1"]
CYCLICAL_CLOCK = ["hour_sin", "hour_cos", "dow_sin", "dow_cos"]

# Known the day before: calendar, last week of carbon, yesterday's weather, CAISO demand forecast.
DAY_AHEAD_CATEGORICAL = HOUR_DOW
DAY_AHEAD_NUMERIC = SEASON + HISTORY + WEATHER_LAG + DEMAND_FORECAST
CYCLICAL_NUMERIC = CYCLICAL_CLOCK + SEASON + HISTORY + WEATHER_LAG + DEMAND_FORECAST

# Held fixed outside the tree-structure search so notebooks differ by one choice.
TREE_PARAMS = {
    "learning_rate": 0.08,
    "max_depth": 6,
    "min_samples_leaf": 40,
    "max_iter": 300,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": RANDOM_STATE,
}


def check_features(columns: Sequence[str]) -> None:
    """Raise if a feature list includes the target or a fuel used to build it."""
    leaked = sorted(set(columns) & LEAKED_COLUMNS)
    if leaked:
        raise ValueError(f"features include the carbon formula: {leaked}")


def train_test_split(frame: pd.DataFrame, test_days: int = TEST_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the last ``test_days`` of the series.

    Args:
        frame: Modeling table sorted in time.
        test_days: Length of the final block. It is scored once.

    Returns:
        Train rows, then test rows. The two index ranges do not overlap.
    """
    cutoff = frame.index.max() - pd.Timedelta(days=test_days)
    train = frame.loc[frame.index < cutoff].copy()
    test = frame.loc[frame.index >= cutoff].copy()
    if train.empty or test.empty:
        raise ValueError("time split produced an empty side")
    if train.index.max() >= test.index.min():
        raise ValueError("train overlaps test")
    return train, test


def fit_validation_split(train: pd.DataFrame, val_days: int = VAL_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cut a validation tail from the training block for ensemble weights.

    The final test block is not used. Weights chosen here are applied once,
    after the specialists are refit on the whole training block.
    """
    cutoff = train.index.max() - pd.Timedelta(days=val_days)
    fit = train.loc[train.index < cutoff].copy()
    validation = train.loc[train.index >= cutoff].copy()
    if fit.empty or validation.empty:
        raise ValueError("validation split produced an empty side")
    return fit, validation


def feature_matrix(frame: pd.DataFrame, categorical: Sequence[str], numeric: Sequence[str]) -> pd.DataFrame:
    """Return model inputs in a stable column order and reject leaked fields."""
    columns = list(categorical) + list(numeric)
    check_features(columns)
    return frame.loc[:, columns]


def score_predictions(y_true, y_pred) -> dict[str, float]:
    """Mean absolute error and root mean squared error, in gCO₂/kWh.

    Predictions are clipped at zero because intensity cannot be negative.
    """
    actual = np.asarray(y_true, dtype=float)
    predicted = np.maximum(np.asarray(y_pred, dtype=float), 0.0)
    residual = actual - predicted
    return {
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(residual**2))),
    }


def hour_climatology(train: pd.DataFrame, when: pd.DataFrame) -> np.ndarray:
    """Predict each hour with the training mean for that local hour.

    This is the baseline the correlations support: most of the carbon shape
    is the time of day.
    """
    means = train.groupby("hour_local")[TARGET].mean()
    fallback = float(train[TARGET].mean())
    return means.reindex(when["hour_local"].to_numpy()).fillna(fallback).to_numpy()


def pinball_loss(y_true, y_pred, quantile: float) -> float:
    """Pinball loss for one quantile. Lower is better. The 0.5 quantile is half of MAE."""
    error = np.asarray(y_true, dtype=float) - np.maximum(np.asarray(y_pred, dtype=float), 0.0)
    loss = np.maximum(quantile * error, (quantile - 1.0) * error)
    return float(np.mean(loss))


def coverage(y_true, y_pred) -> float:
    """Share of hours whose actual intensity is at or below the prediction."""
    actual = np.asarray(y_true, dtype=float)
    predicted = np.maximum(np.asarray(y_pred, dtype=float), 0.0)
    return float(np.mean(actual <= predicted))


def result_row(name: str, y_true, y_pred, cv_mae: float | None = None, climatology_mae: float | None = None) -> dict:
    """One results-table row, including skill against the hour-of-day baseline."""
    scores = score_predictions(y_true, y_pred)
    row = {"model": name, "mae": scores["mae"], "rmse": scores["rmse"]}
    if cv_mae is not None:
        row["cv_mae"] = cv_mae
    if climatology_mae is not None and climatology_mae > 0:
        row["skill_vs_hour"] = 1.0 - scores["mae"] / climatology_mae
    return row


def linear_pipeline(estimator, categorical: Sequence[str], numeric: Sequence[str]) -> Pipeline:
    """One-hot encode the clock and scale the numeric inputs, then fit ``estimator``."""
    check_features(list(categorical) + list(numeric))
    transformers = []
    if list(categorical):
        transformers.append(
            ("cat", OneHotEncoder(drop="first", sparse_output=False), list(categorical))
        )
    if list(numeric):
        transformers.append(("num", StandardScaler(), list(numeric)))
    if not transformers:
        raise ValueError("linear pipeline needs at least one feature")
    return Pipeline([("pre", ColumnTransformer(transformers)), ("model", estimator)])


def cross_validated_mae(estimator, x_train: pd.DataFrame, y_train: pd.Series, n_splits: int = N_SPLITS) -> float:
    """Mean absolute error on forward folds inside the training block."""
    folds = []
    for train_index, valid_index in TimeSeriesSplit(n_splits=n_splits).split(x_train):
        model = clone(estimator)
        model.fit(x_train.iloc[train_index], y_train.iloc[train_index])
        predicted = model.predict(x_train.iloc[valid_index])
        folds.append(mean_absolute_error(y_train.iloc[valid_index], np.maximum(predicted, 0.0)))
    return float(np.mean(folds))


def search_time_series(estimator, param_grid: dict, x_train: pd.DataFrame, y_train: pd.Series, n_splits: int = N_SPLITS):
    """Grid search on forward folds. The score being minimized is MAE.

    ``best_score_`` is negative MAE, matching scikit-learn's convention.
    The returned search is already refit on all of ``x_train``.
    """
    def _clipped_neg_mae(estimator, features, target):
        predicted = np.maximum(estimator.predict(features), 0.0)
        return -mean_absolute_error(target, predicted)

    search = GridSearchCV(
        estimator,
        param_grid,
        cv=TimeSeriesSplit(n_splits=n_splits),
        scoring=_clipped_neg_mae,
        n_jobs=1,
        refit=True,
    )
    search.fit(x_train, y_train)
    return search


def make_tree(loss: str = "absolute_error", quantile: float | None = None, **overrides) -> HistGradientBoostingRegressor:
    """Build the shared tree model.

    Args:
        loss: ``squared_error``, ``absolute_error``, or ``quantile``.
        quantile: Required when ``loss`` is ``quantile``.
        overrides: Keys of ``TREE_PARAMS`` to change, used by the depth search.

    Returns:
        An unfitted histogram gradient boosting regressor. Hour and weekday
        are passed as categorical features at fit time.
    """
    params = dict(TREE_PARAMS)
    params.update(overrides)
    params["loss"] = loss
    if loss == "quantile":
        if quantile is None:
            raise ValueError("quantile loss needs a quantile between 0 and 1")
        params["quantile"] = quantile
    return HistGradientBoostingRegressor(**params)


def fit_tree(train: pd.DataFrame, categorical: Sequence[str], numeric: Sequence[str], loss: str = "absolute_error", quantile: float | None = None, **overrides):
    """Fit one tree model on a feature set. Hour and weekday stay categorical."""
    matrix = feature_matrix(train, categorical, numeric)
    model = make_tree(loss=loss, quantile=quantile, **overrides)
    categorical_features = [matrix.columns.get_loc(column) for column in categorical]
    model.set_params(categorical_features=categorical_features)
    model.fit(matrix, train[TARGET])
    return model


def predict_tree(model, frame: pd.DataFrame, categorical: Sequence[str], numeric: Sequence[str]) -> np.ndarray:
    """Predict with a tree fitted by ``fit_tree``, clipping at zero."""
    matrix = feature_matrix(frame, categorical, numeric)
    return np.maximum(model.predict(matrix), 0.0)


# A four-hour block is long enough to move a batch of work and short enough
# that "the clean part of the day" is a real choice on a solar-shaped grid.
SHIFT_HOURS = 4
# Fixed on purpose. Tuning belongs in a later pass.
RIDGE_ALPHA = 1.0


def clip_prediction(predicted) -> np.ndarray:
    """Carbon intensity cannot be negative."""
    return np.maximum(np.asarray(predicted, dtype=float), 0.0)


def error_components(y_true, y_pred) -> dict[str, float]:
    """Bias, MAE, and RMSE in gCO₂/kWh, plus the share of hours predicted too clean.

    Bias is prediction minus actual. A negative bias means the forecast said the
    grid was cleaner than it was, so a carbon report built from it would be low.
    """
    actual = np.asarray(y_true, dtype=float)
    predicted = clip_prediction(y_pred)
    residual = actual - predicted
    return {
        "bias": float(np.mean(predicted - actual)),
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "underpredicted_share": float(np.mean(residual > 0)),
    }


def shift_regret(actual, predicted, hours: int = SHIFT_HOURS) -> float:
    """Extra gCO₂/kWh from running in the predicted-clean hours.

    Regret is the actual intensity of the hours the forecast called cleanest,
    minus the actual intensity of the hours that really were cleanest. Zero
    means the forecast ranked the window correctly. A wrong level that keeps
    the same order has regret zero.

    Args:
        actual: Actual gCO₂/kWh for one day, one entry per hour.
        predicted: Forecast for those same hours.
        hours: How many hours the workload needs.

    Returns:
        Extra gCO₂/kWh. Non-negative aside from ties.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = clip_prediction(predicted)
    if len(actual) < hours:
        raise ValueError(f"need at least {hours} hours to score a shift")
    true_hours = np.argpartition(actual, hours - 1)[:hours]
    chosen_hours = np.argpartition(predicted, hours - 1)[:hours]
    return float(actual[chosen_hours].mean() - actual[true_hours].mean())


def shape_mae(actual, predicted) -> float:
    """MAE after each series has its own mean removed.

    This is the part of the error that is the shape of the day. A forecast that
    is 40 g/kWh too clean in every hour has shape MAE zero.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = clip_prediction(predicted)
    actual_shape = actual - actual.mean()
    predicted_shape = predicted - predicted.mean()
    return float(np.mean(np.abs(actual_shape - predicted_shape)))


def local_day_labels(frame: pd.DataFrame) -> pd.Series:
    """Calendar date in America/Los_Angeles for each row."""
    dates = frame.index.tz_convert("America/Los_Angeles").date
    return pd.Series(dates, index=frame.index, name="local_day")


def _rank_correlation(actual: np.ndarray, predicted: np.ndarray) -> float:
    if np.unique(actual).size < 2 or np.unique(predicted).size < 2:
        return float("nan")
    return float(pd.Series(actual).corr(pd.Series(predicted), method="spearman"))


def day_scores(frame: pd.DataFrame, predicted, hours: int = SHIFT_HOURS) -> pd.DataFrame:
    """One row per complete local day: level, shape, MAE, RMSE, and shift regret.

    Days with fewer than 24 hours are omitted. The holdout starts and ends
    mid-afternoon Pacific, so the first and last dates are partial.
    """
    labels = local_day_labels(frame)
    actual_all = frame[TARGET].to_numpy(dtype=float)
    predicted_all = clip_prediction(predicted)
    rows = []
    for day in pd.unique(labels):
        chosen = np.flatnonzero(labels.to_numpy() == day)
        if len(chosen) != 24:
            continue
        actual = actual_all[chosen]
        forecast = predicted_all[chosen]
        residual = actual - forecast
        rows.append(
            {
                "local_day": day,
                "actual_mean": float(actual.mean()),
                "predicted_mean": float(forecast.mean()),
                "level_error": float(forecast.mean() - actual.mean()),
                "mae": float(np.mean(np.abs(residual))),
                "rmse": float(np.sqrt(np.mean(np.square(residual)))),
                "shape_mae": shape_mae(actual, forecast),
                "regret_4h": shift_regret(actual, forecast, hours),
                "regret_1h": shift_regret(actual, forecast, 1),
                "rank_corr": _rank_correlation(actual, forecast),
            }
        )
    return pd.DataFrame(rows)


def fixed_forecasts(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    """The same five forecasts in every notebook. Nothing here is tuned.

    Ridge uses penalty 1. The tree uses ``TREE_PARAMS`` and absolute error.
    Both see only day-ahead columns. ``previous hour`` is the bound on how
    much of the miss is just issuing the forecast a day early.
    """
    from sklearn.linear_model import Ridge

    forecasts = {
        "hour-of-day mean": hour_climatology(train, test),
        "yesterday, same hour": clip_prediction(test["carbon_lag_24"].to_numpy()),
    }
    ridge = linear_pipeline(Ridge(alpha=RIDGE_ALPHA), DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC)
    ridge.fit(feature_matrix(train, DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC), train[TARGET])
    forecasts["day-ahead ridge"] = clip_prediction(
        ridge.predict(feature_matrix(test, DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC))
    )
    tree = fit_tree(train, DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC, loss="absolute_error")
    forecasts["day-ahead tree"] = predict_tree(tree, test, DAY_AHEAD_CATEGORICAL, DAY_AHEAD_NUMERIC)
    next_numeric = DAY_AHEAD_NUMERIC + PREVIOUS_HOUR
    next_model = linear_pipeline(Ridge(alpha=RIDGE_ALPHA), HOUR_DOW, next_numeric)
    next_model.fit(feature_matrix(train, HOUR_DOW, next_numeric), train[TARGET])
    forecasts["previous hour"] = clip_prediction(next_model.predict(feature_matrix(test, HOUR_DOW, next_numeric)))
    return forecasts
