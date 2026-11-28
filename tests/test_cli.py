import json

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import carbon.cli.main as cli
from carbon.api.main import app
from carbon.common.store import get_store

runner = CliRunner()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(cli, "get_client", lambda: TestClient(app))


def test_best_json_is_machine_readable(api, seeded):
    result = runner.invoke(cli.app, ["best", "-d", "4", "-w", "1d", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["recommendation"] in {"run_now", "delay"}


def test_best_prints_a_table_by_default(api, seeded):
    result = runner.invoke(cli.app, ["best", "-d", "4", "-w", "1d"])
    assert result.exit_code == 0
    assert "Start (UTC)" in result.stdout


def test_stale_forecast_exits_4_but_still_prints(api, seeded, monkeypatch):
    monkeypatch.setenv("CARBON_NOW", "2026-10-27T23:30:00Z")
    result = runner.invoke(cli.app, ["best", "-d", "4", "--json"])
    assert result.exit_code == 4
    assert "forecast_stale" in json.loads(result.stdout)["warnings"]
    assert runner.invoke(cli.app, ["best", "-d", "4", "--json", "--allow-stale"]).exit_code == 0


def test_failed_pipeline_exits_4(api, seeded):
    get_store().update_status({"last_run_status": "failed", "last_error": "x"})
    assert runner.invoke(cli.app, ["status", "--json"]).exit_code == 4


def test_unreachable_api_exits_3(monkeypatch):
    monkeypatch.setattr(cli, "get_client", lambda: httpx.Client(base_url="http://127.0.0.1:1", timeout=1))
    assert runner.invoke(cli.app, ["best", "-d", "4"]).exit_code == 3


def test_api_errors_exit_5(api, seeded):
    assert runner.invoke(cli.app, ["best", "-d", "4", "-l", "nowhere"]).exit_code == 5


def test_no_forecast_yet_exits_5(api):
    assert runner.invoke(cli.app, ["best", "-d", "4"]).exit_code == 5


def test_bad_arguments_exit_2(api):
    assert runner.invoke(cli.app, ["best"]).exit_code == 2
    assert runner.invoke(cli.app, ["best", "-d", "0"]).exit_code == 2


def test_location_comes_from_the_environment(api, seeded, monkeypatch):
    monkeypatch.setenv("CARBON_LOCATION", "nowhere")
    assert runner.invoke(cli.app, ["best", "-d", "4"]).exit_code == 5
