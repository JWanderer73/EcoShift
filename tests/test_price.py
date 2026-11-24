"""The delivered price model inside the pipeline, with a tiny stand-in model and fake data pulls.

No network and no real model file: the point is the wiring (ingest, gate, predict, accuracy and the
API), which the real model file plugs into unchanged.
"""

import io

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from carbon.common import keys
from carbon.common.store import get_store
from carbon.common.timeutil import iso, utcnow
from carbon.common.validate import ValidationError
from carbon.price import run as price_run
from carbon.price import sites
from carbon.price.bridge import load as model_code

CAMPUSES = ["fresno-305-west-napa-avenue", "fresno-1315-van-ness-avenue"]
NODES = sorted({n["pnode_id"] for c in CAMPUSES for n in sites.candidates()[c]})


@pytest.fixture(autouse=True)
def price_mode(monkeypatch):
    monkeypatch.setenv("CARBON_MODEL", "price_xgb")
    monkeypatch.delenv("CARBON_LOCATIONS", raising=False)


def hourly_price(node: str, ts: pd.DatetimeIndex) -> np.ndarray:
    """A daily shape with a midday dip, a node offset and a negative stretch on the 25th."""
    base = 40 - 30 * np.exp(-((ts.hour.to_numpy() - 13) ** 2) / 12) + (sum(map(ord, node)) % 7)
    return np.where((ts.day == 25) & (ts.hour >= 11) & (ts.hour <= 14), -12.0, base).astype(float)


def fake_lmp(calls=None, gap_node=None):
    def fetch(node, start, end):
        if calls is not None:
            calls.append((node, start, end))
        ts = pd.date_range(start, end - pd.Timedelta(hours=1), freq="h", tz="UTC")
        frame = pd.DataFrame({"timestamp": ts, "lmp_usd_per_mwh": hourly_price(node, ts)})
        if node == gap_node:
            frame = frame.drop(frame.index[100:110])  # ten missing hours: longer than the 3-hour limit
        return frame

    return fetch


def fake_weather(lat, lon, hours, columns):
    return pd.DataFrame({c: np.linspace(10, 20, len(hours)) for c in columns}, index=hours)


def fake_load(hours):
    return pd.Series(np.linspace(25000, 32000, len(hours)), index=hours)


def stand_in_model_bytes() -> bytes:
    from price_windows.schema import feature_columns
    from xgboost import XGBRegressor

    features = feature_columns(include_load=True)
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(300, len(features))), columns=features)
    model = XGBRegressor(n_estimators=8, max_depth=2, objective="reg:absoluteerror").fit(x, rng.normal(30, 10, 300))
    buffer = io.BytesIO()
    joblib.dump({"model": model, "features": features}, buffer)
    return buffer.getvalue()


@pytest.fixture
def ingested():
    model_code()  # puts the vendored model on sys.path
    price_run.ingest(get_store(), fetch_lmp=fake_lmp(), nodes=NODES)


@pytest.fixture
def with_model(ingested):
    metrics = {"test": {"mae_usd_per_mwh": 7.37}}
    version = price_run.register_model(get_store(), stand_in_model_bytes(), metrics)
    assert price_run.gate(get_store())["promoted"] is True
    return version


def predict(**extra):
    return price_run.predict(
        get_store(), fetch_weather=fake_weather, fetch_load=fake_load, campus_filter=CAMPUSES, **extra
    )


def test_ingest_keeps_three_weeks_through_tomorrow(ingested):
    table = get_store().get_json(keys.PRICE_TABLE)
    from carbon.price.forecast import prices_frame

    frame = prices_frame(table)
    assert set(frame.columns) == set(NODES)
    assert frame.index.max() == pd.Timestamp("2026-10-28 23:00", tz="UTC")  # now is 2026-10-27 14:30Z
    assert (frame.index.max() - frame.index.min()).days >= 20
    assert (frame.to_numpy() < 0).any()  # negative prices survive validation


def test_second_ingest_only_asks_for_recent_days():
    model_code()
    store, calls = get_store(), []
    price_run.ingest(store, fetch_lmp=fake_lmp(), nodes=NODES)
    price_run.ingest(store, fetch_lmp=fake_lmp(calls), nodes=NODES)
    starts = {start for _, start, _ in calls}
    assert starts == {pd.Timestamp("2026-10-27", tz="UTC")}  # the last stored day, minus one


