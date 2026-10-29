"""Ridge regression.

Same line as ordinary linear regression, plus a penalty that shrinks
the coefficients. ``alpha`` is the size of that penalty. The grid picks
the alpha with the lowest error inside the training hours.

    python -m src.ridge_model
"""

from __future__ import annotations

from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

# Small alpha is almost ordinary linear regression. Large alpha pulls
# every coefficient toward zero.
PARAM_GRID = {
    "model__alpha": [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
}


def make_model() -> Pipeline:
    """Scale every column, then fit a penalized line."""
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", Ridge()),
    ])


def run() -> dict:
    """Search alpha on the first 60% of hours and score the last 40%."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Ridge", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
