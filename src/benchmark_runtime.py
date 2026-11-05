"""Time training the tuned XGBoost model as the history gets longer.

Two clocks are measured, both with the settings in ``results/xgb_optuna.json``.

- A retrain is one fit of all 945 trees on the whole training block.
- A tuner trial is what Optuna does for one candidate: three forward folds,
  each fit with early stopping. The last search ran 44 of these.

History lengths of 2, 4, 6, and 7.7 years are real slices of the EIA table.
Ten and fifteen years repeat those hours until the table is that long, so
the clock time is real. The extra rows are not new years of grid data.
EIA hourly CAISO demand starts in 2019.

    python -m src.benchmark_runtime
"""

from __future__ import annotations

import json
import platform
import resource
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from src.carbon_data import repo_root
from src.forecast_data import CV_SPLITS, TARGET, features, score, train_test_hours

HOURS_PER_YEAR = 365.25 * 24
REPEATS = 3
REAL_YEARS = (2, 4, 6)
LONG_YEARS = (10, 15)
# How many candidates the last search scored, and the default search size.
SEARCH_TRIALS = (44, 80)
EARLY_STOPPING_ROUNDS = 40


def _saved() -> tuple[dict, int]:
    """Saved settings, and how many candidates the last search actually scored."""
    record = json.loads((repo_root() / "results" / "xgb_optuna.json").read_text())
    params = dict(record["best_params"])
    params["n_estimators"] = int(params["n_estimators"])
    params["max_depth"] = int(params["max_depth"])
    return params, int(record["trials"])


def _model(params: dict, early_stopping: bool) -> XGBRegressor:
    stopping = {"early_stopping_rounds": EARLY_STOPPING_ROUNDS, "eval_metric": "mae"} if early_stopping else {}
    return XGBRegressor(**params, **stopping, tree_method="hist", n_jobs=-1, random_state=0, verbosity=0)


def _rows(frame: pd.DataFrame, target: pd.Series, count: int) -> tuple[pd.DataFrame, pd.Series]:
    """The last ``count`` hours, repeating the table if it is shorter than ``count``."""
    if count <= len(frame):
        return frame.iloc[-count:].reset_index(drop=True), target.iloc[-count:].reset_index(drop=True)
    copies = int(np.ceil(count / len(frame)))
    return (
        pd.concat([frame] * copies, ignore_index=True).iloc[:count],
        pd.concat([target] * copies, ignore_index=True).iloc[:count],
    )


