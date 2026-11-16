"""Column names shared by the price dataset, the trainer, and the recommender.

Build, train, and recommend import these names. The strings are the dataset contract.
A price feature has to be at least five days old. Congestion, loss, and the energy
component are the price split into parts, so a column whose name contains one of
those words is refused.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from src.carbon_data import repo_root

TARGET = "lmp_usd_per_mwh"
CAMPUS_ID = "campus_id"
PNODE_ID = "pnode_id"
# Same hour last week. Legal as a feature and as the copy-the-past baseline.
LMP_LAG_168 = "lmp_lag_168"
# A price feature younger than this restates the hour being forecast.
MIN_LAG_HOURS = 120
# Congestion, loss, and energy are the LMP split into parts. Any lag of them is banned.
BANNED_PARTS = ("cong", "loss", "energy", "mcc", "mce", "mcl")
# Inside this distance, a load node outranks a generation node. Both can still be kept.
NODE_TIE_KM = 0.2
# Last block of the modeling table. The correlation check uses only the hours before it.
TEST_DAYS = 28
# Percent error is undefined near zero and below zero. Hours at or under this stay out of it.
PERCENT_PRICE_FLOOR = 5.0
# The cabinet in the Inflect quote. Dollars use this when the command omits --kw.
DEFAULT_KW = 8.0
# No feature in this folder is legal further ahead than this.
HORIZON_DAYS = 5
LOCAL_TZ = "America/Los_Angeles"
HISTORY_START = "2025-11-15"
HISTORY_END = "2026-11-14"
# Named price lags. The week mean also uses the hours between 168 and 336.
LMP_LAGS = (120, 144, 168, 336)
# Seven same-hour lags, starting at five days and stepping one day.
WEEK_LAGS = (120, 144, 168, 192, 216, 240, 264)
WEEK_COLUMN = "lmp_same_hour_week"
LOAD_FEATURE = "load_forecast_7da_mwh"
CALENDAR_FEATURES = (
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "doy_sin",
    "doy_cos",
    "is_holiday",
)
WEATHER_FEATURES = (
    "temperature_forecast_day5",
    "cloud_cover_forecast_day5",
    "wind_speed_forecast_day5",
    "shortwave_forecast_day5",
)
STATIC_FEATURES = (
    "node_latitude",
    "node_longitude",
    "distance_km",
    "node_type_load",
)
EARTH_RADIUS_KM = 6371.0088
# Santa Clara, San Jose, and Fresno are PG&E. Los Angeles is SCE. San Diego is SDG&E.
# The other cities are the same three load zones, by which utility serves them.
_PG_AND_E = (
    "santa clara",
    "san jose",
    "fresno",
    "san francisco",
    "sunnyvale",
    "fremont",
    "rancho cordova",
    "sacramento",
    "mountain view",
    "modesto",
    "stockton",
    "hayward",
    "mcclellan park",
    "san luis obispo",
    "newark",
    "oakland",
    "emeryville",
    "west sacramento",
    "roseville",
    "milpitas",
    "palo alto",
    "citrus heights",
    "petaluma",
    "santa rosa",
)
_SCE = (
    "los angeles",
    "el segundo",
    "irvine",
    "anaheim",
    "redondo beach",
    "santa ana",
    "tustin",
    "burbank",
    "culver city",
    "marina del rey",
    "pasadena",
    "hawthorne",
    "santa fe springs",
    "la mirada",
    "cypress",
    "san bernardino",
    "riverside",
    "menifee",
)
_SDGE = ("san diego",)
DLAP_BY_CITY = {
    **{city: "DLAP_PGAE-APND" for city in _PG_AND_E},
    **{city: "DLAP_SCE-APND" for city in _SCE},
    **{city: "DLAP_SDGE-APND" for city in _SDGE},
}
_LAG_HOURS = re.compile(r"lmp_lag_(\d+)")


def dataset_path():
    """The hourly price modeling table."""
    return repo_root() / "price_windows" / "price_dataset.csv"


def meta_path():
    """Metadata beside the price table: features, campuses, nodes, and the content hash."""
    return dataset_path().with_suffix(".meta.json")


def dlap_for_city(city: str) -> str | None:
    """The load-aggregation node for a city. A label, not one of the five nearest nodes."""
    return DLAP_BY_CITY.get(str(city).strip().casefold())


def feature_columns(include_load: bool = True) -> list[str]:
    """Every column the model may see, in the order the table writes them.

    The seven-day load forecast is omitted when that OASIS pull returned no rows.
    """
    columns = [
        *CALENDAR_FEATURES,
        *[f"lmp_lag_{hours}" for hours in LMP_LAGS],
        WEEK_COLUMN,
        *WEATHER_FEATURES,
        *STATIC_FEATURES,
    ]
    if include_load:
        columns.append(LOAD_FEATURE)
    return columns


def illegal_feature_names(names: list[str]) -> list[str]:
    """Feature names that would leak the price: the target, a component, or a short lag.

    The check is the name. A lag of 120 hours is the youngest price feature allowed.
    """
    refused = []
    for name in names:
        lowered = name.casefold()
        lag = _LAG_HOURS.search(lowered)
        short_lag = lag is not None and int(lag.group(1)) < MIN_LAG_HOURS
        component = any(part in lowered for part in BANNED_PARTS)
        if lowered == TARGET or short_lag or component:
            refused.append(name)
    return refused


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance in kilometers. Inputs are decimal degrees."""
    lat1 = np.radians(np.asarray(lat1, dtype=float))
    lon1 = np.radians(np.asarray(lon1, dtype=float))
    lat2 = np.radians(np.asarray(lat2, dtype=float))
    lon2 = np.radians(np.asarray(lon2, dtype=float))
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    chord = np.sin(delta_lat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(chord))


def nearest_five(latitude: float, longitude: float, nodes: pd.DataFrame) -> pd.DataFrame:
    """The five closest located nodes, ranked.

    When the next node and a load node are within 0.2 km, the load node ranks
    first. The generation node is still eligible for a later rank.
    """
    columns = ["rank", "pnode_id", "node_type", "latitude", "longitude", "distance_km"]
    frame = nodes.loc[:, ["pnode_id", "node_type", "latitude", "longitude"]].dropna().copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame["distance_km"] = haversine_km(latitude, longitude, frame["latitude"].to_numpy(), frame["longitude"].to_numpy())
    remaining = frame.to_dict(orient="records")
    picked = []
    while remaining and len(picked) < 5:
        remaining.sort(key=lambda row: (row["distance_km"], str(row["pnode_id"])))
        nearest = remaining[0]["distance_km"]
        band = [row for row in remaining if row["distance_km"] <= nearest + NODE_TIE_KM]
        loads = [row for row in band if "load" in str(row["node_type"]).casefold()]
        pool = loads or band
        pool.sort(key=lambda row: (row["distance_km"], str(row["pnode_id"])))
        choice = pool[0]
        picked.append(choice)
        remaining = [row for row in remaining if row["pnode_id"] != choice["pnode_id"]]
    result = pd.DataFrame(picked)
    result["rank"] = np.arange(1, len(result) + 1)
    return result.loc[:, columns].reset_index(drop=True)
