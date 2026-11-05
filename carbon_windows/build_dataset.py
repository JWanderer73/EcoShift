"""Build the hourly CAISO carbon-intensity table.

The target is grams of CO₂ per kilowatt-hour. It is computed from the
EIA-930 hourly fuel mix and the EPA emission factors in
``src.carbon_data``. The fuel megawatt-hours are the ingredients of that
number, so they are not written into the modeling table.

Weather comes from the Open-Meteo history already saved by
``python -m src.build_demand_history``. This script does not download
weather again. CAISO's day-ahead demand forecast is taken from that same
file. It is a legal input: it is not part of the carbon formula, and it
is published before the hour.

Every Open-Meteo column and the fuel lags are the same hour yesterday.
CAISO's day-ahead solar and wind forecasts are for the target hour, and
they are published the afternoon before, so a model that uses them is
still legal 24 hours ahead and not beyond that. City wind does not track
the passes where CAISO's wind actually is.

    python -m carbon_windows.build_dataset
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.build_demand_dataset import LOCAL_TZ, content_hash, us_holidays
from src.build_demand_history import HISTORY_END, HISTORY_START, _years, history_path
from src.carbon_data import EMITTING_KG_PER_MWH, ZERO_CARBON, _eia_pages, carbon_intensity, repo_root

TARGET = "carbon_intensity_g_per_kwh"
LOCATION = "CISO"
# Hours outside this range are bad reports. CAISO intensity sits well inside it.
INTENSITY_MIN = 0.0
INTENSITY_MAX = 1100.0
WEATHER_LAG_HOURS = 24
FUEL_CODES = tuple(EMITTING_KG_PER_MWH) + tuple(sorted(ZERO_CARBON))

CITIES = ["san_diego", "los_angeles", "fresno", "sacramento", "san_francisco"]
TEMP_CITIES = ["san_diego", "los_angeles", "fresno", "san_francisco"]
# Yesterday's mix. Same-hour megawatthours stay out of the table.
# Geothermal is missing from the EIA feed until December 2025, so it is not a feature.
LAGGED_FUELS = ("NG", "SUN", "WND", "WAT", "NUC")
# OASIS has no day-ahead renewable forecast before July 2023. Later hours
# leave these two columns empty, and XGBoost treats the empty cells as missing.
FORECAST_START = "2023-07-01"
FORECAST_COLUMNS = ("solar_forecast_mw", "wind_forecast_mw")
# A missing forecast, or a fuel the feed did not report that hour, stays empty.
# XGBoost splits around missing values. The hour itself is still usable.
OPTIONAL_FEATURES = set(FORECAST_COLUMNS) | {f"generation_{fuel.lower()}_lag_24" for fuel in LAGGED_FUELS}

# Same-hour supply. Seeing any of these would let the model copy the formula.
BANNED_FEATURES = set(FUEL_CODES) | {
    TARGET,
    "demand_mwh",
    "ng_mwh",
    "coal_mwh",
    "oil_mwh",
    "solar_mwh",
    "wind_generation_mwh",
    "hydro_mwh",
    "nuclear_mwh",
    "geothermal_mwh",
}

DROPPED = {
    "fuel megawatthours": "they are the ingredients of carbon intensity for the same hour",
    "demand_mwh": "known only as the hour happens; the day-ahead forecast is the legal demand input",
    "sacramento_temperature_2m": "moves with Fresno temperature",
    "fresno_relative_humidity_2m": "mirrors Fresno temperature",
    "sacramento_relative_humidity_2m": "mirrors Sacramento temperature",
    "per-city sunlight": "the five cities move together; replaced by sun_shortwave_mean and sun_diffuse_mean",
    "direct radiation": "shortwave radiation is direct plus diffuse",
    "wind direction": "the demand audit found it was mostly the daily clock",
    "precipitation": "rare at these cities and weak next to cloud cover",
    "is_day": "a function of the clock",
}


def cache_dir():
    """Downloaded pages that are expensive to fetch and safe to rebuild."""
    return repo_root() / "carbon_windows" / "cache"


def dataset_path():
    """The carbon modeling table."""
    return repo_root() / "carbon_windows" / "carbon_dataset.csv"


def meta_path():
    """Metadata beside the carbon table."""
    return dataset_path().with_suffix(".meta.json")


def _fuels() -> pd.DataFrame:
    """Hourly CAISO generation by fuel, one column per EIA fuel code."""
    frames = []
    for start, end in _years(HISTORY_START, HISTORY_END):
        page = _eia_pages(
            "electricity/rto/fuel-type-data/data/",
            [
                ("frequency", "hourly"),
                ("data[]", "value"),
                ("facets[respondent][]", LOCATION),
                ("start", f"{start}T00"),
                ("end", f"{end}T23"),
            ],
        )
        if not page.empty:
            frames.append(page)
        time.sleep(0.3)
    if not frames:
        raise RuntimeError("EIA returned no CAISO fuel-mix hours")
    raw = pd.concat(frames, ignore_index=True)
    wide = raw.pivot_table(index="period", columns="fueltype", values="value", aggfunc="last")
    wide.index = pd.to_datetime(wide.index, utc=True).floor("h")
    wide = wide[~wide.index.duplicated(keep="last")].sort_index()
    path = cache_dir() / "fuels.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_csv(path)
    return wide


def _cached_fuels() -> pd.DataFrame:
    """Fuel mix from the local cache, or a fresh EIA download when the cache is missing."""
    path = cache_dir() / "fuels.csv"
    if path.exists():
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        print(f"fuel mix cache: {len(frame)} hours")
        return frame
    return _fuels()


def _oasis_chunk(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """One OASIS day-ahead renewable forecast request. Empty when that span has no rows."""
    start_text = start.strftime("%Y%m%dT%H:%M-0000")
    end_text = end.strftime("%Y%m%dT%H:%M-0000")
    url = (
        "http://oasis.caiso.com/oasisapi/SingleZip?queryname=SLD_REN_FCST"
        f"&startdatetime={start_text}&enddatetime={end_text}"
        "&market_run_id=DAM&version=1&resultformat=6"
    )
    request = Request(url, headers={"User-Agent": "ecoshift-carbon"})
    for attempt in range(5):
        try:
            raw = urlopen(request, timeout=90).read()
            break
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            time.sleep(15 * (attempt + 1))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = archive.namelist()[0]
        payload = archive.read(name)
    if name.endswith(".xml") or payload.startswith(b"<?xml"):
        if b"No data returned" in payload:
            return pd.DataFrame(columns=list(FORECAST_COLUMNS))
        text = payload.decode("utf-8", "replace")
        raise RuntimeError(f"OASIS refused {start_text} to {end_text}: {text[text.find('ERR_DESC'):text.find('ERR_DESC')+180]}")
    frame = pd.read_csv(io.BytesIO(payload))
    frame["timestamp"] = pd.to_datetime(frame["INTERVALSTARTTIME_GMT"], utc=True)
    wide = frame.pivot_table(index="timestamp", columns="RENEWABLE_TYPE", values="MW", aggfunc="sum")
    wide = wide.rename(columns={"Solar": "solar_forecast_mw", "Wind": "wind_forecast_mw"})
    for column in FORECAST_COLUMNS:
        if column not in wide.columns:
            wide[column] = np.nan
    return wide.loc[:, list(FORECAST_COLUMNS)]


def renewable_forecasts() -> pd.DataFrame:
    """CAISO day-ahead solar and wind, summed across NP15, SP15, and ZP26.

    The day-ahead market publishes these the afternoon before the operating
    day. They are the forecast for the target hour, not yesterday's weather.
    OASIS allows about a month per request and answers 429 when asked faster
    than that, so each chunk is cached.
    """
    folder = cache_dir() / "renewables"
    folder.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(FORECAST_START, tz="UTC")
    stop = pd.Timestamp(HISTORY_END, tz="UTC") + pd.Timedelta(days=1)
    frames = []
    cursor = start
    while cursor < stop:
        chunk_end = min(cursor + pd.Timedelta(days=28), stop)
        cache = folder / f"{cursor.strftime('%Y%m%d')}_{chunk_end.strftime('%Y%m%d')}.csv"
        if cache.exists() and cache.stat().st_size > 80:
            piece = pd.read_csv(cache, index_col=0, parse_dates=True)
            piece.index = pd.to_datetime(piece.index, utc=True)
        else:
            piece = _oasis_chunk(cursor, chunk_end)
            # A span that crosses the daylight-saving change can come back empty
            # even though each week of it has rows. Ask for those weeks instead.
            if piece.empty and chunk_end - cursor > pd.Timedelta(days=7):
                weeks = []
                week_start = cursor
                while week_start < chunk_end:
                    week_end = min(week_start + pd.Timedelta(days=7), chunk_end)
                    week = _oasis_chunk(week_start, week_end)
                    if not week.empty:
                        weeks.append(week)
                    time.sleep(4)
                    week_start = week_end
                if weeks:
                    piece = pd.concat(weeks)
            piece.to_csv(cache)
            print(f"renewables {cursor.date()} to {chunk_end.date()}: {len(piece)} hours")
            time.sleep(4)
        if not piece.empty:
            frames.append(piece)
        cursor = chunk_end
    if not frames:
        raise RuntimeError("CAISO returned no day-ahead renewable forecasts")
    frame = pd.concat(frames).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame


def _weather_columns(history: pd.DataFrame) -> pd.DataFrame:
    """The Open-Meteo columns this model is allowed to see, still at the same hour."""
    missing = []
    for city in CITIES:
        for field in ("shortwave_radiation", "diffuse_radiation", "wind_speed_10m", "cloud_cover"):
            name = f"{city}_{field}"
            if name not in history.columns:
                missing.append(name)
    for city in TEMP_CITIES:
        name = f"{city}_temperature_2m"
        if name not in history.columns:
            missing.append(name)
    if "demand_forecast_mwh" not in history.columns:
        missing.append("demand_forecast_mwh")
    if missing:
        raise RuntimeError(f"demand history is missing columns: {missing}")
    frame = pd.DataFrame(index=history.index)
    frame["sun_shortwave_mean"] = history[[f"{city}_shortwave_radiation" for city in CITIES]].mean(axis=1)
    frame["sun_diffuse_mean"] = history[[f"{city}_diffuse_radiation" for city in CITIES]].mean(axis=1)
    for city in CITIES:
        frame[f"{city}_wind_speed_10m"] = history[f"{city}_wind_speed_10m"]
        frame[f"{city}_cloud_cover"] = history[f"{city}_cloud_cover"]
    for city in TEMP_CITIES:
        frame[f"{city}_temperature_2m"] = history[f"{city}_temperature_2m"]
    frame["demand_forecast_mwh"] = history["demand_forecast_mwh"]
    return frame


def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Clock features in Pacific time, including the US holiday flag."""
    local = index.tz_convert(LOCAL_TZ)
    hour = local.hour.to_numpy()
    dow = local.dayofweek.to_numpy()
    day_of_year = local.dayofyear.to_numpy()
    holidays = us_holidays(range(int(local.year.min()), int(local.year.max()) + 1))
    return pd.DataFrame(
        {
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "dow_sin": np.sin(2 * np.pi * dow / 7),
            "dow_cos": np.cos(2 * np.pi * dow / 7),
            "doy_sin": np.sin(2 * np.pi * day_of_year / 365.25),
            "doy_cos": np.cos(2 * np.pi * day_of_year / 365.25),
            "is_holiday": np.isin(local.date, list(holidays)).astype(float),
        },
        index=index,
    )


