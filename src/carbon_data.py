"""Hourly CAISO carbon-intensity panel for the training notebooks.

The target is an estimate of grams of CO₂ per kWh, built from EIA generation
by fuel. Fuel megawatthours are not written into the cached modeling table.
They are the ingredients of the target, so a model that saw them would be
reproducing the formula rather than forecasting it.

Weather is the Open-Meteo archive for five California cities. Fresno radiation
is kept on its own because it tracked CAISO solar more closely than the coastal
cities. Temperature and wind are the mean of the five cities, which is the
series that lined up with demand.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# kg CO₂ per MWh, equal to g CO₂ per kWh.
# EPA combustion factors (kg/MMBtu) times a typical heat rate (MMBtu/MWh):
# gas 53.06 * 7.4, coal 95.5 * 10.5, distillate oil 73.96 * 11.
EMITTING_KG_PER_MWH = {"NG": 393.0, "COL": 1003.0, "OIL": 814.0}
ZERO_CARBON = {"SUN", "WND", "WAT", "NUC", "GEO"}

HOURLY_START = "2026-01-01T00"
HOURLY_END = "2026-10-18T23"
WEATHER_START = "2026-01-01"
WEATHER_END = "2026-10-18"
EIA_PAGE_SIZE = 5000
PANEL_VERSION = 1

CITIES = [
    ("san_diego", 32.7157, -117.1611),
    ("los_angeles", 34.0522, -118.2437),
    ("fresno", 36.7378, -119.7871),
    ("sacramento", 38.5816, -121.4944),
    ("san_francisco", 37.7749, -122.4194),
]
WEATHER_VARS = ["temperature_2m", "shortwave_radiation", "wind_speed_10m"]

PANEL_COLUMNS = [
    "carbon_intensity_g_per_kwh",
    "demand_mwh",
    "demand_forecast_mwh",
    "temp",
    "radiation",
    "radiation_fresno",
    "wind_10m",
]


def repo_root() -> Path:
    """Return the repository root, whether the caller started in it or in notebooks/."""
    here = Path.cwd().resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "requirements.txt").exists() and (candidate / ".env.example").exists():
            return candidate
    return here


def cache_path() -> Path:
    """Path of the cached modeling table. Derived data, safe to rebuild."""
    return repo_root() / "data" / "processed" / "hourly_model_panel.csv"


def carbon_intensity(fuels: pd.DataFrame) -> pd.Series:
    """Estimate gCO₂/kWh from generation by fuel.

    Emitting fuels use the factors in ``EMITTING_KG_PER_MWH``. Nuclear, hydro,
    wind, solar, and geothermal count in the denominator at zero emissions.
    Other fuels and storage are left out. Negative reported generation is
    clipped to zero before the ratio.

    Args:
        fuels: Columns are EIA fuel codes and values are megawatthours.

    Returns:
        Carbon intensity aligned to ``fuels``. Hours with no counted generation
        are missing.
    """
    frame = fuels.copy()
    for fuel in ZERO_CARBON | set(EMITTING_KG_PER_MWH):
        if fuel not in frame.columns:
            frame[fuel] = 0.0
        frame[fuel] = pd.to_numeric(frame[fuel], errors="coerce").fillna(0.0).clip(lower=0.0)
    emissions = sum(frame[fuel] * factor for fuel, factor in EMITTING_KG_PER_MWH.items())
    denominator = frame[list(ZERO_CARBON | set(EMITTING_KG_PER_MWH))].sum(axis=1).replace(0, np.nan)
    intensity = emissions / denominator
    intensity.name = "carbon_intensity_g_per_kwh"
    return intensity


def model_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Add calendar fields and lags, and drop hours that are missing any of them.

    Lags are taken on a complete UTC hourly index, so a missing hour does not
    shorten the lag. ``carbon_lag_1`` is the previous hour. ``carbon_lag_24``
    and the weather lags are the same UTC hour yesterday, which is what a
    day-ahead model is allowed to see. The first 168 hours are dropped because
    of the week-long carbon lag.

    Args:
        panel: Hourly observations indexed in UTC, with ``PANEL_COLUMNS``.

    Returns:
        Modeling table indexed in UTC. Fuel columns are never added.
    """
    missing = [column for column in PANEL_COLUMNS if column not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing columns: {missing}")
    frame = panel.loc[:, PANEL_COLUMNS].sort_index()
    frame.index = pd.to_datetime(frame.index, utc=True).floor("h")
    frame = frame[~frame.index.duplicated(keep="last")]
    full_index = pd.date_range(frame.index.min(), frame.index.max(), freq="h", tz="UTC")
    frame = frame.reindex(full_index)
    local = frame.index.tz_convert("America/Los_Angeles")
    frame["hour_local"] = local.hour.astype(int)
    frame["dow"] = local.dayofweek.astype(int)
    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour_local"] / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour_local"] / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * frame["dow"] / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * frame["dow"] / 7)
    day_of_year = local.dayofyear.to_numpy()
    frame["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)
    lagged = {
        "carbon_lag_1": ("carbon_intensity_g_per_kwh", 1),
        "carbon_lag_24": ("carbon_intensity_g_per_kwh", 24),
        "carbon_lag_168": ("carbon_intensity_g_per_kwh", 168),
        "temp_lag_24": ("temp", 24),
        "radiation_lag_24": ("radiation", 24),
        "radiation_fresno_lag_24": ("radiation_fresno", 24),
        "wind_10m_lag_24": ("wind_10m", 24),
    }
    for name, (source, steps) in lagged.items():
        frame[name] = frame[source].shift(steps)
    model_columns = PANEL_COLUMNS + [
        "hour_local",
        "dow",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "doy_sin",
        "doy_cos",
        *lagged,
    ]
    return frame.dropna(subset=model_columns).loc[:, model_columns]


def load_hourly_panel(refresh: bool = False) -> pd.DataFrame:
    """Load the cached hourly panel, fetching EIA and Open-Meteo on a miss.

    Args:
        refresh: When True, ignore the cache and download again.

    Returns:
        Observations indexed by UTC hour. Columns are ``PANEL_COLUMNS``.
    """
    path = cache_path()
    meta = path.with_suffix(".meta.json")
    if path.exists() and meta.exists() and not refresh:
        recorded = json.loads(meta.read_text())
        if recorded.get("version") == PANEL_VERSION:
            frame = pd.read_csv(path, index_col=0, parse_dates=True)
            frame.index = pd.to_datetime(frame.index, utc=True)
            return frame.loc[:, PANEL_COLUMNS]
    frame = _fetch_hourly_panel()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path)
    meta.write_text(json.dumps({"version": PANEL_VERSION, "rows": int(len(frame))}))
    return frame


