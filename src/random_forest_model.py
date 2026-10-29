"""Random forest.

A crowd of decision trees. Each tree sees a random sample of the hours
and a random sample of the features. The forecast is the average of the trees.

``n_estimators`` is how many trees. ``max_depth`` is how many splits a
tree may make. Deeper trees fit the training hours more tightly and
take longer.

    python -m src.random_forest_model
"""

from __future__ import annotations

from sklearn.ensemble import RandomForestRegressor

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

PARAM_GRID = {
    "n_estimators": [100, 300],
    "max_depth": [8, 16],
}


def make_model() -> RandomForestRegressor:
    """One forest. Leaves smaller than 5 hours are treated as noise."""
    return RandomForestRegressor(
        min_samples_leaf=5,
        n_jobs=-1,
        random_state=0,
    )


def run() -> dict:
    """Search the forest settings on the training hours, then score the test hours."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Random forest", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