def _peak_mb() -> float:
    """Highest resident memory of this process so far, in megabytes."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / 1e6 if platform.system() == "Darwin" else rss / 1e3


def _clock(function) -> dict:
    """Wall time, CPU time, and peak memory for one call."""
    cpu_before = time.process_time()
    started = time.perf_counter()
    function()
    return {
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_before,
        "peak_mb": _peak_mb(),
    }


def _summary(values: list[float]) -> dict:
    array = np.asarray(values, dtype=float)
    return {
        "mean": float(array.mean()),
        "std": float(array.std(ddof=1)) if len(array) > 1 else 0.0,
        "min": float(array.min()),
        "max": float(array.max()),
        "n": int(len(array)),
    }


def _retrain(x, y, params: dict) -> None:
    _model(params, early_stopping=False).fit(x, y, verbose=False)


def _trial(x, y, params: dict) -> None:
    """Three forward folds, each allowed to stop early. This is one Optuna candidate."""
    for fit_index, valid_index in TimeSeriesSplit(n_splits=CV_SPLITS).split(x):
        model = _model(params, early_stopping=True)
        model.fit(
            x.iloc[fit_index],
            y.iloc[fit_index],
            eval_set=[(x.iloc[valid_index], y.iloc[valid_index])],
            verbose=False,
        )
        score(y.iloc[valid_index], np.maximum(model.predict(x.iloc[valid_index]), 0.0))


def _measure(x, y, params: dict, count: int, repeated: bool) -> dict:
    block_x, block_y = _rows(x, y, count)
    retrains = [_clock(lambda: _retrain(block_x, block_y, params)) for _ in range(REPEATS)]
    trials = [_clock(lambda: _trial(block_x, block_y, params)) for _ in range(REPEATS)]
    row = {
        "rows": count,
        "years": count / HOURS_PER_YEAR,
        "repeated_hours": repeated,
        "retrain_seconds": _summary([item["wall_seconds"] for item in retrains]),
        "retrain_cpu_seconds": _summary([item["cpu_seconds"] for item in retrains]),
        "trial_seconds": _summary([item["wall_seconds"] for item in trials]),
        "trial_cpu_seconds": _summary([item["cpu_seconds"] for item in trials]),
        "peak_mb": max(item["peak_mb"] for item in retrains + trials),
    }
    print(
        f"{row['years']:5.2f} y  {count:7d} rows  "
        f"retrain {row['retrain_seconds']['mean']:6.1f} s  "
        f"one search trial {row['trial_seconds']['mean']:6.1f} s"
        f"{'  (hours repeated)' if repeated else ''}"
    )
    return row


def run() -> dict:
    """Train at each history length and write ``results/runtime.json``."""
    params, trials_run = _saved()
    train, _ = train_test_hours()
    x_all = features(train)
    y_all = train[TARGET]
    available = len(x_all)
    lengths = [min(available, int(years * HOURS_PER_YEAR)) for years in REAL_YEARS]
    lengths.append(available)
    lengths.extend(int(years * HOURS_PER_YEAR) for years in LONG_YEARS)

    print(f"training benchmark, {REPEATS} repeats, {params['n_estimators']} trees")
    measured = [_measure(x_all, y_all, params, count, count > available) for count in lengths]

    def scale(row: dict, trials: int) -> dict:
        return {
            "years": row["years"],
            "rows": row["rows"],
            "repeated_hours": row["repeated_hours"],
            "trials": trials,
            "minutes": row["trial_seconds"]["mean"] * trials / 60,
        }

    report = {
        "machine": platform.platform(),
        "processor": platform.processor(),
        "repeats": REPEATS,
        "trees": params["n_estimators"],
        "folds_per_trial": CV_SPLITS,
        "training": measured,
        "full_search_minutes": [scale(row, count) for row in measured for count in (trials_run, *SEARCH_TRIALS)],
        "notes": [
            "Retrain is one fit of every tree on that many hours.",
            "A search trial is three forward folds with early stopping, which is one Optuna candidate.",
            "Ten and fifteen years repeat the real hours so the training time can be measured. They are not extra EIA history.",
        ],
    }
    out = repo_root() / "results" / "runtime.json"
    out.write_text(json.dumps(report, indent=2))
    _print(report, trials_run)
    print(f"wrote {out}")
    return report


def _print(report: dict, trials_run: int) -> None:
    print()
    print(f"machine: {report['machine']}")
    print(f"retrain = one fit of {report['trees']} trees. search trial = {report['folds_per_trial']} folds.")
    print(f"{'years':>7} {'rows':>8} {'retrain s':>10} {'std':>6} {'cpu s':>8} {'trial s':>9} {'peak MB':>8}")
    for row in report["training"]:
        fit = row["retrain_seconds"]
        mark = "*" if row["repeated_hours"] else " "
        print(
            f"{mark}{row['years']:6.2f} {row['rows']:8d} {fit['mean']:10.1f} {fit['std']:6.2f} "
            f"{row['retrain_cpu_seconds']['mean']:8.1f} {row['trial_seconds']['mean']:9.1f} {row['peak_mb']:8.0f}"
        )
    print("* hours repeated to reach that length")
    print()
    print(f"full search, using the measured trial time. The last run scored {trials_run} candidates.")
    print(f"{'years':>7} {'44 trials':>12} {'80 trials':>12}")
    seen = set()
    for row in report["full_search_minutes"]:
        if row["years"] in seen or row["trials"] not in (44, 80):
            continue
        pair = {item["trials"]: item["minutes"] for item in report["full_search_minutes"] if item["years"] == row["years"]}
        seen.add(row["years"])
        print(f"{row['years']:7.2f} {pair.get(44, float('nan')):10.1f} m {pair.get(80, float('nan')):10.1f} m")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