def test_a_node_with_a_long_gap_is_dropped_but_the_run_continues():
    model_code()
    store = get_store()
    # one bad node out of many is under the degraded fraction only when there are enough nodes
    many = sites.all_nodes()[:60]
    summary = price_run.ingest(store, fetch_lmp=fake_lmp(gap_node=many[0]), nodes=many)
    assert summary["dropped"] == 1 and summary["nodes"] == 59


def test_an_oasis_outage_never_replaces_good_data_and_a_first_run_with_nothing_fails():
    model_code()
    store = get_store()

    def broken(node, start, end):
        raise RuntimeError("OASIS down")

    with pytest.raises(ValidationError):  # nothing stored yet and nothing pulled
        price_run.ingest(store, fetch_lmp=broken, nodes=NODES)
    assert store.get_json(keys.PRICE_TABLE) is None

    price_run.ingest(store, fetch_lmp=fake_lmp(), nodes=NODES)
    before = store.get_json(keys.PRICE_TABLE)["nodes"]
    price_run.ingest(store, fetch_lmp=broken, nodes=NODES)  # outage later: stored prices stay as they were
    assert store.get_json(keys.PRICE_TABLE)["nodes"] == before


def test_train_step_needs_an_uploaded_model(ingested):
    with pytest.raises(RuntimeError, match="upload_model"):
        price_run.check_trained_model(get_store())


def test_gate_promotes_first_then_only_if_not_worse(ingested):
    store = get_store()
    price_run.register_model(store, b"first", {"test": {"mae_usd_per_mwh": 7.0}})
    assert price_run.gate(store)["promoted"] is True
    price_run.register_model(store, b"worse", {"test": {"mae_usd_per_mwh": 9.0}})
    assert price_run.gate(store)["promoted"] is False
    price_run.register_model(store, b"better", {"test": {"mae_usd_per_mwh": 6.5}})
    assert price_run.gate(store)["promoted"] is True


def test_predict_serves_published_prices_then_the_model_forecast(with_model):
    result = predict()
    assert result["campuses"] == 2 and result["fallback"] is False
    status = get_store().get_status()
    assert status["data_source"] == "caiso-day-ahead" and status["prices_through"] == "2026-10-28T23:00:00Z"
    version = status["current_model_versions"][CAMPUSES[0]]
    rows = get_store().get_forecast(CAMPUSES[0], version)["rows"]
    assert rows[0]["ts"] == "2026-10-27T14:00:00Z"  # from the current hour
    published = [r for r in rows if r["kind"] == "published"]
    forecast = [r for r in rows if r["kind"] == "forecast"]
    assert len(published) == 34 and len(forecast) == 120  # to 2026-10-28 23:00, then five days
    assert forecast[0]["ts"] == "2026-10-29T00:00:00Z" and forecast[-1]["ts"] == "2026-11-02T23:00:00Z"
    assert set(rows[0]["nodes"]) == {n["pnode_id"] for n in sites.candidates()[CAMPUSES[0]]}
    assert all(np.isfinite(r["price"]) for r in rows)


def test_a_published_hour_is_served_exactly_as_published(with_model):
    predict()
    status = get_store().get_status()
    rows = get_store().get_forecast(CAMPUSES[0], status["current_model_versions"][CAMPUSES[0]])["rows"]
    node = sites.candidates()[CAMPUSES[0]][0]["pnode_id"]
    ts = pd.Timestamp(rows[0]["ts"])
    assert rows[0]["nodes"][node] == pytest.approx(round(float(hourly_price(node, pd.DatetimeIndex([ts]))[0]), 2))


def test_predictions_are_not_clipped_at_zero(with_model):
    saved = joblib.load(io.BytesIO(stand_in_model_bytes()))
    saved["model"].set_params(base_score=-500.0)  # a model that predicts well below zero
    from carbon.price.forecast import forecast_campuses, prices_frame

    prices = prices_frame(get_store().get_json(keys.PRICE_TABLE))
    # Retrain-free way to force negatives: shift the stand-in's output through its booster config.
    rows, _ = forecast_campuses(saved, prices, utcnow(), fetch_weather=fake_weather, fetch_load=fake_load, campus_filter=CAMPUSES[:1])
    prices_out = [r["price"] for r in rows[CAMPUSES[0]] if r["kind"] == "forecast"]
    assert min(prices_out) < 0


