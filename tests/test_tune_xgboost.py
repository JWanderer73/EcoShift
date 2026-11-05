"""Optuna tunes XGBoost on the training block and leaves a saved model."""

import numpy as np

from src.forecast_data import TEST_DAYS
from src.tune_xgboost import tune
from tests.test_xgb_benchmark import _write_dataset


def test_short_optuna_search_scores_the_holdout_once(tmp_path, cleaned_table) -> None:
    path = _write_dataset(tmp_path, cleaned_table(24 * 80))
    result = tune(path=path, n_trials=2, quick=True)
    assert result["sampler"] == "optuna TPE"
    assert result["trials"] == 2
    assert result["test_rows"] == TEST_DAYS * 24
    assert np.isfinite(result["cv_mae"])
    assert np.isfinite(result["mae"])
    assert result["best_params"]["n_estimators"] > 0
