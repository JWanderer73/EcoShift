"""The price model is scored in $/MWh, without clipping a negative hour."""

import json

import joblib
import numpy as np
import pandas as pd
import pytest

from price_windows.schema import TARGET, TEST_DAYS
from price_windows.train_xgboost import LAG_168, LAG_72, _errors, _folds, _shift_regret, _split, predict_price, train


def test_percent_error_uses_only_prices_above_five_dollars() -> None:
    actual = np.array([-10.0, 5.0, 10.0])
    predicted = np.array([-12.0, 0.0, 8.0])
    scored = _errors(actual, predicted)
    # Clipping the -12 forecast to zero would make the first absolute error 10, not 2.
    assert scored["mae_usd_per_mwh"] == pytest.approx(np.mean([2.0, 5.0, 2.0]))
    assert scored["percent_error_mean"] == pytest.approx(20.0)
    assert scored["percent_error_median"] == pytest.approx(20.0)


def test_shift_regret_keeps_a_negative_price() -> None:
    actual = np.array([5.0, -10.0, 3.0])
    predicted = np.array([0.0, -1.0, -5.0])
    # The cheapest forecast is the last hour. Clipping it to zero would tie every hour.
    assert _shift_regret(actual, predicted, hours=1) == pytest.approx(13.0)


def test_predict_price_does_not_clip() -> None:
    class _Fake:
        def predict(self, frame):
            return np.array([-3.5, 4.0])

    saved = {"model": _Fake(), "features": ["hour_sin"], "target": TARGET}
    out = predict_price(saved, pd.DataFrame({"hour_sin": [1.0, 2.0]}))
    assert out.tolist() == [-3.5, 4.0]
    saved["residual_of"] = LAG_72
    added = predict_price(saved, pd.DataFrame({"hour_sin": [1.0, 2.0], LAG_72: [-1.0, 2.0]}))
    assert added.tolist() == [-4.5, 6.0]


def test_folds_keep_every_node_at_one_hour_together() -> None:
    hours = pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC")
    index = hours.repeat(2)
    folds = _folds(index)
    assert len(folds) == 3
    for fit_rows, valid_rows in folds:
        fit_times = set(index[fit_rows])
        valid_times = set(index[valid_rows])
        assert fit_times.isdisjoint(valid_times)
        assert max(fit_times) < min(valid_times)
        for stamp in valid_times:
            rows = set(np.flatnonzero(index == stamp))
            assert len(rows) == 2
            assert rows <= set(valid_rows)


def _panel() -> tuple[pd.DataFrame, list[str]]:
    hours = pd.date_range("2026-01-01 08:00", periods=40 * 24, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    frames = []
    for node, level in (("N1", 15.0), ("N2", 40.0)):
        clock = np.arange(len(hours))
        lag = level + 8.0 * np.sin(clock * 2 * np.pi / 24) + rng.normal(0, 1, len(hours))
        target = lag - 20.0 + rng.normal(0, 0.3, len(hours))
        frames.append(
            pd.DataFrame(
                {
                    "campus_id": "campus",
                    "pnode_id": node,
                    TARGET: target,
                    LAG_72: lag,
                    LAG_168: lag,
                    "hour_sin": np.sin(hours.hour * 2 * np.pi / 24),
                    "node_type_load": 1.0,
                },
                index=hours,
            )
        )
    features = [LAG_168, "hour_sin", "node_type_load"]
    return pd.concat(frames).sort_index(), features


def test_leaky_feature_is_refused(tmp_path) -> None:
    frame, _features = _panel()
    with pytest.raises(ValueError, match="leak"):
        train(n_trials=1, quick=True, frame=frame, features=["lmp_lag_24"], output_dir=tmp_path)
    with pytest.raises(ValueError, match="leak"):
        train(n_trials=1, quick=True, frame=frame, features=["lmp_mcc_lag_168"], output_dir=tmp_path)


def test_short_search_scores_the_last_28_days_once(tmp_path) -> None:
    frame, features = _panel()
    extra = frame.copy()
    extra["campus_id"] = "other"
    extra["distance_km"] = 9.0
    doubled = pd.concat([frame, extra])
    metrics = train(
        n_trials=2,
        quick=True,
        frame=doubled,
        features=[*features, "distance_km"],
        output_dir=tmp_path,
    )
    assert metrics["train_rows"] + metrics["test_rows"] == len(frame)
    assert metrics["residual_of"] == LAG_72
    assert metrics["trials"] == 2
    assert metrics["clipped_at_zero"] is False
    assert metrics["percent_error_min_price_usd_per_mwh"] == 5.0
    assert np.isfinite(metrics["test"]["mae_usd_per_mwh"])
    assert np.isfinite(metrics["test"]["rmse_usd_per_mwh"])
    assert np.isfinite(metrics["cv_mae_usd_per_mwh"])
    assert metrics["best_params"]["n_estimators"] > 0
    assert metrics["test"]["percent_error_mean"] is not None
    assert np.isfinite(metrics["test_regret_4h_usd_per_mwh"])

    train_frame, test_frame = _split(frame.sort_index())
    assert train_frame.index.max() <= frame.index.max() - pd.Timedelta(days=TEST_DAYS)
    assert test_frame.index.min() > frame.index.max() - pd.Timedelta(days=TEST_DAYS)
    assert set(train_frame.index).isdisjoint(set(test_frame.index))

    saved = joblib.load(tmp_path / "model.joblib")
    assert saved["target"] == TARGET
    assert saved["features"] == features
    assert saved["residual_of"] == LAG_72
    assert "distance_km" not in saved["features"]
    predicted = predict_price(saved, test_frame)
    raw = np.asarray(saved["model"].predict(test_frame.loc[:, features].astype(float)), dtype=float)
    assert np.allclose(predicted, raw + test_frame[LAG_72].to_numpy(dtype=float))
    scored = _errors(test_frame[TARGET], predicted)
    assert metrics["test"]["percent_error_mean"] == pytest.approx(scored["percent_error_mean"])
    below = test_frame[TARGET].to_numpy() <= 5
    assert np.any(below)
    written = json.loads((tmp_path / "metrics.json").read_text())
    assert written["test"]["mae_usd_per_mwh"] == pytest.approx(metrics["test"]["mae_usd_per_mwh"])
    assert {row["name"] for row in written["baselines_test"]} == {
        "same hour three days ago",
        "same hour last week",
        "hour of week mean",
    }
