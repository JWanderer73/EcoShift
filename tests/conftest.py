"""A synthetic copy of the cleaned CSV, with the same columns and the same identities."""

import numpy as np
import pandas as pd
import pytest

from src.carbon_data import CITIES
from src.column_audit import FUEL_COLUMNS


def synthetic_cleaned_table(periods: int, seed: int = 0) -> pd.DataFrame:
    """Hourly rows shaped like ``cleaned_weather_carbon.csv``.

    The averages, the Fresno copy, and shortwave = direct + diffuse hold
    exactly, as they do in the real file, so the audit has something to find.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    hour = index.tz_convert("America/Los_Angeles").hour.to_numpy()
    daylight = np.clip(np.sin(np.pi * (hour - 6) / 12), 0.0, None)
    frame = pd.DataFrame(index=index)
    for city, _, _ in CITIES:
        direct = 600.0 * daylight * rng.uniform(0.2, 1.0, periods)
        diffuse = 150.0 * daylight * rng.uniform(0.2, 1.0, periods)
        frame[f"{city}_temperature_2m"] = 15.0 + 8.0 * daylight + rng.normal(0.0, 4.0, periods)
        frame[f"{city}_relative_humidity_2m"] = rng.uniform(20.0, 90.0, periods)
        frame[f"{city}_wind_speed_10m"] = rng.uniform(0.0, 20.0, periods)
        frame[f"{city}_wind_direction_10m"] = rng.uniform(0.0, 360.0, periods)
        frame[f"{city}_shortwave_radiation"] = direct + diffuse
        frame[f"{city}_direct_radiation"] = direct
        frame[f"{city}_diffuse_radiation"] = diffuse
        frame[f"{city}_cloud_cover"] = rng.uniform(0.0, 100.0, periods)
        frame[f"{city}_precipitation"] = rng.exponential(0.2, periods) * (rng.uniform(size=periods) < 0.1)
        frame[f"{city}_is_day"] = (daylight > 0).astype(float)
    cities = [city for city, _, _ in CITIES]
    frame["temp"] = frame[[f"{city}_temperature_2m" for city in cities]].mean(axis=1)
    frame["radiation"] = frame[[f"{city}_shortwave_radiation" for city in cities]].mean(axis=1)
    frame["radiation_fresno"] = frame["fresno_shortwave_radiation"]
    frame["wind_10m"] = frame[[f"{city}_wind_speed_10m" for city in cities]].mean(axis=1)
    demand = 25000.0 + 4000.0 * np.sin(2 * np.pi * hour / 24) + 150.0 * frame["temp"] + rng.normal(0.0, 500.0, periods)
    frame["demand_mwh"] = demand
    frame["demand_forecast_mwh"] = demand + rng.normal(0.0, 1500.0, periods)
    for column in FUEL_COLUMNS:
        frame[column] = demand * rng.uniform(0.0, 0.2, periods)
    frame["carbon_intensity_g_per_kwh"] = 393.0 * frame["ng_mwh"] / frame[FUEL_COLUMNS].sum(axis=1)
    frame.index.name = "timestamp"
    return frame


@pytest.fixture
def cleaned_table():
    """Factory for the synthetic cleaned table."""
    return synthetic_cleaned_table