def load_model_frame(refresh: bool = False) -> pd.DataFrame:
    """Return the lagged modeling table used by every training notebook."""
    return model_frame(load_hourly_panel(refresh=refresh))


def _fetch_hourly_panel() -> pd.DataFrame:
    load_dotenv(repo_root() / ".env")
    if not os.getenv("EIA_API_KEY"):
        raise RuntimeError("EIA_API_KEY is missing from .env")
    fuel = _eia_pages(
        "electricity/rto/fuel-type-data/data/",
        [
            ("frequency", "hourly"),
            ("data[]", "value"),
            ("facets[respondent][]", "CISO"),
            ("start", HOURLY_START),
            ("end", HOURLY_END),
        ],
    )
    region = _eia_pages(
        "electricity/rto/region-data/data/",
        [
            ("frequency", "hourly"),
            ("data[]", "value"),
            ("facets[respondent][]", "CISO"),
            ("start", HOURLY_START),
            ("end", HOURLY_END),
        ],
    )
    weather = _weather()
    wide_fuel = fuel.pivot_table(index="period", columns="fueltype", values="value", aggfunc="sum")
    wide_region = region.pivot_table(index="period", columns="type", values="value", aggfunc="sum")
    wide_fuel.index = pd.to_datetime(wide_fuel.index, utc=True).floor("h")
    wide_region.index = pd.to_datetime(wide_region.index, utc=True).floor("h")
    for column, label in (("D", "demand"), ("DF", "day-ahead demand forecast")):
        if column not in wide_region.columns:
            raise RuntimeError(f"EIA region data has no {column} ({label}) column")
    panel = pd.DataFrame(
        {
            "carbon_intensity_g_per_kwh": carbon_intensity(wide_fuel),
            "demand_mwh": wide_region["D"],
            "demand_forecast_mwh": wide_region["DF"],
        }
    )
    panel = panel.join(weather, how="inner")
    panel = panel.loc[:, PANEL_COLUMNS].sort_index()
    panel = panel[~panel.index.duplicated(keep="last")]
    return panel.dropna(subset=["carbon_intensity_g_per_kwh"])


