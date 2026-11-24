"""Tune XGBoost on day-ahead prices at the P-nodes next to each campus.

Optuna minimizes mean absolute error, in dollars per megawatt-hour, on
forward folds inside the training block. A fold cuts on the timestamp, so
every campus and node at one hour stays on the same side. The last 28 days
are scored once, after the winner is chosen. Predictions are not clipped:
a negative price is a real CAISO hour.

    python -m price_windows.train_xgboost
    python -m price_windows.train_xgboost --minutes 10
"""

from __future__ import annotations

import atexit
import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from price_windows.build_dataset import dataset_path, meta_path
from price_windows.schema import LOCAL_TZ, PERCENT_PRICE_FLOOR, TARGET, TEST_DAYS, illegal_feature_names
from src.tune_xgboost import EARLY_STOPPING_ROUNDS, SEED, STARTUP_TRIALS, _suggest

UNIT = "$/MWh"
CV_SPLITS = 3
# Same length the carbon model uses for a shift. The cheapest hours need not be contiguous.
SHIFT_HOURS = 4
LAG_168 = "lmp_lag_168"
BASELINE_WEEK = "same hour last week"
BASELINE_HOUR = "hour of week mean"
# Extra trees when continuing a saved booster. This is not an Optuna search.
UPDATE_TREES = 20


def predict_price(saved: dict, frame: pd.DataFrame) -> np.ndarray:
    """Day-ahead price in dollars per megawatt-hour.

    A negative price is a real CAISO hour, so the numbers are not clipped.
    """
    predicted = saved["model"].predict(frame.loc[:, saved["features"]].astype(float))
    return np.asarray(predicted, dtype=float)


