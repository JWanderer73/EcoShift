"""Elastic net.

A line with both penalties at once: ridge (shrink coefficients) and
lasso (drop coefficients). ``alpha`` is the total penalty. ``l1_ratio``
is the share of that penalty that acts like lasso. 0.2 is mostly ridge.
0.8 is mostly lasso.

    python -m src.elastic_net_model
"""

from __future__ import annotations

from sklearn.linear_model import ElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

PARAM_GRID = {
    "model__alpha": [0.001, 0.01, 0.1, 1.0],
    "model__l1_ratio": [0.2, 0.5, 0.8],
}


def make_model() -> Pipeline:
    """Scale every column, then fit an elastic net."""
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", ElasticNet(max_iter=20000)),
    ])


def run() -> dict:
    """Search alpha and l1_ratio on the training hours, then score the test hours."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Elastic net", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
