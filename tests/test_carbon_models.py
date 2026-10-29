"""Checks for the carbon formula, the time split, and the feature lists."""

import numpy as np
import pandas as pd

from src.carbon_data import PANEL_COLUMNS, carbon_intensity, model_frame
from src.modeling import (
    CYCLICAL_NUMERIC,
    DAY_AHEAD_CATEGORICAL,
    DAY_AHEAD_NUMERIC,
    LEAKED_COLUMNS,
    OBSERVED_NOW,
    PREVIOUS_HOUR,
    TARGET,
    check_features,
    shape_mae,
    shift_regret,
    train_test_split,
)


def test_carbon_intensity_half_gas_half_solar() -> None:
    fuels = pd.DataFrame({"NG": [50.0], "SUN": [50.0]})
    intensity = carbon_intensity(fuels)
    assert intensity.iloc[0] == np.float64(393.0 * 50.0 / 100.0)


def test_carbon_intensity_clips_negative_generation() -> None:
    fuels = pd.DataFrame({"NG": [10.0], "SUN": [-4.0], "WND": [0.0]})
    intensity = carbon_intensity(fuels)
    assert intensity.iloc[0] == np.float64(393.0)


def test_feature_lists_exclude_the_fuel_mix() -> None:
    used = set(DAY_AHEAD_CATEGORICAL + DAY_AHEAD_NUMERIC + CYCLICAL_NUMERIC + OBSERVED_NOW + PREVIOUS_HOUR)
    assert used.isdisjoint(LEAKED_COLUMNS)
    check_features(DAY_AHEAD_CATEGORICAL + DAY_AHEAD_NUMERIC)


def test_model_frame_lag_is_twenty_four_hours() -> None:
    index = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    panel = pd.DataFrame({column: np.arange(200, dtype=float) for column in PANEL_COLUMNS}, index=index)
    panel["carbon_intensity_g_per_kwh"] = np.arange(200, dtype=float)
    frame = model_frame(panel)
    stamp = index[168]
    assert frame.loc[stamp, "carbon_lag_24"] == 144.0
    assert frame.loc[stamp, "carbon_lag_1"] == 167.0
    assert TARGET in frame.columns
    assert "NG" not in frame.columns


def test_train_test_split_is_ordered_and_disjoint() -> None:
    index = pd.date_range("2026-01-01", periods=24 * 40, freq="h", tz="UTC")
    frame = pd.DataFrame({"value": np.arange(len(index))}, index=index)
    train, test = train_test_split(frame, test_days=7)
    assert train.index.max() < test.index.min()
    assert test.index.min() == frame.index.max() - pd.Timedelta(days=7)


def test_shift_regret_is_zero_when_the_order_is_right() -> None:
    actual = np.array([10.0, 80.0, 20.0, 90.0])
    predicted = actual + 40.0
    assert shift_regret(actual, predicted, hours=2) == 0.0


def test_shift_regret_is_the_extra_carbon_of_the_wrong_hours() -> None:
    actual = np.array([10.0, 80.0, 20.0, 90.0])
    predicted = np.array([90.0, 10.0, 80.0, 20.0])
    assert shift_regret(actual, predicted, hours=2) == np.float64(70.0)


def test_shape_mae_ignores_a_constant_level_miss() -> None:
    actual = np.array([10.0, 30.0, 20.0])
    assert shape_mae(actual, actual + 50.0) == 0.0