def _eia_pages(route: str, params: list) -> pd.DataFrame:
    rows: list[dict] = []
    offset = 0
    total = None
    while True:
        query = [
            ("api_key", os.environ["EIA_API_KEY"]),
            ("offset", str(offset)),
            ("length", str(EIA_PAGE_SIZE)),
            *params,
        ]
        payload = _get_json("https://api.eia.gov/v2/" + route + "?" + urlencode(query))
        response = payload["response"]
        batch = response.get("data") or []
        total = int(response["total"])
        rows.extend(batch)
        offset += len(batch)
        if not batch or offset >= total:
            break
        time.sleep(0.15)
    frame = pd.DataFrame(rows)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    print(f"{route}: {len(frame)} rows (api total {total})")
    return frame


def _weather() -> pd.DataFrame:
    frames = []
    for city, latitude, longitude in CITIES:
        payload = _get_json(
            "https://archive-api.open-meteo.com/v1/archive?"
            + urlencode(
                [
                    ("latitude", str(latitude)),
                    ("longitude", str(longitude)),
                    ("start_date", WEATHER_START),
                    ("end_date", WEATHER_END),
                    ("hourly", ",".join(WEATHER_VARS)),
                    ("timezone", "UTC"),
                ]
            )
        )
        frame = pd.DataFrame(payload["hourly"])
        frame["city"] = city
        frame["time"] = pd.to_datetime(frame["time"], utc=True).dt.floor("h")
        frames.append(frame)
        print(f"weather {city}: {len(frame)} hours")
        time.sleep(0.5)
    weather = pd.concat(frames, ignore_index=True)
    mean = (
        weather.groupby("time", as_index=True)[["temperature_2m", "shortwave_radiation", "wind_speed_10m"]]
        .mean()
        .rename(columns={"temperature_2m": "temp", "shortwave_radiation": "radiation", "wind_speed_10m": "wind_10m"})
    )
    fresno = weather.loc[weather["city"] == "fresno", ["time", "shortwave_radiation"]]
    fresno = fresno.drop_duplicates("time").set_index("time").rename(columns={"shortwave_radiation": "radiation_fresno"})
    return mean.join(fresno, how="left")


def _get_json(url: str, timeout: int = 180) -> dict:
    request = Request(url, headers={"User-Agent": "EcoShift-models/1.0"})
    payload = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503} and attempt < 3:
                time.sleep(65 if exc.code == 429 else 5 * (attempt + 1))
                continue
            route = exc.url.split("?", 1)[0]
            raise RuntimeError(f"Request failed ({exc.code}) for {route}: {detail[:400]}") from None
    if not isinstance(payload, dict):
        raise RuntimeError("empty response")
    if payload.get("error") and "response" not in payload and "hourly" not in payload:
        raise RuntimeError(str(payload.get("reason") or payload.get("error")))
    return payload