def test_without_a_champion_the_last_week_baseline_is_served_with_a_warning(ingested):
    result = predict()
    assert result["fallback"] is True and result["version"].startswith("baseline-lastweek")
    status = get_store().get_status()
    rows = get_store().get_forecast(CAMPUSES[0], status["current_model_versions"][CAMPUSES[0]])["rows"]
    node = sites.candidates()[CAMPUSES[0]][0]["pnode_id"]
    first = next(r for r in rows if r["kind"] == "forecast")
    ts = pd.Timestamp(first["ts"]) - pd.Timedelta(hours=168)
    assert first["nodes"][node] == pytest.approx(round(float(hourly_price(node, pd.DatetimeIndex([ts]))[0]), 2))


def test_a_campus_whose_weather_fails_is_skipped_not_fatal(with_model):
    def flaky(lat, lon, hours, columns):
        if abs(lat - sites.campuses()[CAMPUSES[0]]["latitude"]) < 1e-9:
            raise RuntimeError("Open-Meteo 429")
        return fake_weather(lat, lon, hours, columns)

    result = price_run.predict(get_store(), fetch_weather=flaky, fetch_load=fake_load, campus_filter=CAMPUSES)
    assert result["campuses"] == 1 and result["skipped"] == 1
    assert CAMPUSES[0] in get_store().get_status()["campuses_skipped"]


def test_accuracy_scores_forecast_hours_against_published_prices(with_model, monkeypatch):
    predict()
    # A day later the table has caught up, so earlier forecast hours now have a published price.
    monkeypatch.setenv("CARBON_NOW", "2026-10-28T20:00:00Z")
    price_run.ingest(get_store(), fetch_lmp=fake_lmp(), nodes=NODES)
    result = price_run.accuracy(get_store())["all"]
    assert result["n"] > 0 and result["mae_usd_per_mwh"] >= 0


# --- the API on top of it ---------------------------------------------------------------------


@pytest.fixture
def api(with_model):
    predict()
    from carbon.api.main import app

    return TestClient(app)


def test_api_lists_campuses_with_their_nodes(api):
    body = api.get("/v1/sites").json()["sites"]
    assert len(body) == 206  # every campus, whether or not it has a forecast yet
    one = next(s for s in body if s["location"] == CAMPUSES[0])
    assert len(one["nodes"]) == 5 and one["city"] == "Fresno"


def test_api_forecast_marks_published_and_forecast_hours(api):
    body = api.get("/v1/forecast", params={"location": CAMPUSES[0]}).json()
    assert body["unit"] == "usd_per_mwh" and body["data_source"] == "caiso-day-ahead"
    assert {r["kind"] for r in body["rows"]} == {"published", "forecast"}
    assert len(body["rows"]) == 154


def test_api_windows_can_choose_a_negative_published_hour_and_price_it_in_dollars(api):
    body = api.get(
        "/v1/windows", params={"location": CAMPUSES[0], "duration_hours": 2, "kw": 8, "max_wait": "3d"}
    ).json()
    assert body["recommendation"] in {"run_now", "delay"}
    assert body["best"]["cost_usd"] == pytest.approx(body["best"]["avg"] * 8 * 2 / 1000, abs=5e-3)
    assert body["data_source"] == "caiso-day-ahead"


def test_api_can_price_at_a_chosen_node(api):
    node = sites.candidates()[CAMPUSES[0]][2]["pnode_id"]
    body = api.get("/v1/forecast", params={"location": CAMPUSES[0], "node": node}).json()
    assert body["node"] == node
    assert body["rows"][0]["price"] == body["rows"][0]["nodes"][node]
    assert api.get("/v1/forecast", params={"location": CAMPUSES[0], "node": "NOT_A_NODE"}).status_code == 404


def test_a_campus_without_a_forecast_is_a_clear_503(api):
    other = next(c for c in sites.campus_ids() if c not in CAMPUSES)
    r = api.get("/v1/forecast", params={"location": other})
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_forecast"


def test_the_published_price_for_the_current_hour_is_the_run_now_price(api):
    body = api.get("/v1/windows", params={"location": CAMPUSES[0], "duration_hours": 1}).json()
    forecast = api.get("/v1/forecast", params={"location": CAMPUSES[0]}).json()
    assert body["run_now_avg"] == forecast["rows"][0]["price"]
