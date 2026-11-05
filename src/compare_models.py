"""Fit every model on the same time cut and write one comparison table.

The target is hourly CAISO electricity demand, in megawatthours, from
``demand_dataset.csv``. The models are the ones that keep showing
up for hourly electricity load:

- linear regression, ridge, lasso, elastic net
- random forest and extra trees
- histogram gradient boosting, XGBoost, and LightGBM

Three baselines are scored beside them: demand at the same hour
yesterday, at the same hour last week, and CAISO's own day-ahead forecast.
A model that cannot beat those has not learned anything worth keeping.

Each model file can also be run on its own. This script calls them in
order, saves every fitted model under ``models/``, and writes
``results/model_comparison.json``. The weather-forecast stand-in variant
writes ``results/model_comparison_weather_forecast_standin.json``.

    python -m src.compare_models
    python -m src.compare_models --variant weather_forecast_standin
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.build_demand_dataset import DEFAULT_VARIANT, VARIANTS
from src.carbon_data import repo_root
from src.elastic_net_model import run as run_elastic_net
from src.extra_trees_model import run as run_extra_trees
from src.forecast_data import TEST_DAYS, baseline_rows, data_path, feature_columns, train_test_hours
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


def results_path(variant: str = DEFAULT_VARIANT) -> Path:
    """Where a variant's comparison table is written."""
    name = "model_comparison.json" if variant == DEFAULT_VARIANT else f"model_comparison_{variant}.json"
    return repo_root() / "results" / name


def compare(path: Path, param_grids: dict | None = None) -> list[dict]:
    """Score the baselines, then fit every model on ``path``.

    Args:
        path: Demand dataset CSV.
        param_grids: Optional grid per runner index, so tests can stay fast.

    Returns:
        Baseline rows first, then one row per model.
    """
    _, test = train_test_hours(path)
    results = baseline_rows(test)
    for index, run in enumerate(RUNNERS):
        grid = None if param_grids is None else param_grids.get(index)
        results.append(run(path=path, param_grid=grid))
        print()
    return results


def main() -> None:
    """Run every model and print them sorted by test MAE."""
    parser = argparse.ArgumentParser(description="Compare every demand model on one time cut.")
    parser.add_argument("--variant", choices=VARIANTS, default=DEFAULT_VARIANT)
    args = parser.parse_args()
    path = data_path(args.variant)

    print(f"Same cut for every model: the last {TEST_DAYS} days are the test block.")
    print(f"Variant: {args.variant}")
    print("Features:")
    for column in feature_columns(path):
        print(f"  {column}")
    print()

    results = compare(path)
    by_error = sorted(results, key=lambda row: row["mae"])
    print("Sorted by test MAE (lower is better)")
    print(f"{'model':<28} {'kind':<9} {'MAE':>9} {'MAPE %':>7} {'RMSE':>9} {'fit s':>8} {'search s':>9}")
    for row in by_error:
        print(
            f"{row['model']:<28} {row['kind']:<9} {row['mae']:9.1f} {row['mape']:7.2f} {row['rmse']:9.1f} "
            f"{row.get('fit_seconds', 0.0):8.3f} {row.get('search_seconds', 0.0):9.3f}"
        )
    print()
    models = [row for row in results if row["kind"] == "model"]
    print(f"lowest test MAE: {by_error[0]['model']}")
    print(f"fastest single fit: {min(models, key=lambda row: row['fit_seconds'])['model']}")

    path_out = results_path(args.variant)
    path_out.parent.mkdir(parents=True, exist_ok=True)
    path_out.write_text(json.dumps(results, indent=2))
    print(f"wrote {path_out}")


if __name__ == "__main__":
    main()
