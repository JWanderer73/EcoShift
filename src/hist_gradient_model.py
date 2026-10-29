"""Histogram gradient boosting.

Sklearn's own boosted trees. Histograms bin each feature first, which
makes the splits cheap. On hourly load data this family is often tied
with LightGBM for accuracy, with a different training time.

``max_iter`` is the number of trees. ``learning_rate`` is how much each
new tree is allowed to correct the ones before it. ``max_depth`` caps
each tree.

    python -m src.hist_gradient_model
"""

from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingRegressor

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

PARAM_GRID = {
    "learning_rate": [0.05, 0.1],
    "max_depth": [4, 8],
    "max_iter": [150, 300],
}


def make_model() -> HistGradientBoostingRegressor:
    """One boosted-tree model. Early stopping is off so every candidate builds all of its trees."""
    return HistGradientBoostingRegressor(
        early_stopping=False,
        random_state=0,
    )


def run() -> dict:
    """Search the boosting settings on the training hours, then score the test hours."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Hist gradient boosting", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
