"""LightGBM.

Boosted trees built to train faster than XGBoost by growing each tree
one leaf at a time. A 2025 comparison of carbon-intensity forecasts
across grids found LightGBM ahead of XGBoost, random forests, and CatBoost
on average error.

``n_estimators`` is the number of trees. ``max_depth`` and
``learning_rate`` mean the same thing they do for XGBoost.

    python -m src.lightgbm_model
"""

from __future__ import annotations

from lightgbm import LGBMRegressor

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

PARAM_GRID = {
    "n_estimators": [100, 300],
    "max_depth": [4, 8],
    "learning_rate": [0.05, 0.1],
}


def make_model() -> LGBMRegressor:
    """One LightGBM regressor. Warnings about feature names are turned off."""
    return LGBMRegressor(
        objective="regression",
        n_jobs=-1,
        random_state=0,
        verbosity=-1,
    )


def run() -> dict:
    """Search the boosting settings on the training hours, then score the test hours."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("LightGBM", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
