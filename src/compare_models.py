"""Fit every model on the same 60/40 cut and write one comparison table.

The models are the ones that keep showing up for hourly carbon intensity
and hourly electricity load:

- linear regression, ridge, lasso, elastic net
- random forest and extra trees
- histogram gradient boosting, XGBoost, and LightGBM

Each file in this list can also be run on its own. This script just calls
them in order and saves ``results/model_comparison.json``.

    python -m src.compare_models
"""

from __future__ import annotations

import json

from src.carbon_data import repo_root
from src.elastic_net_model import run as run_elastic_net
from src.extra_trees_model import run as run_extra_trees
from src.forecast_data import FEATURE_COLUMNS, TRAIN_FRACTION
from src.hist_gradient_model import run as run_hist_gradient
from src.lasso_model import run as run_lasso
from src.lightgbm_model import run as run_lightgbm
from src.linear_regression_model import run as run_linear
from src.random_forest_model import run as run_random_forest
from src.ridge_model import run as run_ridge
from src.xgb_benchmark import run as run_xgboost

RUNNERS = [
    run_linear,
    run_ridge,
    run_lasso,
    run_elastic_net,
    run_random_forest,
    run_extra_trees,
    run_hist_gradient,
    run_xgboost,
    run_lightgbm,
]


def main() -> None:
    """Run every model and print them sorted by test MAE."""
    print(f"Same cut for every model: first {TRAIN_FRACTION:.0%} trains, last {1 - TRAIN_FRACTION:.0%} tests.")
    print("Features:")
    for column in FEATURE_COLUMNS:
        print(f"  {column}")
    print()

    results = []
    for run in RUNNERS:
        results.append(run())
        print()

    by_error = sorted(results, key=lambda row: row["mae"])
    by_speed = sorted(results, key=lambda row: row["fit_seconds"])
    print("Sorted by test MAE (lower is better)")
    print(f"{'model':<28} {'MAE':>10} {'MSE':>12} {'fit s':>8} {'search s':>10}")
    for row in by_error:
        print(
            f"{row['model']:<28} {row['mae']:10.3f} {row['mse']:12.3f} "
            f"{row['fit_seconds']:8.3f} {row['search_seconds']:10.3f}"
        )
    print()
    print(f"lowest test MAE: {by_error[0]['model']}")
    print(f"fastest single fit: {by_speed[0]['model']}")

    path = repo_root() / "results" / "model_comparison.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
