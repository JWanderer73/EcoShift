"""Extra trees.

Like a random forest, but each split is drawn at random and the best of
those random splits is kept. That is usually faster than searching for
the single best split, which is why this file is in the speed comparison.

Day-ahead carbon-intensity papers often find this family competitive
with neural nets, and faster to train.

    python -m src.extra_trees_model
"""

from __future__ import annotations

from sklearn.ensemble import ExtraTreesRegressor

from src.forecast_data import print_score, print_split, search_and_score, train_test_hours

# max_depth None means a tree may keep splitting until a leaf is small.
PARAM_GRID = {
    "n_estimators": [100, 300],
    "max_depth": [8, 16, None],
}


def make_model() -> ExtraTreesRegressor:
    """One extra-trees model. Leaves smaller than 5 hours are treated as noise."""
    return ExtraTreesRegressor(
        min_samples_leaf=5,
        n_jobs=-1,
        random_state=0,
    )


def run() -> dict:
    """Search tree count and depth on the training hours, then score the test hours."""
    train, test = train_test_hours()
    print_split(train, test)
    result = search_and_score("Extra trees", make_model(), PARAM_GRID, train, test)
    print_score(result)
    return result


def main() -> None:
    run()


if __name__ == "__main__":
    main()