def build(fuels: pd.DataFrame, history: pd.DataFrame, forecasts: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Join fuel-mix carbon to weather and keep only columns known a day ahead.

    Args:
        fuels: EIA fuel codes, megawatthours, indexed by UTC hour.
        history: The Open-Meteo and demand table, indexed by UTC hour.
        forecasts: CAISO day-ahead solar and wind, indexed by UTC hour.

    Returns:
        The modeling table and its metadata. Same-hour fuel columns are not in the table.
    """
    intensity = carbon_intensity(fuels).rename(TARGET)
    weather = _weather_columns(history)
    frame = pd.concat([intensity, weather], axis=1, join="inner").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    full = pd.date_range(frame.index.min(), frame.index.max(), freq="h", tz="UTC")
    frame = frame.reindex(full)
    possible = frame[TARGET].between(INTENSITY_MIN, INTENSITY_MAX)
    frame.loc[~possible, TARGET] = np.nan

    weather_names = [column for column in weather.columns if column != "demand_forecast_mwh"]
    lagged = {f"{column}_lag_{WEATHER_LAG_HOURS}": frame[column].shift(WEATHER_LAG_HOURS) for column in weather_names}
    frame = frame.drop(columns=weather_names).assign(**lagged)
    generation = fuels.reindex(frame.index)
    for fuel in LAGGED_FUELS:
        values = generation[fuel] if fuel in generation.columns else 0.0
        frame[f"generation_{fuel.lower()}_lag_24"] = pd.to_numeric(values, errors="coerce").shift(24)
    generation_lags = [f"generation_{fuel.lower()}_lag_24" for fuel in LAGGED_FUELS]
    frame["carbon_lag_24"] = frame[TARGET].shift(24)
    frame["carbon_lag_168"] = frame[TARGET].shift(168)
    frame["carbon_same_hour_week"] = sum(frame[TARGET].shift(hours) for hours in range(24, 169, 24)) / 7
    demand = history["demand_mwh"].copy()
    demand.index = pd.to_datetime(demand.index, utc=True)
    frame["demand_lag_24"] = demand.reindex(frame.index).shift(24)
    frame["demand_change_mwh"] = frame["demand_forecast_mwh"] - frame["demand_lag_24"]
    frame = frame.join(forecasts.reindex(frame.index))
    calendar = _calendar(frame.index)
    frame = frame.join(calendar)

    features = [
        *calendar.columns,
        "carbon_lag_24",
        "carbon_lag_168",
        "carbon_same_hour_week",
        "demand_forecast_mwh",
        "demand_lag_24",
        "demand_change_mwh",
        *generation_lags,
        *FORECAST_COLUMNS,
        *lagged,
    ]
    banned = sorted(set(features) & BANNED_FEATURES)
    if banned:
        raise RuntimeError(f"features include the carbon formula or the target: {banned}")
    required = [column for column in features if column not in OPTIONAL_FEATURES]
    table = frame.dropna(subset=[TARGET, *required]).loc[:, [TARGET, *features]]
    table.index.name = "timestamp"
    meta = {
        "location": LOCATION,
        "target": TARGET,
        "target_unit": "gCO2/kWh",
        "horizon_hours": 24,
        "features": features,
        "dropped": DROPPED,
        "emission_factors_kg_per_mwh": EMITTING_KG_PER_MWH,
        "emission_factor_source": (
            "EPA combustion factors in kg/MMBtu times a typical heat rate in MMBtu/MWh: "
            "gas 53.06 * 7.4, coal 95.5 * 10.5, distillate oil 73.96 * 11. "
            "A kg per MWh is the same number as a g per kWh. "
            "Nuclear, hydro, wind, solar, and geothermal are 0. "
            "eGRID publishes yearly plant rates, so it is not an hourly column."
        ),
        "zero_carbon_fuels": sorted(ZERO_CARBON),
        "weather_lag_hours": WEATHER_LAG_HOURS,
        "renewable_forecast": (
            "CAISO OASIS SLD_REN_FCST, day-ahead market, solar and wind summed across "
            "NP15, SP15, and ZP26. Published the afternoon before the operating day. "
            "Hours before July 2023 have no forecast and are left empty on purpose."
        ),
        "rows": int(len(table)),
        "start": str(table.index.min()),
        "end": str(table.index.max()),
        "content_hash": content_hash(table),
    }
    return table, meta


def main() -> None:
    """Download the fuel mix, join the saved weather, and write the carbon table."""
    load_dotenv(repo_root() / ".env")
    if not os.getenv("EIA_API_KEY"):
        raise RuntimeError("EIA_API_KEY is missing from .env")
    source = history_path()
    if not source.exists():
        raise RuntimeError(f"{source} is missing. Build it with: python -m src.build_demand_history")
    history = pd.read_csv(source, index_col=0, parse_dates=True)
    history.index = pd.to_datetime(history.index, utc=True)
    table, meta = build(_cached_fuels(), history, renewable_forecasts())
    path = dataset_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path)
    meta["source_weather"] = source.name
    meta_path().write_text(json.dumps(meta, indent=2))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"wrote {path}")
    print(f"rows: {meta['rows']}, features: {len(meta['features'])}, {meta['start']} to {meta['end']}")
    print(f"file sha256: {digest}")


if __name__ == "__main__":
    main()
