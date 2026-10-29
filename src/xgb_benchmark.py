"""XGBoost on hourly CAISO carbon intensity.

Read this file from top to bottom:

1. Load the cleaned CSV and cut it: first 60% trains, last 40% tests.
2. Try a small grid of tree settings. The search only uses the training hours.
3. Fit the winner once and print how long that took, plus test MAE and MSE.

An earlier version fit 10,000 trees with the settings fixed in advance.
This version searches, because the question now is which settings are
worth the time.

Run it on its own:

    python -m src.xgb_benchmark
"""

from __future__ import annotations

from pathlib import Path

from xgboost import XGBRegressor

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

# Each candidate is trained three times inside the training block.
# 2 x 2 x 2 = 8 candidates.
PARAM_GRID = {
    "n_estimators": [100, 300],
    "max_depth": [4, 8],
    "learning_rate": [0.05, 0.1],
}


def make_model() -> XGBRegressor:
    """One XGBoost regressor. The grid above replaces the three tuned numbers."""
    return XGBRegressor(
        objective="reg:squarederror",
        tree_method="hist",
        n_jobs=-1,
        random_state=0,
        verbosity=0,
    )


def run(path: Path | None = None, param_grid: dict | None = None) -> dict:
    """Search, refit the winner, and return the test scores.

    Args:
        path: CSV to read. Defaults to the cleaned 10,000-hour table.
        param_grid: Settings to try. Tests pass a one-row grid so they stay fast.
    """
    train, test = train_test_hours(path)
    print_split(train, test)
    result = search_and_score(
        "XGBoost",
        make_model(),
        PARAM_GRID if param_grid is None else param_grid,
        train,
        test,
    )
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
