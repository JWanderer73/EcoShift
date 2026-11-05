"""The comparison forecasts electricity demand from the cleaned CSV, on a 60/40 time cut."""

import numpy as np
import pandas as pd

from src.forecast_data import FEATURE_COLUMNS, TARGET, TRAIN_FRACTION, load_hours, train_test_hours
from src.xgb_benchmark import run


def _hourly_table(periods: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    hour = index.tz_convert("America/Los_Angeles").hour.to_numpy()
    demand = 20000.0 + 4000.0 * np.sin(2 * np.pi * hour / 24)
    frame = pd.DataFrame(
        {
            "carbon_intensity_g_per_kwh": np.linspace(80.0, 220.0, periods),
            "ng_mwh": 999.0,
            "demand_mwh": demand,
            "demand_forecast_mwh": demand - 200.0,
            "temp": np.linspace(10.0, 30.0, periods),
            "radiation": np.linspace(0.0, 800.0, periods),
            "radiation_fresno": np.linspace(0.0, 900.0, periods),
            "wind_10m": np.linspace(1.0, 8.0, periods),
        },
        index=index,
    )
    return frame


def test_load_hours_keeps_demand_and_drops_fuel_and_carbon(tmp_path) -> None:
    path = tmp_path / "panel.csv"
    _hourly_table(24 * 40).to_csv(path)
    loaded = load_hours(path)
    assert TARGET in loaded.columns
    assert "ng_mwh" not in loaded.columns
    assert "carbon_intensity_g_per_kwh" not in loaded.columns
    assert TARGET not in FEATURE_COLUMNS


def test_split_is_the_first_sixty_percent(tmp_path) -> None:
    path = tmp_path / "panel.csv"
    _hourly_table(24 * 80).to_csv(path)
    train, test = train_test_hours(path)
    assert len(train) == int((len(train) + len(test)) * TRAIN_FRACTION)
    assert train.index.max() < test.index.min()
    assert TRAIN_FRACTION == 0.60
    assert TARGET == "demand_mwh"


def test_short_xgb_fit_returns_finite_holdout_error(tmp_path) -> None:
    path = tmp_path / "panel.csv"
    _hourly_table(24 * 80).to_csv(path)
    result = run(path=path, param_grid={"n_estimators": [20], "max_depth": [2], "learning_rate": [0.1]})
    assert result["target"] == "demand_mwh"
    assert result["train_rows"] == int((result["train_rows"] + result["test_rows"]) * 0.60)
    assert result["fit_seconds"] >= 0.0
    assert np.isfinite(result["mae"])
    assert np.isfinite(result["mse"])
    assert result["test_rows"] > 0
