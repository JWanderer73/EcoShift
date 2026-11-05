"""Which columns of the cleaned CSV a demand forecast may start from.

The cleaned table ``data/processed/cleaned_weather_carbon.csv`` has 65
columns. Many of them say the same thing twice:

- The fuel megawatthours are this hour's supply. Supply has to meet
  demand, so they restate the answer, and they are only known after the
  hour has happened. Carbon intensity is a formula of them.
- ``temp``, ``radiation``, and ``wind_10m`` are exactly the mean of the
  five city columns. ``radiation_fresno`` is a copy of Fresno's
  shortwave radiation. Shortwave radiation is exactly direct plus
  diffuse radiation.
- ``is_day`` is the clock. Sunlight in one city moves with sunlight in
  every other city (correlation 0.94 to 0.99). Inland humidity mirrors
  inland temperature.

``DROPPED`` lists every removed column with its reason. The rest of this
module finds those relationships from the data, so the audit notebook and
the tests can check that the list is still right.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from src.carbon_data import CITIES

TARGET = "demand_mwh"

# CAISO's own day-ahead forecast of the target. It is kept as the number
# to beat. It is not a model input.
BENCHMARK_COLUMNS = {"demand_forecast_mwh": "benchmark_caiso_forecast_mwh"}

CITY_NAMES = [city for city, _, _ in CITIES]

FUEL_COLUMNS = [
    "ng_mwh",
    "coal_mwh",
    "oil_mwh",
    "solar_mwh",
    "wind_generation_mwh",
    "hydro_mwh",
    "nuclear_mwh",
    "geothermal_mwh",
]

# Two cities whose humidity is mostly their temperature read backwards.
HUMIDITY_DROPPED_CITIES = ["fresno", "sacramento"]

# Either side of this, a pair of features is "the same column twice".
DROP_CORRELATION = 0.95
REVIEW_CORRELATION = 0.90


def _dropped() -> dict[str, str]:
    reasons: dict[str, str] = {}
    for column in FUEL_COLUMNS:
        reasons[column] = "this hour's supply; it has to meet demand, so it restates the answer"
    reasons["carbon_intensity_g_per_kwh"] = "a formula of the fuel columns"
    reasons["temp"] = "exact mean of the five city temperatures"
    reasons["radiation"] = "exact mean of the five city shortwave radiation columns"
    reasons["wind_10m"] = "exact mean of the five city wind speeds"
    reasons["radiation_fresno"] = "exact copy of fresno_shortwave_radiation"
    for city in CITY_NAMES:
        reasons[f"{city}_direct_radiation"] = "exactly shortwave minus diffuse radiation"
        reasons[f"{city}_is_day"] = "a function of the clock, the date, and the location"
        reasons[f"{city}_shortwave_radiation"] = "cities correlate 0.94 to 0.99; replaced by sun_shortwave_mean"
        reasons[f"{city}_diffuse_radiation"] = "replaced by sun_diffuse_mean, the five-city mean"
        reasons[f"{city}_wind_direction_10m"] = "degrees wrap at 360; replaced by sine and cosine"
    for city in HUMIDITY_DROPPED_CITIES:
        reasons[f"{city}_relative_humidity_2m"] = f"correlates 0.90 or more with {city} temperature"
    return reasons


DROPPED: dict[str, str] = _dropped()

# Weather columns that survive the audit, all measured at the same hour.
# The dataset builder lags them or uses them as they are, by variant.
FEATURE_SOURCE_COLUMNS = (
    [f"{city}_temperature_2m" for city in CITY_NAMES]
    + [f"{city}_relative_humidity_2m" for city in CITY_NAMES if city not in HUMIDITY_DROPPED_CITIES]
    + [f"{city}_wind_speed_10m" for city in CITY_NAMES]
    + [f"{city}_wind_dir_sin" for city in CITY_NAMES]
    + [f"{city}_wind_dir_cos" for city in CITY_NAMES]
    + [f"{city}_cloud_cover" for city in CITY_NAMES]
    + [f"{city}_precipitation" for city in CITY_NAMES]
    + ["sun_shortwave_mean", "sun_diffuse_mean"]
)


def apply_audit(raw: pd.DataFrame) -> pd.DataFrame:
    """Drop the columns in ``DROPPED`` and build their replacements.

    Args:
        raw: The cleaned CSV, indexed by UTC hour.

    Returns:
        The target, the CAISO benchmark, and ``FEATURE_SOURCE_COLUMNS``,
        all at the same hour. Nothing is lagged yet.
    """
    needed = [TARGET, *BENCHMARK_COLUMNS]
    for city in CITY_NAMES:
        needed += [
            f"{city}_temperature_2m",
            f"{city}_relative_humidity_2m",
            f"{city}_wind_speed_10m",
            f"{city}_wind_direction_10m",
            f"{city}_shortwave_radiation",
            f"{city}_diffuse_radiation",
            f"{city}_cloud_cover",
            f"{city}_precipitation",
        ]
    missing = [column for column in needed if column not in raw.columns]
    if missing:
        raise ValueError(f"cleaned table is missing columns: {missing}")

    frame = raw.copy()
    for city in CITY_NAMES:
        radians = np.deg2rad(frame[f"{city}_wind_direction_10m"].astype(float))
        frame[f"{city}_wind_dir_sin"] = np.sin(radians)
        frame[f"{city}_wind_dir_cos"] = np.cos(radians)
    frame["sun_shortwave_mean"] = frame[[f"{city}_shortwave_radiation" for city in CITY_NAMES]].mean(axis=1)
    frame["sun_diffuse_mean"] = frame[[f"{city}_diffuse_radiation" for city in CITY_NAMES]].mean(axis=1)
    frame = frame.rename(columns=BENCHMARK_COLUMNS)
    keep = [TARGET, *BENCHMARK_COLUMNS.values(), *FEATURE_SOURCE_COLUMNS]
    return frame.loc[:, keep]


def find_identities(frame: pd.DataFrame, tolerance: float = 1e-6) -> pd.DataFrame:
    """Find columns that are exact copies, means, or sums of other columns.

    Three checks:

    - a copy: two columns never differ by more than ``tolerance``
    - a mean: a column equals the row mean of one weather field across cities
    - a sum: inside one city, a column equals the sum of two others

    Args:
        frame: Numeric columns. Rows with any missing value are skipped.
        tolerance: Largest absolute difference still counted as equal.

    Returns:
        One row per identity: ``column``, ``kind``, ``of``, ``max_abs_diff``.
    """
    numeric = frame.select_dtypes("number").dropna()
    rows = []

    for left, right in combinations(numeric.columns, 2):
        gap = float((numeric[left] - numeric[right]).abs().max())
        if gap <= tolerance:
            rows.append({"column": left, "kind": "copy", "of": right, "max_abs_diff": gap})

    fields: dict[str, list[str]] = {}
    for column in numeric.columns:
        for city in CITY_NAMES:
            if column.startswith(f"{city}_"):
                fields.setdefault(column[len(city) + 1 :], []).append(column)
    city_columns = {column for members in fields.values() for column in members}
    for field, members in fields.items():
        if len(members) < 2:
            continue
        mean = numeric[members].mean(axis=1)
        for column in numeric.columns:
            if column in city_columns:
                continue
            gap = float((numeric[column] - mean).abs().max())
            if gap <= tolerance:
                rows.append({"column": column, "kind": "mean", "of": f"{field} across cities", "max_abs_diff": gap})

    for city in CITY_NAMES:
        members = [column for column in numeric.columns if column.startswith(f"{city}_")]
        for column in members:
            others = [other for other in members if other != column]
            for left, right in combinations(others, 2):
                gap = float((numeric[column] - numeric[left] - numeric[right]).abs().max())
                if gap <= tolerance:
                    rows.append({"column": column, "kind": "sum", "of": f"{left} + {right}", "max_abs_diff": gap})

    return pd.DataFrame(rows, columns=["column", "kind", "of", "max_abs_diff"])


def find_correlated_pairs(frame: pd.DataFrame, threshold: float = REVIEW_CORRELATION) -> pd.DataFrame:
    """Every pair of columns whose absolute Pearson correlation is at least ``threshold``.

    Constant columns are skipped, because their correlation is undefined.

    Returns:
        Columns ``a``, ``b``, ``r`` (absolute value), strongest first.
    """
    numeric = frame.select_dtypes("number")
    numeric = numeric.loc[:, numeric.nunique(dropna=True) > 1]
    corr = numeric.corr().abs()
    rows = []
    for left, right in combinations(corr.columns, 2):
        value = corr.loc[left, right]
        if np.isfinite(value) and value >= threshold:
            rows.append({"a": left, "b": right, "r": float(value)})
    table = pd.DataFrame(rows, columns=["a", "b", "r"])
    return table.sort_values("r", ascending=False, ignore_index=True)


def resolve_correlated(frame: pd.DataFrame, target: pd.Series, threshold: float = DROP_CORRELATION) -> dict[str, str]:
    """Drop one column from every pair at or above ``threshold``.

    Pairs are handled strongest first. Of the two, the column less
    correlated with ``target`` is dropped. A pair whose member is already
    dropped is skipped.

    Args:
        frame: Candidate feature columns.
        target: The value being forecast, aligned to ``frame``.
        threshold: Absolute correlation that counts as a duplicate.

    Returns:
        Dropped column mapped to the reason, naming the column it duplicated.
    """
    pairs = find_correlated_pairs(frame, threshold)
    relevance = frame.select_dtypes("number").corrwith(target).abs()
    dropped: dict[str, str] = {}
    for left, right, value in pairs.itertuples(index=False):
        if left in dropped or right in dropped:
            continue
        loser, winner = (left, right) if relevance.get(left, 0.0) < relevance.get(right, 0.0) else (right, left)
        dropped[loser] = f"correlates {value:.3f} with {winner}"
    return dropped


def review_pairs(frame: pd.DataFrame) -> pd.DataFrame:
    """Pairs between ``REVIEW_CORRELATION`` and ``DROP_CORRELATION``: kept, but worth a look."""
    pairs = find_correlated_pairs(frame, REVIEW_CORRELATION)
    return pairs.loc[pairs["r"] < DROP_CORRELATION].reset_index(drop=True)
