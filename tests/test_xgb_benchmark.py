"""Checks that the XGBoost benchmark ignores fuel columns and returns finite error."""

import numpy as np
import pandas as pd

from src.carbon_data import PANEL_COLUMNS
from src.xgb_benchmark import load_panel, run


def _hourly_table(periods: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    frame = pd.DataFrame({column: np.linspace(80.0, 220.0, periods) for column in PANEL_COLUMNS}, index=index)
    hour = index.tz_convert("America/Los_Angeles").hour.to_numpy()
    frame["carbon_intensity_g_per_kwh"] = 150.0 + 40.0 * np.sin(2 * np.pi * hour / 24)
    frame["ng_mwh"] = 999.0
    return frame


def test_load_panel_drops_fuel_columns(tmp_path) -> None:
    path = tmp_path / "panel.csv"
    _hourly_table(24 * 40).to_csv(path)
    loaded = load_panel(path)
    assert list(loaded.columns) == PANEL_COLUMNS
    assert "ng_mwh" not in loaded.columns


def test_short_xgb_fit_returns_finite_holdout_error(tmp_path) -> None:
    path = tmp_path / "panel.csv"
    _hourly_table(24 * 80).to_csv(path)
    result = run(n_estimators=20, path=path)
    assert result["n_estimators"] == 20
    assert result["fit_seconds"] >= 0.0
    assert np.isfinite(result["mae"])
    assert np.isfinite(result["mse"])
    assert result["test_rows"] > 0
