"""How ``data/processed/cleaned_weather_carbon.csv`` gets built.

There are two hourly CSVs. They are not the same file.

- ``cleaned_weather_carbon.csv`` is this script. It is the latest 10,000
  hours that have both weather and carbon. It keeps the fuel megawatthours
  and the weather for each city, because it is a dataset.
- ``hourly_model_panel.csv`` is the shorter cache the notebooks use. That
  one is built by ``src/carbon_data.py`` and does not store the fuel columns.

This script does five steps:

1. Download hourly weather for five California cities from Open-Meteo.
2. Download hourly CAISO fuel mix and demand from EIA. This needs
   ``EIA_API_KEY`` in ``.env``.
3. Turn the fuel mix into carbon intensity, in grams of CO2 per kWh.
4. Join weather to carbon and drop any hour that is missing either one.
5. Keep the latest 10,000 complete hours and write the CSV.

The model scripts do not train on the fuel columns. Those columns are how
the carbon number was calculated. Seeing them would let a model copy the
formula instead of forecasting it.

    python -m src.build_cleaned_dataset
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import pandas as pd
from dotenv import load_dotenv

from src.carbon_data import (
    CITIES,
    _eia_pages,
    _get_json,
    carbon_intensity,
    repo_root,
)

# One row per hour, for every city. These are the Open-Meteo field names.
WEATHER_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "cloud_cover",
    "precipitation",
    "is_day",
]

# The download window is wider than 10,000 hours on purpose. Hours that
# fail to join get dropped, and we still want 10,000 complete rows left.
START_DATE = "2025-08-01"
END_DATE = "2026-10-20"
TARGET_ROWS = 10_000

# EIA fuel code -> column name in the CSV. These are the counts behind
# the carbon number. They are saved. They are not model inputs.
FUEL_COLUMNS = {
    "NG": "ng_mwh",
    "COL": "coal_mwh",
    "OIL": "oil_mwh",
    "SUN": "solar_mwh",
    "WND": "wind_generation_mwh",
    "WAT": "hydro_mwh",
    "NUC": "nuclear_mwh",
    "GEO": "geothermal_mwh",
}

OUTPUT = repo_root() / "data" / "processed" / "cleaned_weather_carbon.csv"


def _weather() -> pd.DataFrame:
    """Download one hourly weather table per city and line them up on the hour.

    Each city gets the same fields, with the city name prefixed on the column
    (``fresno_temperature_2m``). Duplicate hours are collapsed. A city-hour
    that is missing any weather field is dropped, so the join later does not
    have to guess.
    """
    frames = []
    for city, latitude, longitude in CITIES:
        payload = _get_json(
            "https://archive-api.open-meteo.com/v1/archive?"
            + urlencode(
                [
                    ("latitude", str(latitude)),
                    ("longitude", str(longitude)),
                    ("start_date", START_DATE),
                    ("end_date", END_DATE),
                    ("hourly", ",".join(WEATHER_VARS)),
                    ("timezone", "UTC"),
                ]
            )
        )
        frame = pd.DataFrame(payload["hourly"])
        frame["time"] = pd.to_datetime(frame.pop("time"), utc=True).dt.floor("h")
        for column in WEATHER_VARS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = (
            frame.drop_duplicates(subset=["time"], keep="last")
            .set_index("time")
            .sort_index()
            .add_prefix(f"{city}_")
        )
        frames.append(frame)
        print(f"weather {city}: {len(frame)} hours")
        time.sleep(0.5)
    weather = pd.concat(frames, axis=1).sort_index()
    weather = weather[~weather.index.duplicated(keep="last")]
    return weather.dropna(subset=list(weather.columns))


def _carbon() -> pd.DataFrame:
    """Download CAISO generation and demand, then compute carbon intensity.

    EIA returns one row per fuel per hour. Those rows are pivoted so each
    hour is one row and each fuel is a column. Carbon intensity is
    emissions divided by generation, using the same factors as the notebooks.
    Demand (``D``) and the day-ahead demand forecast (``DF``) come from a
    second EIA table and are attached to the same hours.
    """
    start = f"{START_DATE}T00"
    end = f"{END_DATE}T23"
    fuel = _eia_pages(
        "electricity/rto/fuel-type-data/data/",
        [
            ("frequency", "hourly"),
            ("data[]", "value"),
            ("facets[respondent][]", "CISO"),
            ("start", start),
            ("end", end),
        ],
    )
    region = _eia_pages(
        "electricity/rto/region-data/data/",
        [
            ("frequency", "hourly"),
            ("data[]", "value"),
            ("facets[respondent][]", "CISO"),
            ("start", start),
            ("end", end),
        ],
    )
    wide_fuel = fuel.pivot_table(index="period", columns="fueltype", values="value", aggfunc="sum")
    wide_region = region.pivot_table(index="period", columns="type", values="value", aggfunc="sum")
    wide_fuel.index = pd.to_datetime(wide_fuel.index, utc=True).floor("h")
    wide_region.index = pd.to_datetime(wide_region.index, utc=True).floor("h")
    wide_fuel = wide_fuel[~wide_fuel.index.duplicated(keep="last")]
    wide_region = wide_region[~wide_region.index.duplicated(keep="last")]
    for column, label in (("D", "demand"), ("DF", "day-ahead demand forecast")):
        if column not in wide_region.columns:
            raise RuntimeError(f"EIA region data has no {column} ({label}) column")

    counts = pd.DataFrame(index=wide_fuel.index)
    for code, name in FUEL_COLUMNS.items():
        if code in wide_fuel.columns:
            counts[name] = pd.to_numeric(wide_fuel[code], errors="coerce").fillna(0.0).clip(lower=0.0)
        else:
            counts[name] = 0.0
    counts.insert(0, "carbon_intensity_g_per_kwh", carbon_intensity(wide_fuel))
    counts["demand_mwh"] = wide_region["D"]
    counts["demand_forecast_mwh"] = wide_region["DF"]
    return counts.sort_index()


def _aggregates(weather: pd.DataFrame) -> pd.DataFrame:
    """Average the five cities into the columns the forecast models use.

    Temperature, sunlight, and wind are the mean of the five cities.
    Fresno sunlight is also kept on its own, because it tracks CAISO solar
    more closely than the coastal cities do.
    """
    temp = weather[[f"{city}_temperature_2m" for city, _, _ in CITIES]].mean(axis=1)
    radiation = weather[[f"{city}_shortwave_radiation" for city, _, _ in CITIES]].mean(axis=1)
    wind = weather[[f"{city}_wind_speed_10m" for city, _, _ in CITIES]].mean(axis=1)
    return pd.DataFrame(
        {
            "temp": temp,
            "radiation": radiation,
            "radiation_fresno": weather["fresno_shortwave_radiation"],
            "wind_10m": wind,
        },
        index=weather.index,
    )


def build() -> pd.DataFrame:
    """Run the five steps above and return the latest 10,000 complete hours."""
    load_dotenv(repo_root() / ".env")
    if not os.getenv("EIA_API_KEY"):
        raise RuntimeError("EIA_API_KEY is missing from .env")

    weather = _weather()
    carbon = _carbon()
    # Inner join: an hour survives only when weather and carbon both have it.
    frame = carbon.join(_aggregates(weather), how="inner").join(weather, how="inner")
    frame = frame.dropna(subset=["carbon_intensity_g_per_kwh", "demand_mwh", "demand_forecast_mwh"])
    frame = frame.sort_index()
    if len(frame) < TARGET_ROWS:
        raise RuntimeError(f"only {len(frame)} complete hours; need about {TARGET_ROWS}")
    frame = frame.iloc[-TARGET_ROWS:]
    frame.index.name = "timestamp"
    return frame


def main() -> None:
    """Build the table and write ``data/processed/cleaned_weather_carbon.csv``."""
    frame = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT)
    print(f"wrote {OUTPUT}")
    print(f"rows: {len(frame)}")
    print(f"columns: {len(frame.columns)}")
    print(f"from {frame.index.min()} to {frame.index.max()}")


if __name__ == "__main__":
    main()
