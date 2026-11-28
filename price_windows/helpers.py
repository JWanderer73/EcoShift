"""Helpers this folder used to borrow from other models.

They live here so a checkout of main can train prices without the demand
or carbon modules.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import optuna
import pandas as pd

# Random trials before the sampler trusts its own model.
STARTUP_TRIALS = 15
# A fold stops when this many new trees fail to improve its validation hours.
EARLY_STOPPING_ROUNDS = 40
SEED = 0


def repo_root() -> Path:
    """Return the repository root, whether the caller started in it or in a subfolder."""
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "requirements.txt").exists() and (candidate / ".env.example").exists():
            return candidate
    return here


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th given weekday of a month (Monday is 0). n = -1 is the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    following = dt.date(year + month // 12, month % 12 + 1, 1)
    last = following - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: dt.date) -> dt.date:
    """A fixed-date holiday on a Saturday is observed Friday, on a Sunday, Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def us_holidays(years) -> set[dt.date]:
    """US federal holidays, plus the day after Thanksgiving, which California also observes.

    Both the actual date and the observed weekday are included for fixed-date
    holidays, because load drops on both.
    """
    days: set[dt.date] = set()
    for year in years:
        for month, day in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25)):
            actual = dt.date(year, month, day)
            days.update({actual, _observed(actual)})
        thanksgiving = _nth_weekday(year, 11, 3, 4)
        days.update(
            {
                _nth_weekday(year, 1, 0, 3),
                _nth_weekday(year, 2, 0, 3),
                _nth_weekday(year, 5, 0, -1),
                _nth_weekday(year, 9, 0, 1),
                _nth_weekday(year, 10, 0, 2),
                thanksgiving,
                thanksgiving + dt.timedelta(days=1),
            }
        )
    return days


def content_hash(frame: pd.DataFrame) -> str:
    """A short fingerprint of the table, index included, so a run can name its data."""
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy()
    return hashlib.sha256(hashed.tobytes()).hexdigest()[:16]


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
