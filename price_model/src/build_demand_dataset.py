"""Build the demand dataset the model scripts train on.

The question is: how many megawatthours will CAISO serve in a given hour?

Steps:

1. Read ``data/processed/cleaned_weather_carbon.csv``.
2. Drop the columns in ``src.column_audit.DROPPED``: the fuel columns and
   carbon (this hour's supply restates demand), exact copies and means,
   and near-duplicates. CAISO's own forecast is kept as
   ``benchmark_caiso_forecast_mwh``, the number to beat. It is not a feature.
3. Add the clock (hour, weekday, day of year as sine and cosine) and a
   US holiday flag, all in Pacific time.
4. Add demand at the same hour yesterday and last week.
5. Add weather. There are two variants:

   - ``honest``: weather at the same hour yesterday. Every feature is
     known 24 hours before the hour being forecast.
   - ``weather_forecast_standin``: weather at the hour being forecast. A
     real forecast would use a weather forecast for that hour, which is
     not pulled yet. Actual weather stands in for a perfect one, so this
     variant is an upper bound and is never reported as the real score.

6. Drop any feature that still correlates 0.95 or more with another,
   keeping the one closer to demand.
7. Write the table and a ``.meta.json`` beside it: features, dropped
   columns with reasons, rows, date range, and a content hash.

    python -m src.build_demand_dataset
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.carbon_data import repo_root
from src.column_audit import (
    BENCHMARK_COLUMNS,
    DROPPED,
    FEATURE_SOURCE_COLUMNS,
    TARGET,
    apply_audit,
    resolve_correlated,
)

BENCHMARK = BENCHMARK_COLUMNS["demand_forecast_mwh"]
VARIANTS = ("honest", "weather_forecast_standin")
DEFAULT_VARIANT = "honest"
LOCAL_TZ = "America/Los_Angeles"

CALENDAR_COLUMNS = ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "doy_sin", "doy_cos", "is_holiday"]
DEMAND_LAGS = {"demand_lag_24": 24, "demand_lag_168": 168}
WEATHER_LAG_HOURS = 24


def source_path() -> Path:
    """The cleaned weather and grid table this dataset is built from."""
    return repo_root() / "data" / "processed" / "cleaned_weather_carbon.csv"


def output_path(variant: str = DEFAULT_VARIANT) -> Path:
    """Where a variant is written. The honest variant is the default file."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    name = "demand_dataset.csv" if variant == DEFAULT_VARIANT else f"demand_dataset_{variant}.csv"
    return repo_root() / "data" / "processed" / name


