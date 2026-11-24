"""Tune XGBoost with Optuna, then score the test block once.

The small grid in ``src/xgb_benchmark.py`` tries eight settings. This
search tries many more, and it chooses them. Optuna's TPE sampler keeps a
probabilistic model of which settings have worked so far and draws the
next trial from the region that model says is promising. The first trials
are random, so the model has something to learn from.

The score being minimized is mean absolute error on forward folds inside
the training block. The last 56 days are scored once, after the search,
and they are never used to pick a setting. Each fold stops adding trees
once the validation hours stop improving, so a trial does not spend its
time on trees that no longer help.

    python -m src.tune_xgboost
    python -m src.tune_xgboost --trials 40
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
import optuna
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from src.build_demand_dataset import DEFAULT_VARIANT, VARIANTS
from src.carbon_data import repo_root
from src.forecast_data import (
    CV_SPLITS,
    TARGET,
    TARGET_UNIT,
    data_path,
    features,
    model_slug,
    print_split,
    score,
    train_test_hours,
)

# Random trials before the sampler trusts its own model.
STARTUP_TRIALS = 15
# A fold stops when this many new trees fail to improve its validation hours.
EARLY_STOPPING_ROUNDS = 40
SEED = 0


def _suggest(trial: optuna.Trial, quick: bool) -> dict:
    """Draw one set of tree settings. ``quick`` keeps the test suite small."""
    return {
        "objective": trial.suggest_categorical("objective", ["reg:squarederror", "reg:absoluteerror"]),
        "max_depth": trial.suggest_int("max_depth", 2, 4 if quick else 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.05 if quick else 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 20 if quick else 200, 40 if quick else 1200),
        "min_child_weight": trial.suggest_float("min_child_weight", 1.0, 50.0, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "gamma": trial.suggest_float("gamma", 0.0, 5.0),
    }


def _fit_fold(params: dict, x_fit, y_fit, x_valid, y_valid) -> tuple[float, int]:
    """Fit one fold, stop early, and return its validation MAE and the tree it stopped at."""
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
    predicted = np.maximum(model.predict(x_valid), 0.0)
    trees = int(model.best_iteration) + 1
    return score(y_valid, predicted)["mae"], trees


def tune(path: Path | None = None, n_trials: int = 80, quick: bool = False, timeout: float | None = None) -> dict:
    """Search settings on the training block, refit the winner, and score the test block once.

    Args:
        path: Demand dataset CSV. Defaults to the honest variant.
        n_trials: How many settings to try. A ``timeout`` stops the search earlier.
        quick: Shrink the search so a test finishes in seconds.
        timeout: Stop after this many seconds. The trials already finished are kept.

    Returns:
        The winning settings, the forward-fold MAE, and the test scores.
    """
    train, test = train_test_hours(path)
    print_split(train, test)
    x_train = features(train)
    y_train = train[TARGET]
    folds = list(TimeSeriesSplit(n_splits=CV_SPLITS).split(x_train))

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
    started = time.perf_counter()
    model.fit(x_train, y_train, verbose=False)
    fit_seconds = time.perf_counter() - started
    predicted = np.maximum(model.predict(features(test)), 0.0)

    model_dir = Path(train.attrs["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{model_slug('XGBoost optuna')}.joblib"
    joblib.dump(model, model_path)

    result = {
        "model": "XGBoost optuna",
        "target": TARGET,
        "unit": TARGET_UNIT,
        "variant": train.attrs.get("variant"),
        "dataset_hash": train.attrs.get("content_hash"),
        "sampler": "optuna TPE",
        "trials": int(len(study.trials)),
        "pruned_trials": int(sum(trial.state == optuna.trial.TrialState.PRUNED for trial in study.trials)),
        "best_params": best,
        "cv_mae": float(study.best_value),
        **score(test[TARGET], predicted),
        "fit_seconds": float(fit_seconds),
        "search_seconds": float(search_seconds),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "model_path": str(model_path),
    }
    if path is None or Path(path).resolve() == data_path(train.attrs.get("variant", DEFAULT_VARIANT)).resolve():
        out = repo_root() / "results" / f"xgb_optuna{'' if train.attrs.get('variant') == DEFAULT_VARIANT else '_' + train.attrs['variant']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        print(f"wrote {out}")
    _print(result)
    return result


def _print(result: dict) -> None:
    print(f"{result['model']} ({result['sampler']}, {result['trials']} trials, {result['pruned_trials']} pruned)")
    settings = ", ".join(f"{key}={value}" for key, value in result["best_params"].items())
    print(f"  best settings: {settings}")
    print(f"  forward-fold MAE: {result['cv_mae']:.1f} {result['unit']}")
    print(f"  search: {result['search_seconds']:.1f} s")
    print(f"  fit: {result['fit_seconds']:.3f} s")
    print(f"  test MAE: {result['mae']:.1f} {result['unit']} ({result['mape']:.2f}%)")
    print(f"  test RMSE: {result['rmse']:.1f} {result['unit']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune XGBoost with Optuna on the training block.")
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--minutes", type=float, default=None, help="stop the search after this many minutes")
    parser.add_argument("--variant", choices=VARIANTS, default=DEFAULT_VARIANT)
    args = parser.parse_args()
    n_trials = args.trials if args.minutes is None else max(args.trials, 10_000)
    timeout = None if args.minutes is None else args.minutes * 60
    tune(path=data_path(args.variant), n_trials=n_trials, timeout=timeout)


if __name__ == "__main__":
    main()