def _load() -> tuple[pd.DataFrame, list[str], dict]:
    path = dataset_path()
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Build it with: python -m price_windows.build_dataset")
    frame = pd.read_csv(path, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.isna().any():
        raise ValueError("the price dataset index is not a UTC hour")
    meta = json.loads(meta_path().read_text())
    return frame.sort_index(kind="mergesort"), list(meta["features"]), meta


def _refuse(features: list[str]) -> None:
    leaked = illegal_feature_names(features)
    if leaked:
        raise ValueError(f"features leak the price or a component of it: {leaked}")


def _require_columns(frame: pd.DataFrame, features: list[str]) -> None:
    needed = [TARGET, LAG_168, "campus_id", "pnode_id", *features]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise ValueError(f"price dataset is missing columns: {missing}")


def _split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out the last 28 days. An hour is entirely train or entirely test."""
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("price dataset rows must be indexed by the UTC hour")
    cutoff = frame.index.max() - pd.Timedelta(days=TEST_DAYS)
    train = frame.loc[frame.index <= cutoff]
    test = frame.loc[frame.index > cutoff]
    if train.empty or test.empty or train.index.max() >= test.index.min():
        raise RuntimeError("the 28-day split did not separate train from test")
    if set(train.index) & set(test.index):
        raise RuntimeError("the 28-day split put one hour on both sides")
    return train, test


def _folds(index: pd.DatetimeIndex, n_splits: int = CV_SPLITS) -> list[tuple[np.ndarray, np.ndarray]]:
    """Forward folds on the distinct hours, so every node at one hour shares a side."""
    index = pd.DatetimeIndex(index)
    unique = pd.DatetimeIndex(index.unique()).sort_values()
    if len(unique) <= n_splits:
        raise ValueError(f"need more than {n_splits} distinct hours for {n_splits} forward folds")
    folds = []
    for fit_pos, valid_pos in TimeSeriesSplit(n_splits=n_splits).split(np.zeros((len(unique), 1))):
        fit_times = unique[fit_pos]
        valid_times = unique[valid_pos]
        if fit_times.max() >= valid_times.min() or set(fit_times) & set(valid_times):
            raise RuntimeError("a forward fold put one hour on both sides")
        fit_rows = np.flatnonzero(index.isin(fit_times))
        valid_rows = np.flatnonzero(index.isin(valid_times))
        folds.append((fit_rows, valid_rows))
    return folds


def _percent(actual, predicted) -> dict[str, float | None]:
    """Mean and median absolute percent error on hours priced above 5 $/MWh."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    usable = actual > PERCENT_PRICE_FLOOR
    if not np.any(usable):
        return {"percent_error_mean": None, "percent_error_median": None}
    ratio = 100.0 * np.abs(actual[usable] - predicted[usable]) / actual[usable]
    return {"percent_error_mean": float(np.mean(ratio)), "percent_error_median": float(np.median(ratio))}


def _errors(actual, predicted) -> dict[str, float | None]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    residual = actual - predicted
    return {
        "mae_usd_per_mwh": float(np.mean(np.abs(residual))),
        "rmse_usd_per_mwh": float(np.sqrt(np.mean(np.square(residual)))),
        **_percent(actual, predicted),
    }


def _shift_regret(actual, predicted, hours: int = SHIFT_HOURS) -> float:
    """Extra $/MWh from running the hours the forecast called cheapest.

    A negative forecast stays negative, so a below-zero hour can still be the
    one the model picks.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) < hours:
        raise ValueError(f"need at least {hours} hours to score a shift")
    true_hours = np.argpartition(actual, hours - 1)[:hours]
    chosen_hours = np.argpartition(predicted, hours - 1)[:hours]
    return float(actual[chosen_hours].mean() - actual[true_hours].mean())


def _regret(frame: pd.DataFrame, predicted) -> float | None:
    """4-hour shift regret on complete Pacific days, averaged across nodes."""
    predicted = np.asarray(predicted, dtype=float)
    actual = frame[TARGET].to_numpy(dtype=float)
    days = np.asarray(frame.index.tz_convert(LOCAL_TZ).date)
    keys = frame["campus_id"].astype(str).to_numpy() + "\t" + frame["pnode_id"].astype(str).to_numpy()
    per_node = []
    for key in pd.unique(keys):
        node_rows = np.flatnonzero(keys == key)
        node_days = days[node_rows]
        regrets = []
        for day in pd.unique(node_days):
            rows = node_rows[node_days == day]
            if len(rows) != 24 or len(set(frame.index[rows])) != 24:
                continue
            regrets.append(_shift_regret(actual[rows], predicted[rows], SHIFT_HOURS))
        if regrets:
            per_node.append(float(np.mean(regrets)))
    if not per_node:
        return None
    return float(np.mean(per_node))


def _hour_of_week(train: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """The training mean of price at that Pacific hour-of-week."""

    def _key(index: pd.DatetimeIndex) -> np.ndarray:
        local = index.tz_convert(LOCAL_TZ)
        return local.dayofweek.to_numpy() * 24 + local.hour.to_numpy()

    means = pd.Series(train[TARGET].to_numpy(dtype=float)).groupby(_key(train.index)).mean()
    fallback = float(train[TARGET].mean())
    return pd.Series(_key(frame.index)).map(means).fillna(fallback).to_numpy(dtype=float)


def _release_workers() -> None:
    """Stop leftover joblib workers before the interpreter exits.

    A multi-core fit leaves loky semaphores behind. Python then prints
    ``Exception ignored`` and ``leaked semaphore`` while it shuts down.
    This does not start a pool when none is running.
    """
    try:
        from joblib.externals.loky import reusable_executor
    except Exception:
        return
    executor = getattr(reusable_executor, "_executor", None)
    if executor is None:
        return
    try:
        executor.shutdown(wait=True, kill_workers=True)
    except TypeError:
        try:
            executor.shutdown(wait=True)
        except Exception:
            return
    except Exception:
        return


def _fit_fold(params: dict, x_fit, y_fit, x_valid, y_valid, jobs: int) -> tuple[float, int]:
    """Fit one fold, stop early on MAE, and return that MAE and the tree it stopped at."""
    model = XGBRegressor(
        **params,
        tree_method="hist",
        early_stopping_rounds=EARLY_STOPPING_ROUNDS,
        eval_metric="mae",
        n_jobs=jobs,
        random_state=SEED,
        verbosity=0,
    )
    model.fit(x_fit, y_fit, eval_set=[(x_valid, y_valid)], verbose=False)
    predicted = np.asarray(model.predict(x_valid), dtype=float)
    actual = np.asarray(y_valid, dtype=float)
    best = getattr(model, "best_iteration", None)
    trees = int(params["n_estimators"]) if best is None else int(best) + 1
    return float(np.mean(np.abs(actual - predicted))), trees


def _plain(value):
    if isinstance(value, np.generic):
        return value.item()
    return value


def train(
    n_trials: int = 40,
    timeout: float | None = None,
    *,
    frame: pd.DataFrame | None = None,
    features: list[str] | None = None,
    output_dir: Path | None = None,
    quick: bool = False,
) -> dict:
    """Search on the training block, refit the winner, and score train and test.

    The last 28 days are the test block. They are scored once and never used
    to pick a setting. Optuna's score is mean absolute error in $/MWh.
    """
    if frame is None:
        frame, features, meta = _load()
    elif features is None:
        raise ValueError("features are required when a frame is passed in")
    else:
        meta = {}
        frame = frame.sort_index(kind="mergesort")
    _refuse(features)
    if not features:
        raise ValueError("the price dataset has no features")
    _require_columns(frame, features)
    train_frame, test_frame = _split(frame)
    x_train = train_frame.loc[:, features].astype(float)
    y_train = train_frame[TARGET].astype(float)
    folds = _folds(train_frame.index)
    # One core on the short test path. The real search still uses every core,
    # then _release_workers stops those processes before Python exits.
    jobs = 1 if quick else -1
    print(f"target: {TARGET} ({UNIT})")
    print(f"TRAIN: {len(train_frame)} rows, {train_frame.index.min()} -> {train_frame.index.max()}")
    print(f"TEST:  {len(test_frame)} rows, {test_frame.index.min()} -> {test_frame.index.max()}")

    def objective(trial: optuna.Trial) -> float:
        params = _suggest(trial, quick)
        errors = []
        trees = []
        for step, (fit_index, valid_index) in enumerate(folds):
            error, stopped_at = _fit_fold(
                params,
                x_train.iloc[fit_index],
                y_train.iloc[fit_index],
                x_train.iloc[valid_index],
                y_train.iloc[valid_index],
                jobs,
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

    best = {key: _plain(value) for key, value in study.best_params.items()}
    best["n_estimators"] = int(study.best_trial.user_attrs.get("trees", best["n_estimators"]))
    model = XGBRegressor(**best, tree_method="hist", n_jobs=jobs, random_state=SEED, verbosity=0)
    model.fit(x_train, y_train, verbose=False)
    saved = {"model": model, "features": list(features), "target": TARGET, "unit": UNIT}
    train_pred = predict_price(saved, train_frame)
    test_pred = predict_price(saved, test_frame)

    out_dir = dataset_path().parent if output_dir is None else Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    joblib.dump(saved, model_path)

    def side(name: str, actual, predicted) -> dict:
        return {"name": name, **_errors(actual, predicted)}

    week = test_frame[LAG_168].to_numpy(dtype=float)
    by_hour = _hour_of_week(train_frame, test_frame)
    metrics = {
        "target": TARGET,
        "unit": UNIT,
        "test_days": TEST_DAYS,
        "percent_error_min_price_usd_per_mwh": PERCENT_PRICE_FLOOR,
        "clipped_at_zero": False,
        "trials": int(len(study.trials)),
        "pruned_trials": int(sum(trial.state == optuna.trial.TrialState.PRUNED for trial in study.trials)),
        "best_params": best,
        "cv_mae_usd_per_mwh": float(study.best_value),
        "search_seconds": float(search_seconds),
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "train_end": str(train_frame.index.max()),
        "test_start": str(test_frame.index.min()),
        "dataset_hash": meta.get("content_hash"),
        "train": _errors(y_train, train_pred),
        "test": _errors(test_frame[TARGET], test_pred),
        "test_regret_4h_usd_per_mwh": _regret(test_frame, test_pred),
        "baselines_test": [
            side(BASELINE_WEEK, test_frame[TARGET], week),
            side(BASELINE_HOUR, test_frame[TARGET], by_hour),
        ],
        "baseline_regret_4h_usd_per_mwh": {
            BASELINE_WEEK: _regret(test_frame, week),
            BASELINE_HOUR: _regret(test_frame, by_hour),
        },
        "model_path": str(model_path),
    }
    out = out_dir / "metrics.json"
    out.write_text(json.dumps(metrics, indent=2))
    _print(metrics)
    print(f"wrote {out}")
    print(f"wrote {model_path}")
    _release_workers()
    return metrics


def update_model(saved: dict, frame: pd.DataFrame, output_path: Path, extra_trees: int = UPDATE_TREES) -> dict:
    """Continue the saved booster on ``frame`` only.

    ``n_estimators`` on this fit is the number of new trees. Optuna does not
    run. The file at ``output_path`` is the only model written. The morning
    job does not call this.
    """
    features = list(saved["features"])
    _refuse(features)
    if extra_trees < 1:
        raise ValueError("extra_trees must be at least 1")
    if frame.empty:
        raise ValueError("there are no new rows to continue from")
    _require_columns(frame, features)
    model = saved["model"]
    model.set_params(n_estimators=int(extra_trees), n_jobs=1)
    try:
        model.fit(
            frame.loc[:, features].astype(float),
            frame[TARGET].astype(float),
            xgb_model=model.get_booster(),
            verbose=False,
        )
        updated = {"model": model, "features": features, "target": TARGET, "unit": UNIT}
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(updated, destination)
    finally:
        _release_workers()
    return updated


def continue_saved_model() -> None:
    """Fit rows after the saved training end. Does not run the 40-trial search.

    A full Optuna search stays manual. This reads the modeling table only to
    slice the new rows, and it refuses to fit the table when that cutoff is
    missing or the saved feature list no longer matches.
    """
    root = dataset_path().parent
    model_path = root / "model.joblib"
    if not model_path.exists():
        raise SystemExit(
            "price_windows/model.joblib is missing. --update-model does not search and does not train from scratch."
        )
    saved = joblib.load(model_path)
    frame, features, _meta = _load()
    if list(saved.get("features", [])) != list(features):
        raise SystemExit(
            "The saved model features differ from price_dataset.meta.json. "
            "A full Optuna search is manual. --update-model will not retune."
        )
    metrics_path = root / "metrics.json"
    if not metrics_path.exists():
        raise SystemExit("metrics.json is missing, so the new-row cutoff is unknown. A full search is manual.")
    metrics = json.loads(metrics_path.read_text())
    if not metrics.get("train_end"):
        raise SystemExit("metrics.json has no train_end. Refusing to fit the whole table.")
    cutoff = pd.Timestamp(metrics["train_end"])
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    new_rows = frame.loc[frame.index > cutoff]
    if new_rows.empty:
        print("no rows after the saved training end; model left unchanged")
        return
    print(f"continuing on {len(new_rows)} rows after {cutoff}")
    update_model(saved, new_rows, model_path)


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _print(metrics: dict) -> None:
    print(
        f"search: {metrics['trials']} trials, {metrics['search_seconds']:.0f} s, "
        f"CV MAE {metrics['cv_mae_usd_per_mwh']:.2f} {UNIT}"
    )
    for name in ("train", "test"):
        row = metrics[name]
        print(
            f"{name}: MAE {row['mae_usd_per_mwh']:.2f} {UNIT}, "
            f"RMSE {row['rmse_usd_per_mwh']:.2f}, "
            f"percent error mean {_fmt(row['percent_error_mean'])} median {_fmt(row['percent_error_median'])}"
        )
    regret = metrics["test_regret_4h_usd_per_mwh"]
    if regret is None:
        print("test 4-hour regret: no complete Pacific day")
    else:
        print(f"test 4-hour regret: {regret:.2f} {UNIT}")
    for row in metrics["baselines_test"]:
        print(
            f"baseline {row['name']}: MAE {row['mae_usd_per_mwh']:.2f} {UNIT}, "
            f"percent error mean {_fmt(row['percent_error_mean'])} median {_fmt(row['percent_error_median'])}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune XGBoost on CAISO day-ahead P-node prices.")
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--minutes", type=float, default=None, help="stop the search after this many minutes")
    parser.add_argument(
        "--update-model",
        action="store_true",
        help="continue the saved booster on rows after metrics.json train_end; does not run Optuna",
    )
    args = parser.parse_args()
    if args.update_model:
        continue_saved_model()
        return
    n_trials = args.trials if args.minutes is None else max(args.trials, 10_000)
    timeout = None if args.minutes is None else args.minutes * 60
    train(n_trials=n_trials, timeout=timeout)


atexit.register(_release_workers)


if __name__ == "__main__":
    main()
