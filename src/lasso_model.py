"""Lasso regression.

A penalized line that can set some coefficients to exactly zero, which
drops those features. ``alpha`` is how hard it pushes coefficients to zero.

    python -m src.lasso_model
"""

from __future__ import annotations

from sklearn.linear_model import Lasso
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

PARAM_GRID = {
    "model__alpha": [0.0001, 0.001, 0.01, 0.1, 1.0, 10.0],
}


def make_model() -> Pipeline:
    """Scale every column, then fit a lasso."""
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", Lasso(max_iter=20000)),
    ])


def run() -> dict:
    """Search alpha on the first 60% of hours and score the last 40%."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Lasso", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
