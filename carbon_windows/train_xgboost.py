"""Tune XGBoost on hourly CAISO carbon intensity.

Optuna minimizes mean absolute error, in grams of CO₂ per kilowatt-hour,
on forward folds inside the training block. The trees learn how much the
hour differs from the same hour yesterday, and yesterday is added back. The last 56 days are scored
once, after the winner is chosen. Train and test both report that MAE and
the percent error. The test report also includes 4-hour shift regret,
because a small gram error can still pick the wrong hours to run a job.

    python -m carbon_windows.train_xgboost
    python -m carbon_windows.train_xgboost --minutes 10
"""

from __future__ import annotations

import argparse
import json
import time

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from carbon_windows.build_dataset import TARGET, dataset_path, meta_path
from src.forecast_data import TEST_DAYS
from src.modeling import SHIFT_HOURS, local_day_labels, shift_regret
from src.tune_xgboost import EARLY_STOPPING_ROUNDS, SEED, STARTUP_TRIALS, _suggest

UNIT = "gCO2/kWh"
CV_SPLITS = 3


def _load() -> tuple[pd.DataFrame, list[str]]:
    path = dataset_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Build it with: python -m carbon_windows.build_dataset")
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    features = list(json.loads(meta_path().read_text())["features"])
    missing = [column for column in [TARGET, *features] if column not in frame.columns]
    if missing:
        raise ValueError(f"carbon dataset is missing columns: {missing}")
    return frame.sort_index(), features


def _split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = frame.index.max() - pd.Timedelta(days=TEST_DAYS)
    train = frame.loc[frame.index <= cutoff]
    test = frame.loc[frame.index > cutoff]
    if train.empty or test.empty or train.index.max() >= test.index.min():
        raise RuntimeError("the 56-day split did not separate train from test")
    return train, test


