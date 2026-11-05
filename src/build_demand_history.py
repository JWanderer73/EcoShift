"""Pull years of hourly CAISO demand and weather, then rebuild the demand dataset.

``cleaned_weather_carbon.csv`` keeps the latest 10,000 hours, about 14
months. That is one summer, so a tree model has almost no hot days to
learn from. This script pulls the same hourly series from when EIA-930
hourly CAISO demand begins (2019) through the latest complete day, joins
Open-Meteo weather for the five cities, and writes the demand datasets
from that table.

Only demand, CAISO's own demand forecast, and the weather columns the
audit uses are downloaded. The fuel mix is not, because it restates
demand for the same hour.

Hours with demand outside 10,000 to 60,000 MWh are dropped. CAISO's
hourly load sits well inside that range, and values outside it are
bad reports rather than real hours.

    python -m src.build_demand_history
    python -m src.build_demand_history --refresh
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
from dotenv import load_dotenv

from src.build_demand_dataset import VARIANTS, write
from src.carbon_data import CITIES, _eia_pages, _get_json, repo_root

# Hourly CAISO demand on EIA's API starts in 2019. 2018 returns no rows.
HISTORY_START = "2019-01-01"
HISTORY_END = "2026-11-04"
# CAISO hourly demand is about 18,000 to 52,000 MWh. Outside this is a bad report.
DEMAND_MIN_MWH = 10_000.0
DEMAND_MAX_MWH = 60_000.0

WEATHER_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "shortwave_radiation",
    "diffuse_radiation",
    "cloud_cover",
    "precipitation",
]


def history_path() -> Path:
    """The long hourly table, before the audit and the lags."""
    return repo_root() / "data" / "processed" / "demand_history_raw.csv"


def _years(start: str, end: str) -> list[tuple[str, str]]:
    """Split a date range into calendar years, so one request cannot be huge."""
    first = pd.Timestamp(start)
    last = pd.Timestamp(end)
    spans = []
    for year in range(first.year, last.year + 1):
        span_start = max(first, pd.Timestamp(f"{year}-01-01"))
        span_end = min(last, pd.Timestamp(f"{year}-12-31"))
        spans.append((span_start.strftime("%Y-%m-%d"), span_end.strftime("%Y-%m-%d")))
    return spans


def _demand() -> pd.DataFrame:
    """Hourly CAISO demand and the day-ahead demand forecast, one row per hour."""
    frames = []
    for start, end in _years(HISTORY_START, HISTORY_END):
        region = _eia_pages(
            "electricity/rto/region-data/data/",
            [
                ("frequency", "hourly"),
                ("data[]", "value"),
                ("facets[respondent][]", "CISO"),
                ("facets[type][]", "D"),
                ("facets[type][]", "DF"),
                ("start", f"{start}T00"),
                ("end", f"{end}T23"),
            ],
        )
        if not region.empty:
            frames.append(region)
        time.sleep(0.3)
    if not frames:
        raise RuntimeError("EIA returned no CAISO demand hours")
    region = pd.concat(frames, ignore_index=True)
    wide = region.pivot_table(index="period", columns="type", values="value", aggfunc="last")
    wide.index = pd.to_datetime(wide.index, utc=True).floor("h")
    wide = wide[~wide.index.duplicated(keep="last")].sort_index()
    if "D" not in wide.columns:
        raise RuntimeError("EIA region data has no D (demand) column")
    demand = pd.DataFrame({"demand_mwh": pd.to_numeric(wide["D"], errors="coerce")}, index=wide.index)
    if "DF" in wide.columns:
        demand["demand_forecast_mwh"] = pd.to_numeric(wide["DF"], errors="coerce")
    else:
        demand["demand_forecast_mwh"] = float("nan")
    return demand


def _weather() -> pd.DataFrame:
    """Hourly weather at the five cities, one column per city and measurement."""
    frames = []
    for city, latitude, longitude in CITIES:
        years = []
        for start, end in _years(HISTORY_START, HISTORY_END):
            payload = _get_json(
                "https://archive-api.open-meteo.com/v1/archive?"
                + urlencode(
                    [
                        ("latitude", str(latitude)),
                        ("longitude", str(longitude)),
                        ("start_date", start),
                        ("end_date", end),
                        ("hourly", ",".join(WEATHER_VARS)),
                        ("timezone", "UTC"),
                    ]
                )
            )
            year = pd.DataFrame(payload["hourly"])
            year["time"] = pd.to_datetime(year.pop("time"), utc=True).dt.floor("h")
            for column in WEATHER_VARS:
                year[column] = pd.to_numeric(year[column], errors="coerce")
            years.append(year)
            print(f"weather {city} {start[:4]}: {len(year)} hours")
            time.sleep(0.4)
        frame = pd.concat(years, ignore_index=True)
        frame = frame.drop_duplicates(subset=["time"], keep="last").set_index("time").sort_index()
        frames.append(frame.add_prefix(f"{city}_"))
    weather = pd.concat(frames, axis=1).sort_index()
    return weather[~weather.index.duplicated(keep="last")]


def _clean(demand: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """Join on the hour and drop demand values outside the possible range."""
    frame = demand.join(weather, how="inner").sort_index()
    possible = frame["demand_mwh"].between(DEMAND_MIN_MWH, DEMAND_MAX_MWH)
    dropped = int((~possible).sum())
    if dropped:
        print(f"dropped {dropped} hours with demand outside {DEMAND_MIN_MWH:.0f} to {DEMAND_MAX_MWH:.0f} MWh")
    frame = frame.loc[possible]
    frame.index.name = "timestamp"
    return frame


def fetch(refresh: bool = False) -> pd.DataFrame:
    """Download the long table, or read it back if it was already saved."""
    path = history_path()
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        print(f"using cached {path} ({len(frame)} hours)")
        return frame
    load_dotenv(repo_root() / ".env")
    if not os.getenv("EIA_API_KEY"):
        raise RuntimeError("EIA_API_KEY is missing from .env")
    frame = _clean(_demand(), _weather())
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path)
    print(f"wrote {path}")
    print(f"rows: {len(frame)}, {frame.index.min()} to {frame.index.max()}")
    return frame


def main() -> None:
    """Download the history and rebuild both demand datasets from it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="download again even if the table is cached")
    args = parser.parse_args()
    frame = fetch(refresh=args.refresh)
    for variant in VARIANTS:
        write(variant, source=history_path())
    print(f"history hours: {len(frame)}")


if __name__ == "__main__":
    main()
