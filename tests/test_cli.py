import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
import typer
from typer.testing import CliRunner

from src import cli

NOW = datetime(2026, 10, 21, 14, 35, tzinfo=UTC)
HOUR0 = NOW.replace(minute=0)  # first forecast hour

runner = CliRunner()


@pytest.fixture
def utc_local_time():
    """Make the machine's local time zone UTC, so printed times are predictable."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()


def _forecast(values: list[float]) -> dict:
    """A /forecast response with one point per value, starting at HOUR0."""
    return {
        "region": "CISO",
        "generated_at": HOUR0.isoformat(),
        "stale": False,
        "data_source": "synthetic",
        "points": [
            {"start": (HOUR0 + timedelta(hours=i)).isoformat(), "intensity": value}
            for i, value in enumerate(values)
        ],
    }


def _response(starts: list[int], duration: int = 2, deadline_hours: int = 48) -> dict:
    """A /windows response with windows starting ``starts`` hours after HOUR0, best first."""

    def span(offset: int) -> dict:
        return {
            "start": (HOUR0 + timedelta(hours=offset)).isoformat(),
            "end": (HOUR0 + timedelta(hours=offset + duration)).isoformat(),
        }

    return {
        "region": "CISO",
        "generated_at": HOUR0.isoformat(),
        "stale": False,
        "data_source": "synthetic",
        "job": {
            "duration_hours": duration,
            "deadline": (HOUR0 + timedelta(hours=deadline_hours)).isoformat(),
            "deadline_clamped": False,
        },
        "baseline": {**span(0), "avg_intensity_g_per_kwh": 250.0},
        "windows": [
            {"rank": rank, **span(offset), "avg_intensity_g_per_kwh": 150.0, "co2_saved_pct": 40.0}
            for rank, offset in enumerate(starts, start=1)
        ],
    }


@pytest.mark.parametrize(
    ("text", "hours"),
    [("4h", 4), ("90m", 2), ("1h30m", 2), ("60m", 1), ("2", 2), ("1.5", 2), (" 3H ", 3)],
)
def test_parse_duration_rounds_up_to_hours(text: str, hours: int) -> None:
    assert cli.parse_duration_hours(text) == hours


@pytest.mark.parametrize("text", ["", "soon", "0", "-1", "4x", "h", "nan", "inf"])
def test_parse_duration_rejects_bad_values(text: str) -> None:
    with pytest.raises(typer.BadParameter):
        cli.parse_duration_hours(text)


def test_parse_deadline_relative() -> None:
    assert cli.parse_deadline("24h", NOW) == NOW + timedelta(hours=24)


def test_parse_deadline_iso_with_timezone() -> None:
    assert cli.parse_deadline("2026-10-22T09:00+00:00", NOW) == datetime(
        2026, 10, 22, 9, tzinfo=UTC
    )


def test_parse_deadline_without_timezone_is_local_time() -> None:
    deadline = cli.parse_deadline("2026-10-22T09:00", NOW)
    assert deadline.tzinfo is not None
    assert deadline.replace(tzinfo=None) == datetime(2026, 10, 22, 9)


@pytest.mark.parametrize("text", ["tomorrow", "0h", "2026-13-01T00:00"])
def test_parse_deadline_rejects_bad_values(text: str) -> None:
    with pytest.raises(typer.BadParameter):
        cli.parse_deadline(text, NOW)


def test_table_output() -> None:
    result = runner.invoke(cli.app, ["windows", "--duration", "2h"])
    assert result.exit_code == 0, result.output
    assert "Synthetic data" in result.stdout
    assert "Best: " in result.stdout
    assert "█" in result.stdout
    assert "CO₂ saved" in result.stdout


def test_json_output_is_the_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {"windows": [], "job": {"deadline_clamped": False}, "data_source": "synthetic"}
    calls = []

    def fake_get_windows(*args: object) -> dict:
        calls.append(args)
        return canned

    def no_forecast(*args: object) -> dict:
        raise AssertionError("--json shouldn't fetch the hourly forecast")

    monkeypatch.setattr(cli, "get_windows", fake_get_windows)
    monkeypatch.setattr(cli, "get_forecast", no_forecast)
    result = runner.invoke(
        cli.app, ["windows", "-d", "90m", "--region", "erco", "--top", "2", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == canned
    duration_hours, deadline, region, top, _ = calls[0]
    assert (duration_hours, deadline, region, top) == (2, None, "ERCO", 2)


def test_real_json_output_parses() -> None:
    result = runner.invoke(cli.app, ["windows", "-d", "3h", "--json"])
    assert result.exit_code == 0, result.output
    response = json.loads(result.stdout)
    assert response["data_source"] == "synthetic"
    assert len(response["windows"]) == 3


def test_clamped_deadline_warns_on_stderr() -> None:
    result = runner.invoke(cli.app, ["windows", "-d", "2h", "--deadline", "200h", "--json"])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.stderr
    assert json.loads(result.stdout)["job"]["deadline_clamped"] is True


def test_job_that_does_not_fit_exits_1() -> None:
    result = runner.invoke(cli.app, ["windows", "-d", "5h", "--deadline", "2h"])
    assert result.exit_code == 1
    assert "doesn't fit" in result.stderr


def test_unknown_region_exits_1() -> None:
    result = runner.invoke(cli.app, ["windows", "-d", "2h", "--region", "NOPE"])
    assert result.exit_code == 1
    assert "unknown region" in result.stderr


@pytest.mark.parametrize(
    "args",
    [["-d", "soon"], ["-d", "2h", "--top", "11"], ["-d", "2h", "--deadline", "later"]],
)
def test_bad_options_exit_2(args: list[str]) -> None:
    assert runner.invoke(cli.app, ["windows", *args]).exit_code == 2


@pytest.mark.parametrize(
    ("offset", "text"),
    [
        (timedelta(minutes=-35), "now"),
        (timedelta(0), "now"),
        (timedelta(minutes=25), "in 25m"),
        (timedelta(hours=3), "in 3h"),
        (timedelta(hours=21, minutes=25), "in 21h 25m"),
    ],
)
def test_format_relative(offset: timedelta, text: str) -> None:
    assert cli.format_relative(NOW + offset, NOW) == text


def test_headline_names_the_best_window(utc_local_time: None) -> None:
    assert cli.format_headline(_response([3]), NOW) == (
        "Best: Wed 17:00–19:00 UTC (in 2h 25m) · 40% less CO₂ than running now"
    )


def test_headline_shows_the_end_day_when_it_differs(utc_local_time: None) -> None:
    assert cli.format_headline(_response([9], duration=3), NOW).startswith(
        "Best: Wed 23:00–Thu 02:00 UTC"
    )


def test_headline_says_run_now_when_nothing_is_cleaner(utc_local_time: None) -> None:
    assert cli.format_headline(_response([0]), NOW) == (
        "Best: run now (Wed 14:00–16:00 UTC). Nothing cleaner before the deadline."
    )


@pytest.mark.parametrize(
    ("value", "style"),
    [(100, "green"), (160, "green"), (180, "yellow"), (240, "red"), (300, "red")],
)
def test_intensity_style_splits_the_range_in_thirds(value: float, style: str) -> None:
    assert cli.intensity_style(value, 100, 300) == style


def test_intensity_style_flat_forecast_is_green() -> None:
    assert cli.intensity_style(200, 200, 200) == "green"


def test_chart_axis_labels_every_12_hours(utc_local_time: None) -> None:
    axis, _, _ = cli.render_chart(_forecast([200] * 48), _response([0]))
    assert axis.plain == "Wed 14:00   Thu 02:00   Thu 14:00   Fri 02:00"


def test_chart_bars_span_lowest_to_highest() -> None:
    _, bars, _ = cli.render_chart(_forecast([100, 200, 300]), _response([0], duration=1))
    assert bars.plain == "▁▅█  100–300 gCO₂/kWh"


def test_chart_dims_hours_after_the_deadline() -> None:
    _, bars, _ = cli.render_chart(
        _forecast([200] * 4), _response([0], duration=1, deadline_hours=2)
    )
    assert [span.style for span in bars.spans[:4]] == ["green", "green", "dim", "dim"]


def test_chart_marks_each_window_under_its_hours() -> None:
    _, _, markers = cli.render_chart(_forecast([200] * 12), _response([1, 6], duration=3))
    assert markers.plain == " └1┘  └2┘"


@pytest.mark.parametrize(
    ("duration", "marker"), [(1, "1"), (2, "1┘"), (3, "└1┘"), (4, "└1─┘"), (5, "└─1─┘")]
)
def test_chart_marker_brackets_the_window(duration: int, marker: str) -> None:
    _, _, markers = cli.render_chart(_forecast([200] * 6), _response([0], duration=duration))
    assert markers.plain == marker


def test_chart_markers_stay_apart_when_windows_touch() -> None:
    _, _, markers = cli.render_chart(_forecast([200] * 6), _response([2, 0, 4], duration=2))
    assert markers.plain == "2┘1┘3┘"


def test_chart_marker_drops_a_rank_too_wide_for_its_window() -> None:
    _, _, markers = cli.render_chart(_forecast([200] * 10), _response(list(range(10)), duration=1))
    assert markers.plain == "123456789─"


def test_chart_skips_windows_outside_the_forecast() -> None:
    _, _, markers = cli.render_chart(_forecast([200] * 4), _response([6], duration=1))
    assert markers.plain == ""