def _percent(actual, predicted) -> dict[str, float]:
    """Mean and median absolute percent error. Hours at zero intensity are left out of the ratio."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.maximum(np.asarray(predicted, dtype=float), 0.0)
    usable = actual > 0
    ratio = 100.0 * np.abs(actual[usable] - predicted[usable]) / actual[usable]
    return {"percent_error_mean": float(np.mean(ratio)), "percent_error_median": float(np.median(ratio))}


def _errors(actual, predicted) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.maximum(np.asarray(predicted, dtype=float), 0.0)
    residual = actual - predicted
    return {
        "mae_g_per_kwh": float(np.mean(np.abs(residual))),
        "rmse_g_per_kwh": float(np.sqrt(np.mean(np.square(residual)))),
        **_percent(actual, predicted),
    }


def _regret(frame: pd.DataFrame, predicted) -> float | None:
    """Mean 4-hour shift regret over complete Pacific days, in g/kWh."""
    labels = local_day_labels(frame)
    actual = frame[TARGET].to_numpy(dtype=float)
    forecast = np.maximum(np.asarray(predicted, dtype=float), 0.0)
    rows = []
    for day in pd.unique(labels):
        chosen = np.flatnonzero(labels.to_numpy() == day)
        if len(chosen) != 24:
            continue
        rows.append(shift_regret(actual[chosen], forecast[chosen], SHIFT_HOURS))
    if not rows:
        return None
    return float(np.mean(rows))


def _hour_of_day(train: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """The training mean of carbon at that Pacific hour."""
    local_train = train.index.tz_convert("America/Los_Angeles").hour
    local_frame = frame.index.tz_convert("America/Los_Angeles").hour
    means = train[TARGET].groupby(local_train).mean()
    fallback = float(train[TARGET].mean())
    return means.reindex(local_frame).fillna(fallback).to_numpy()


LAG = "carbon_lag_24"


def predict_intensity(saved: dict, frame: pd.DataFrame) -> np.ndarray:
    """Grams per kWh. The model learns the change from yesterday, then yesterday is added back."""
    delta = saved["model"].predict(frame.loc[:, saved["features"]].astype(float))
    lag = frame[saved.get("residual_of", LAG)].to_numpy(dtype=float)
    return np.maximum(lag + delta, 0.0)


def _fit_fold(params: dict, x_fit, y_fit, x_valid, y_valid, lag_valid) -> tuple[float, int]:
    model = XGBRegressor(
        **params,
        tree_method="hist",
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        eval_metric="mae",
        n_jobs=-1,
        random_state=SEED,
        verbosity=0,
    )
    model.fit(x_fit, y_fit, eval_set=[(x_valid, y_valid)], verbose=False)
    level = np.maximum(np.asarray(lag_valid, dtype=float) + model.predict(x_valid), 0.0)
    actual = np.asarray(y_valid, dtype=float) + np.asarray(lag_valid, dtype=float)
    return float(np.mean(np.abs(actual - level))), int(model.best_iteration) + 1


def train(n_trials: int = 40, timeout: float | None = None) -> dict:
    """Search on the training block, refit the winner, and score train and test."""
    frame, features = _load()
    # Yesterday's carbon is added back after the model runs, so it is not also a column.
    model_features = [column for column in features if column != LAG]
    train_frame, test_frame = _split(frame)
    x_train = train_frame.loc[:, model_features].astype(float)
    y_train = train_frame[TARGET] - train_frame[LAG]
    lag_train = train_frame[LAG]
    folds = list(TimeSeriesSplit(n_splits=CV_SPLITS).split(x_train))
    print(f"target: {TARGET} ({UNIT})")
    print(f"TRAIN: {len(train_frame)} hours, {train_frame.index.min()} -> {train_frame.index.max()}")
    print(f"TEST:  {len(test_frame)} hours, {test_frame.index.min()} -> {test_frame.index.max()}")

    def objective(trial: optuna.Trial) -> float:
        params = _suggest(trial, quick=False)
        errors = []
        trees = []
        for step, (fit_index, valid_index) in enumerate(folds):
            error, stopped_at = _fit_fold(
                params,
                x_train.iloc[fit_index],
                y_train.iloc[fit_index],
                x_train.iloc[valid_index],
                y_train.iloc[valid_index],
                lag_train.iloc[valid_index],
            )
            errors.append(error)
            trees.append(stopped_at)
            trial.report(float(np.mean(errors)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()
        trial.set_user_attr("trees", int(round(float(np.mean(trees)))))
        return float(np.mean(errors))

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=SEED, n_startup_trials=min(STARTUP_TRIALS, n_trials), multivariate=True),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=min(STARTUP_TRIALS, n_trials), n_warmup_steps=1),
    )
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    started = time.perf_counter()
    study.optimize(objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)
    search_seconds = time.perf_counter() - started

    best = dict(study.best_params)
    best["n_estimators"] = int(study.best_trial.user_attrs.get("trees", best["n_estimators"]))
    model = XGBRegressor(**best, tree_method="hist", n_jobs=-1, random_state=SEED, verbosity=0)
    model.fit(x_train, y_train, verbose=False)
    saved = {"model": model, "features": model_features, "residual_of": LAG, "target": TARGET, "unit": UNIT}
    train_pred = predict_intensity(saved, train_frame)
    test_pred = predict_intensity(saved, test_frame)

    model_path = dataset_path().parent / "model.joblib"
    joblib.dump(saved, model_path)

    def side(name: str, actual, predicted) -> dict:
        return {"name": name, **_errors(actual, predicted)}

    yesterday = test_frame["carbon_lag_24"].to_numpy(dtype=float)
    by_hour = _hour_of_day(train_frame, test_frame)
    metrics = {
        "target": TARGET,
        "unit": UNIT,
        "location": "CISO",
        "trials": int(len(study.trials)),
        "best_params": best,
        "cv_mae_g_per_kwh": float(study.best_value),
        "search_seconds": float(search_seconds),
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "train_end": str(train_frame.index.max()),
        "test_start": str(test_frame.index.min()),
        "train": _errors(train_frame[TARGET], train_pred),
        "test": _errors(test_frame[TARGET], test_pred),
        "test_regret_4h_g_per_kwh": _regret(test_frame, test_pred),
        "baselines_test": [
            side("same hour yesterday", test_frame[TARGET], yesterday),
            side("hour of day mean", test_frame[TARGET], by_hour),
        ],
        "baseline_regret_4h_g_per_kwh": {
            "same hour yesterday": _regret(test_frame, yesterday),
            "hour of day mean": _regret(test_frame, by_hour),
        },
        "model_path": str(model_path),
    }
    out = dataset_path().parent / "metrics.json"
    out.write_text(json.dumps(metrics, indent=2))
    _print(metrics)
    print(f"wrote {out}")
    print(f"wrote {model_path}")
    return metrics


def _print(metrics: dict) -> None:
    print(f"search: {metrics['trials']} trials, {metrics['search_seconds']:.0f} s, CV MAE {metrics['cv_mae_g_per_kwh']:.2f} {UNIT}")
    for name in ("train", "test"):
        row = metrics[name]
        print(
            f"{name}: MAE {row['mae_g_per_kwh']:.2f} {UNIT}, "
            f"percent error mean {row['percent_error_mean']:.2f}% median {row['percent_error_median']:.2f}%, "
            f"RMSE {row['rmse_g_per_kwh']:.2f}"
        )
    print(f"test 4-hour regret: {metrics['test_regret_4h_g_per_kwh']:.2f} {UNIT}")
    for row in metrics["baselines_test"]:
        print(
            f"baseline {row['name']}: MAE {row['mae_g_per_kwh']:.2f} {UNIT}, "
            f"percent error mean {row['percent_error_mean']:.2f}% median {row['percent_error_median']:.2f}%"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune XGBoost on CAISO carbon intensity.")
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--minutes", type=float, default=None, help="stop the search after this many minutes")
    args = parser.parse_args()
    n_trials = args.trials if args.minutes is None else max(args.trials, 10_000)
    timeout = None if args.minutes is None else args.minutes * 60
    train(n_trials=n_trials, timeout=timeout)


if __name__ == "__main__":
    main()
