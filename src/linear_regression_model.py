"""Ordinary linear regression.

Each feature gets one coefficient. There is no penalty, so there is no
grid to search. This is the straight line the penalized linear models
are being compared with.

The features are scaled first. Hour and weekday are already stored as
sine and cosine, so the model does not treat hour 23 as "23 times" hour 1.

    python -m src.linear_regression_model
"""

from __future__ import annotations

from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours


def make_model() -> Pipeline:
    """Scale every column, then fit a line."""
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", LinearRegression()),
    ])


def run() -> dict:
    """Fit the line on the first 60% of hours and score the last 40%."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Linear regression", make_model(), {}, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
