"""Leakage rules for the five-day price dataset. No network."""

import json

import numpy as np
import pandas as pd
import pytest

from price_windows.build_dataset import _campuses, _keep_total_lmp, _parse_page, _with_lags, folder, meta_path
from price_windows.schema import (
    TARGET,
    WEEK_COLUMN,
    WEEK_LAGS,
    dlap_for_city,
    feature_columns,
    illegal_feature_names,
    nearest_five,
)


def test_a_price_lag_shorter_than_five_days_is_refused():
    found = illegal_feature_names(["lmp_lag_24", "hour_sin"])
    assert "lmp_lag_24" in found


def test_a_congestion_or_loss_or_energy_column_is_refused():
    found = illegal_feature_names(["lmp_cong_lag_120", "lmp_loss_lag_168", "mce_lag_120"])
    assert found == ["lmp_cong_lag_120", "lmp_loss_lag_168", "mce_lag_120"]


def test_the_proposed_features_are_legal():
    assert illegal_feature_names(feature_columns(include_load=True)) == []


def test_a_load_node_ranks_ahead_of_a_generator_inside_the_same_band():
    nodes = pd.DataFrame(
        {
            "pnode_id": ["GEN_NEAR", "LOAD_SAME_BAND"],
            "latitude": [37.0002, 37.0015],
            "longitude": [-121.0, -121.0],
            "node_type": ["Generation Node", "Load Node"],
        }
    )
    chosen = nearest_five(37.0, -121.0, nodes)
    assert chosen.iloc[0]["pnode_id"] == "LOAD_SAME_BAND"
    assert list(chosen["rank"]) == [1, 2]


def test_the_minimum_lag_is_legal_and_one_hour_less_is_not():
    assert illegal_feature_names(["lmp_lag_120"]) == []
    assert illegal_feature_names(["lmp_lag_119"]) == ["lmp_lag_119"]


def test_the_target_is_not_a_feature():
    assert illegal_feature_names([TARGET]) == [TARGET]


def test_named_cities_keep_their_load_zone_label():
    assert dlap_for_city("Santa Clara") == "DLAP_PGAE-APND"
    assert dlap_for_city("San Jose") == "DLAP_PGAE-APND"
    assert dlap_for_city("Fresno") == "DLAP_PGAE-APND"
    assert dlap_for_city("Los Angeles") == "DLAP_SCE-APND"
    assert dlap_for_city("San Diego") == "DLAP_SDGE-APND"


def test_the_page_payload_keeps_the_operator_and_every_listing():
    chunk = json.dumps(
        {
            "datacenters": [
                {
                    "name": "Equinix SV5",
                    "address": "9 Great Oaks Boulevard San Jose CA 95119 USA, San Jose",
                    "owner": {"name": "Equinix"},
                },
                {
                    "name": "Telstra SV5",
                    "address": "9 Great Oaks Boulevard San Jose CA 95119 USA, San Jose",
                    "owner": {"name": "Telstra"},
                },
            ]
        }
    )
    html = "<script>self.__next_f.push([1," + json.dumps(chunk) + "])</script>"
    rows = _parse_page(html, "https://inflect.com/datacenters/na/usa/california")
    assert [row["operator"] for row in rows] == ["Equinix", "Telstra"]
    assert rows[0]["street"] == "9 Great Oaks Boulevard"
    campuses = _campuses(pd.DataFrame(rows))
    assert len(campuses) == 1
    assert campuses.iloc[0]["dlap_id"] == "DLAP_PGAE-APND"


def test_component_rows_are_dropped_and_a_negative_price_stays():
    raw = pd.DataFrame(
        {
            "XML_DATA_ITEM": ["LMP_PRC", "LMP_CONG_PRC", "LMP_ENE_PRC", "LMP_LOSS_PRC", "LMP_GHG_PRC"],
            "INTERVALSTARTTIME_GMT": ["2026-01-01T08:00:00-00:00"] * 5,
            "MW": [-12.5, 1.0, -13.0, -0.5, 0.0],
        }
    )
    kept = _keep_total_lmp(raw)
    assert list(kept.columns) == ["timestamp", TARGET]
    assert kept.iloc[0][TARGET] == -12.5


def test_a_missing_hour_does_not_shorten_the_price_lag():
    index = pd.date_range("2026-01-01", periods=400, freq="h", tz="UTC")
    hourly = pd.Series(np.arange(len(index), dtype=float), index=index).drop(index[200])
    frame = _with_lags(hourly)
    moment = index[250]
    assert frame.loc[moment, "lmp_lag_120"] == 130.0
    assert pd.isna(frame.loc[index[200], TARGET])


def test_same_hour_week_is_the_mean_of_seven_lags_from_five_days():
    index = pd.date_range("2026-01-01", periods=400, freq="h", tz="UTC")
    hourly = pd.Series(np.arange(len(index), dtype=float), index=index)
    frame = _with_lags(hourly)
    moment = index[300]
    expected = float(np.mean([300 - hours for hours in WEEK_LAGS]))
    assert frame.loc[moment, WEEK_COLUMN] == expected
    assert min(WEEK_LAGS) >= 120


def test_cached_silicon_valley_page_is_not_cut_at_one_hundred():
    path = folder() / "cache" / "inflect_silicon-valley.html"
    if not path.exists():
        pytest.skip("Inflect pages are not cached")
    rows = _parse_page(path.read_text(errors="replace"), "https://inflect.com/datacenters/na/usa/california/silicon-valley")
    assert len(rows) > 100
    assert any(row["operator"] for row in rows)


def test_built_table_keeps_five_nodes_and_refuses_a_short_lag():
    meta_file = meta_path()
    if not meta_file.exists():
        pytest.skip("price dataset is not built")
    meta = json.loads(meta_file.read_text())
    assert illegal_feature_names(meta["features"]) == []
    assert TARGET not in meta["features"]
    sites = pd.read_csv(folder() / "sites.csv")
    candidates = pd.read_csv(folder() / "candidates.csv")
    assert sites["campus_id"].is_unique
    counts = candidates.groupby("campus_id").size()
    assert counts.eq(5).all()
    assert set(counts.index) == set(sites["campus_id"])


def test_a_closer_band_still_wins():
    nodes = pd.DataFrame(
        {
            "pnode_id": ["GEN_CLOSE", "LOAD_FAR"],
            "latitude": [37.0002, 37.004],
            "longitude": [-121.0, -121.0],
            "node_type": ["Generation Node", "Load Node"],
        }
    )
    chosen = nearest_five(37.0, -121.0, nodes)
    assert chosen.iloc[0]["pnode_id"] == "GEN_CLOSE"