def meta_path(path: Path) -> Path:
    """The metadata file that sits beside a dataset CSV."""
    return path.with_suffix(".meta.json")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The ``n``-th given weekday of a month (Monday is 0). ``n = -1`` is the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    following = dt.date(year + month // 12, month % 12 + 1, 1)
    last = following - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: dt.date) -> dt.date:
    """A fixed-date holiday on a Saturday is observed Friday, on a Sunday, Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def us_holidays(years) -> set[dt.date]:
    """US federal holidays, plus the day after Thanksgiving, which California also observes.

    Both the actual date and the observed weekday are included for fixed-date
    holidays, because load drops on both.
    """
    days: set[dt.date] = set()
    for year in years:
        for month, day in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25)):
            actual = dt.date(year, month, day)
            days.update({actual, _observed(actual)})
        thanksgiving = _nth_weekday(year, 11, 3, 4)
        days.update(
            {
                _nth_weekday(year, 1, 0, 3),
                _nth_weekday(year, 2, 0, 3),
                _nth_weekday(year, 5, 0, -1),
                _nth_weekday(year, 9, 0, 1),
                _nth_weekday(year, 10, 0, 2),
                thanksgiving,
                thanksgiving + dt.timedelta(days=1),
            }
        )
    return days


def content_hash(frame: pd.DataFrame) -> str:
    """A short fingerprint of the table, index included, so a run can name its data."""
    hashed = pd.util.hash_pandas_object(frame, index=True).to_numpy()
    return hashlib.sha256(hashed.tobytes()).hexdigest()[:16]


def build(raw: pd.DataFrame, variant: str = DEFAULT_VARIANT) -> tuple[pd.DataFrame, dict]:
    """Turn the cleaned table into the modeling table for one variant.

    Args:
        raw: The cleaned CSV, indexed by UTC hour.
        variant: ``honest`` or ``weather_forecast_standin``.

    Returns:
        The table (target, benchmark, features) and its metadata.
    """
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    audited = apply_audit(raw)
    audited.index = pd.to_datetime(audited.index, utc=True).floor("h")
    audited = audited[~audited.index.duplicated(keep="last")].sort_index()
    full_index = pd.date_range(audited.index.min(), audited.index.max(), freq="h", tz="UTC")
    frame = audited.reindex(full_index)

    local = frame.index.tz_convert(LOCAL_TZ)
    hour = local.hour.to_numpy()
    dow = local.dayofweek.to_numpy()
    day_of_year = local.dayofyear.to_numpy()
    frame["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    frame["doy_sin"] = np.sin(2 * np.pi * day_of_year / 365.25)
    frame["doy_cos"] = np.cos(2 * np.pi * day_of_year / 365.25)
    holidays = us_holidays(range(local.year.min(), local.year.max() + 1))
    frame["is_holiday"] = np.isin(local.date, list(holidays)).astype(float)

    for name, steps in DEMAND_LAGS.items():
        frame[name] = frame[TARGET].shift(steps)

    if variant == "honest":
        weather = {f"{column}_lag_{WEATHER_LAG_HOURS}": frame[column].shift(WEATHER_LAG_HOURS) for column in FEATURE_SOURCE_COLUMNS}
        frame = frame.drop(columns=FEATURE_SOURCE_COLUMNS).assign(**weather)
        weather_columns = list(weather)
    else:
        weather_columns = list(FEATURE_SOURCE_COLUMNS)

    candidates = CALENDAR_COLUMNS + list(DEMAND_LAGS) + weather_columns
    # A missing CAISO forecast does not drop the hour. The forecast is a
    # benchmark, not a feature, and the early EIA archive has gaps in it.
    table = frame.dropna(subset=[TARGET, *candidates]).loc[:, [TARGET, BENCHMARK, *candidates]]
    duplicated = resolve_correlated(table[candidates], table[TARGET])
    features = [column for column in candidates if column not in duplicated]
    # The demand lags stay in the table even if the 0.95 rule drops them as
    # features, because the copy-the-past baselines are scored from them.
    baselines = [column for column in DEMAND_LAGS if column not in features]
    table = table.loc[:, [TARGET, BENCHMARK, *baselines, *features]]
    table.index.name = "timestamp"

    meta = {
        "variant": variant,
        "target": TARGET,
        "benchmark": BENCHMARK,
        "features": features,
        "dropped": {**DROPPED, **duplicated},
        "weather_lag_hours": WEATHER_LAG_HOURS if variant == "honest" else 0,
        "rows": int(len(table)),
        "start": str(table.index.min()),
        "end": str(table.index.max()),
        "content_hash": content_hash(table),
    }
    return table, meta


def write(variant: str = DEFAULT_VARIANT, source: Path | None = None) -> Path:
    """Build one variant from the cleaned CSV and write the table and its metadata."""
    source = source_path() if source is None else source
    if not source.exists():
        raise FileNotFoundError(f"{source} is missing. Build it with: python -m src.build_cleaned_dataset")
    raw = pd.read_csv(source, index_col=0, parse_dates=True)
    table, meta = build(raw, variant)
    meta["source"] = source.name
    path = output_path(variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path)
    meta_path(path).write_text(json.dumps(meta, indent=2))
    print(f"{variant}: {meta['rows']} rows, {len(meta['features'])} features, {meta['start']} to {meta['end']}")
    print(f"  wrote {path}")
    return path


def main() -> None:
    """Write every variant, or the one named with ``--variant``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", choices=VARIANTS, default=None, help="build only this variant")
    args = parser.parse_args()
    for variant in [args.variant] if args.variant else VARIANTS:
        write(variant)


if __name__ == "__main__":
    main()
