"""The price window is the cheapest block in the next five days, in dollars."""

import numpy as np
import pandas as pd
import pytest

from price_windows.recommend import (
    AmbiguousSite,
    cheapest_block,
    format_report,
    job_dollars,
    match_campuses,
    recommend,
)
from price_windows.schema import LOCAL_TZ, TARGET


class _EchoLag:
    """Returns the 120-hour price lag, so a negative lag stays a negative forecast."""

    def predict(self, frame):
        return frame["lmp_lag_120"].to_numpy(dtype=float)


def _sites() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "campus_id": "santa-clara-main",
                "name": "Main",
                "street": "1 Main St",
                "city": "Santa Clara",
                "latitude": 37.35,
                "longitude": -121.95,
                "dlap_id": "DLAP_PGAE-APND",
            }
        ]
    )


def _nodes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "campus_id": "santa-clara-main",
                "rank": 1,
                "pnode_id": "NODE_A",
                "node_type": "Load Node",
                "latitude": 37.36,
                "longitude": -121.95,
                "distance_km": 1.2,
            },
            {
                "campus_id": "santa-clara-main",
                "rank": 2,
                "pnode_id": "NODE_B",
                "node_type": "Generation Node",
                "latitude": 37.37,
                "longitude": -121.96,
                "distance_km": 2.4,
            },
        ]
    )


def _table(anchor: pd.Timestamp, prices: dict[str, pd.Series]) -> pd.DataFrame:
    frames = []
    for pnode_id, series in prices.items():
        block = pd.DataFrame({TARGET: series, "pnode_id": pnode_id, "campus_id": "santa-clara-main"})
        block.index.name = "timestamp"
        frames.append(block)
    return pd.concat(frames).sort_index()


def _saved() -> dict:
    return {"model": _EchoLag(), "features": ["hour_sin", "lmp_lag_120"], "target": TARGET}


def test_job_dollars_for_an_8kw_four_hour_cabinet() -> None:
    # 8 kW * 4 h = 32 kWh. 40 $/MWh * 32 / 1000 = 1.28 dollars.
    assert job_dollars(40.0, 8, 4) == pytest.approx(1.28)
    assert job_dollars(-10.0, 8, 4) == pytest.approx(-0.32)


def test_cheapest_block_keeps_a_negative_price_and_skips_hours_outside_the_day() -> None:
    index = pd.date_range("2026-11-15 08:00", periods=48, freq="h", tz="UTC")
    local = index.tz_convert(LOCAL_TZ)
    prices = np.full(len(index), 20.0)
    start = int(np.flatnonzero(local.hour.to_numpy() == 10)[0])
    prices[start : start + 4] = -5.0
    daytime = cheapest_block(index, prices, 4, start_hour=10, end_hour=17)
    assert daytime is not None
    assert daytime["average_usd_per_mwh"] == pytest.approx(-5.0)
    overnight = cheapest_block(index, prices, 4, start_hour=0, end_hour=4)
    assert overnight is not None
    assert overnight["average_usd_per_mwh"] == pytest.approx(20.0)


def test_printed_window_for_an_8kw_job_includes_dollars_and_a_negative_price() -> None:
    anchor = pd.Timestamp("2026-11-14 23:00", tz="UTC")
    history = pd.date_range(anchor - pd.Timedelta(hours=200), anchor, freq="h", tz="UTC")
    cheap = pd.Series(40.0, index=history)
    costly = pd.Series(40.0, index=history)
    for step in range(1, 5):
        cheap.loc[anchor + pd.Timedelta(hours=step - 120)] = -10.0
    result = recommend(
        "Santa Clara",
        duration=4,
        days=1,
        kw=8,
        table=_table(anchor, {"NODE_A": cheap, "NODE_B": costly}),
        sites=_sites(),
        candidates=_nodes(),
        saved=_saved(),
    )
    assert result["horizon_start_utc"].startswith("2026-11-15")
    assert pd.Timestamp(result["horizon_start_utc"]) > anchor
    assert result["winner"]["pnode_id"] == "NODE_A"
    assert result["winner"]["average_usd_per_mwh"] == pytest.approx(-10.0)
    assert result["winner"]["job_dollars"] == pytest.approx(-0.32)
    text = format_report(result)
    assert "dollars" in text
    assert "-0.32 dollars" in text
    assert "DLAP_PGAE-APND" in text
    assert "does not forecast" in text


def test_days_above_five_are_clamped_and_the_report_says_so() -> None:
    anchor = pd.Timestamp("2026-11-14 23:00", tz="UTC")
    history = pd.date_range(anchor - pd.Timedelta(hours=150), anchor, freq="h", tz="UTC")
    flat = pd.Series(25.0, index=history)
    result = recommend(
        "1 Main St",
        duration=4,
        days=9,
        kw=8,
        table=_table(anchor, {"NODE_A": flat, "NODE_B": flat}),
        sites=_sites(),
        candidates=_nodes(),
        saved=_saved(),
    )
    assert result["clamped_to_5_days"] is True
    assert result["horizon_hours"] == 120
    assert result["winner"]["job_dollars"] == pytest.approx(0.80)
    assert result["winner"]["rank"] == 1
    assert "days clamped to 5" in format_report(result)


def test_several_campuses_are_listed_instead_of_guessed() -> None:
    sites = pd.concat([_sites(), _sites().assign(campus_id="santa-clara-other", street="2 Other St")], ignore_index=True)
    anchor = pd.Timestamp("2026-11-14", tz="UTC")
    history = pd.date_range(anchor - pd.Timedelta(hours=4), anchor, freq="h", tz="UTC")
    with pytest.raises(AmbiguousSite) as raised:
        recommend(
            "Santa Clara",
            duration=4,
            days=1,
            table=_table(anchor, {"NODE_A": pd.Series(1.0, index=history)}),
            sites=sites,
            candidates=_nodes(),
            saved=_saved(),
        )
    assert len(match_campuses(sites, "Santa Clara")) == 2
    assert len(raised.value.matches) == 2
