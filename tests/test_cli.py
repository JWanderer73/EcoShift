import json
from datetime import UTC, datetime, timedelta

import pytest
import typer
from typer.testing import CliRunner

from src import cli

NOW = datetime(2026, 10, 21, 14, 35, tzinfo=UTC)

runner = CliRunner()


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
    assert "CO₂ saved" in result.stdout


def test_json_output_is_the_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {"windows": [], "job": {"deadline_clamped": False}, "data_source": "synthetic"}
    calls = []

    def fake_get_windows(*args: object) -> dict:
        calls.append(args)
        return canned

    monkeypatch.setattr(cli, "get_windows", fake_get_windows)
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
