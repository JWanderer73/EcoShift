"""The demand dataset keeps no column that restates demand or repeats another column."""

import datetime as dt

import pandas as pd
import pytest

from src.build_demand_dataset import BENCHMARK, VARIANTS, build, source_path, us_holidays
from src.column_audit import (
    BENCHMARK_COLUMNS,
    DROP_CORRELATION,
    DROPPED,
    FEATURE_SOURCE_COLUMNS,
    FUEL_COLUMNS,
    TARGET,
    apply_audit,
    find_correlated_pairs,
    find_identities,
)

RESTATEMENTS = set(FUEL_COLUMNS) | {"carbon_intensity_g_per_kwh", TARGET, BENCHMARK, *BENCHMARK_COLUMNS}


def test_every_raw_column_is_dropped_kept_or_the_benchmark(cleaned_table) -> None:
    raw = cleaned_table(24 * 30)
    audited = apply_audit(raw)
    for column in raw.columns:
        assert column in DROPPED or column in audited.columns or column in BENCHMARK_COLUMNS, column


def test_identities_are_found_in_the_raw_table(cleaned_table) -> None:
    found = find_identities(cleaned_table(24 * 30))
    pairs = set(zip(found["column"], found["kind"]))
    copies = {frozenset(pair) for pair in zip(found["column"], found["of"])}
    assert ("temp", "mean") in pairs
    assert ("radiation", "mean") in pairs
    assert ("wind_10m", "mean") in pairs
    assert frozenset({"radiation_fresno", "fresno_shortwave_radiation"}) in copies
    assert ("fresno_shortwave_radiation", "sum") in pairs


@pytest.mark.parametrize("variant", VARIANTS)
def test_features_never_restate_demand(cleaned_table, variant) -> None:
    _, meta = build(cleaned_table(24 * 80), variant)
    features = set(meta["features"])
    assert not features & RESTATEMENTS
    assert not features & set(DROPPED)


@pytest.mark.parametrize("variant", VARIANTS)
def test_no_duplicate_features_left(cleaned_table, variant) -> None:
    table, meta = build(cleaned_table(24 * 80), variant)
    assert find_correlated_pairs(table[meta["features"]], DROP_CORRELATION).empty
    assert find_identities(table[meta["features"]]).empty


def test_honest_weather_is_from_the_same_hour_yesterday(cleaned_table) -> None:
    raw = cleaned_table(24 * 80)
    table, meta = build(raw, "honest")
    sources = apply_audit(raw)
    column = "los_angeles_temperature_2m"
    lagged = table[f"{column}_lag_24"]
    expected = sources[column].shift(24).reindex(lagged.index)
    pd.testing.assert_series_equal(lagged, expected, check_names=False)
    assert all(name.endswith("_lag_24") for name in meta["features"] if name.split("_lag_")[0] in FEATURE_SOURCE_COLUMNS)


def test_standin_weather_is_the_same_hour(cleaned_table) -> None:
    raw = cleaned_table(24 * 80)
    table, _ = build(raw, "weather_forecast_standin")
    sources = apply_audit(raw)
    column = "los_angeles_temperature_2m"
    pd.testing.assert_series_equal(table[column], sources[column].reindex(table.index), check_names=False)


def test_holidays_follow_the_calendar_rules() -> None:
    days = us_holidays([2026])
    assert dt.date(2026, 11, 26) in days
    assert dt.date(2026, 11, 27) in days
    assert dt.date(2026, 5, 25) in days
    assert dt.date(2026, 7, 3) in days
    assert dt.date(2026, 9, 7) in days


@pytest.mark.skipif(not source_path().exists(), reason="cleaned_weather_carbon.csv is not built")
def test_real_table_has_no_duplicates_left() -> None:
    raw = pd.read_csv(source_path(), index_col=0, parse_dates=True)
    table, meta = build(raw, "honest")
    assert find_correlated_pairs(table[meta["features"]], DROP_CORRELATION).empty
    assert find_identities(table[meta["features"]]).empty
    assert not set(meta["features"]) & RESTATEMENTS
