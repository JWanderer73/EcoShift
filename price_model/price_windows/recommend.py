"""Pick the cheapest hours for one batch job at a datacenter campus.

The model only predicts the day-ahead price. Weather is an input. The window
is a job length inside the next three days after the last hour whose 120-hour
price lag exists. A request past three days is clamped.

    python -m price_windows.recommend --site "Santa Clara" --duration 4 --days 5 --kw 8
"""

from __future__ import annotations

import argparse
import io
import json
import re
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd

from price_windows.build_dataset import _calendar, dataset_path
from price_windows.schema import (
    CALENDAR_FEATURES,
    DEFAULT_KW,
    GAS_FEATURE,
    HORIZON_DAYS,
    LOAD_FEATURE,
    LOCAL_TZ,
    MIN_LAG_HOURS,
    SEARCH_DAYS,
    STATIC_FEATURES,
    TARGET,
    WEATHER_FEATURES,
    WEEK_COLUMN,
    WEEK_LAGS,
    dlap_for_city,
    illegal_feature_names,
    usd_per_kwh,
)
from price_windows.train_xgboost import predict_price

# Same Open-Meteo previous-run fields the dataset stores under the day-5 names.
_METEO = {
    "temperature_forecast_day5": "temperature_2m_previous_day5",
    "cloud_cover_forecast_day5": "cloud_cover_previous_day5",
    "wind_speed_forecast_day5": "wind_speed_10m_previous_day5",
    "shortwave_forecast_day5": "shortwave_radiation_previous_day5",
}
_OASIS = "http://oasis.caiso.com/oasisapi/SingleZip"
_USER_AGENT = "Mozilla/5.0 (compatible; ecoshift-price/1.0)"
_LAG_NAME = re.compile(r"lmp_lag_(\d+)$")


class AmbiguousSite(Exception):
    """More than one campus matched the query."""

    def __init__(self, query: str, matches: pd.DataFrame):
        self.query = query
        self.matches = matches
        super().__init__(query)


def job_kwh(kw: float, duration: int) -> float:
    """Energy of a constant kilowatt load running for ``duration`` hours."""
    return float(kw) * int(duration)


def job_dollars(price_usd_per_mwh: float, kw: float, duration: int) -> float:
    """Wholesale cost. Dollars are $/MWh times kWh, divided by 1000."""
    return float(price_usd_per_mwh) * job_kwh(kw, duration) / 1000.0


def clamp_days(days: int, limit: int = SEARCH_DAYS) -> tuple[int, bool]:
    """Keep the search inside ``limit`` days. A longer request is clamped.

    The public command uses three days. Nothing in this folder is legal past five.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    cap = min(int(limit), HORIZON_DAYS)
    if cap < 1:
        raise ValueError("days must be at least 1")
    if days > cap:
        return cap, True
    return int(days), False


def match_campuses(sites: pd.DataFrame, query: str) -> pd.DataFrame:
    """Campuses whose id, city, or street equals the query, ignoring case."""
    needle = " ".join(query.strip().lower().split())
    if not needle:
        raise ValueError("site is empty")

    def column(name: str) -> pd.Series:
        if name not in sites.columns:
            return pd.Series(False, index=sites.index)
        text = sites[name].fillna("").astype(str).str.strip().str.lower()
        text = text.str.replace(r"\s+", " ", regex=True)
        return text.eq(needle)

    mask = column("campus_id") | column("city") | column("street")
    return sites.loc[mask].reset_index(drop=True)


def cheapest_block(
    index: pd.DatetimeIndex,
    prices: np.ndarray,
    duration: int,
    start_hour: int | None,
    end_hour: int | None,
    *,
    range_start: pd.Timestamp | None = None,
    range_end: pd.Timestamp | None = None,
) -> dict | None:
    """The contiguous block with the lowest average price, or None.

    ``start_hour`` and ``end_hour`` are inclusive Pacific clock hours. A
    block that would run outside that daily range is skipped. ``range_start``
    and ``range_end`` bound the hours the job may occupy. Prices are not
    clipped: a negative hour can win.
    """
    prices = np.asarray(prices, dtype=float)
    if duration < 1 or len(prices) < duration:
        return None
    local = index.tz_convert(LOCAL_TZ)
    best = None
    for start in range(len(prices) - duration + 1):
        block = prices[start : start + duration]
        if not np.isfinite(block).all():
            continue
        hours = local[start : start + duration].hour.to_numpy()
        if not _inside_clock(hours, start_hour, end_hour):
            continue
        start_time = index[start]
        last_time = index[start + duration - 1]
        if range_start is not None and start_time < range_start:
            continue
        if range_end is not None and last_time > range_end:
            continue
        average = float(block.mean())
        if best is None or average < best["average_usd_per_mwh"]:
            best = {
                "average_usd_per_mwh": average,
                "window_start_utc": start_time,
                "window_end_utc": start_time + pd.Timedelta(hours=duration),
            }
    return best


def dlap_line(city: str, dlap: str, node_ids: list[str]) -> str:
    """One line so a cabinet buyer can see the load-zone node is a different price."""
    if not dlap:
        return f"load zone label: no DLAP is recorded for {city}"
    where = "the five proximity nodes" if len(node_ids) == 5 else "the proximity nodes above"
    if dlap in set(node_ids):
        return f"load zone label: {dlap} is the aggregation node for {city} and it is one of {where}"
    return (
        f"load zone label: {dlap} is the aggregation node for {city}, a different node from {where}. "
        "This folder does not forecast that load-zone price."
    )


def format_report(result: dict) -> str:
    """The text the command prints. Job cost is in dollars."""
    lines = [
        f"campus: {result['name']}",
        f"        {result['street']}, {result['city']} ({result['campus_id']})",
    ]
    if result["clamped_to_3_days"]:
        lines.append("days clamped to 3")
    if result.get("range_clamped"):
        lines.append("range clamped to the next 3 days")
    lines.append(
        f"job: {result['kw']:g} kW for {result['duration_hours']} hours ({result['job_kwh']:g} kWh)"
    )
    lines.append(
        f"horizon: {result['horizon_start_utc']} to {result['horizon_end_utc']} UTC "
        f"({result['horizon_hours']} hours)"
    )
    lines.append(
        "price: dollars per kilowatt-hour. The model predicts the day-ahead $/MWh price and this divides it by 1000."
    )
    lines.append("job cost: that price per kWh times the job's kWh.")
    if result.get("load_note"):
        lines.append(result["load_note"])
    for option in result["options"]:
        lines.append(
            f"rank {option['rank']}  {option['pnode_id']}  {option['distance_km']:.2f} km  {option['node_type']}"
        )
        if option["average_usd_per_mwh"] is None:
            lines.append("  no window inside the horizon and the daily hours")
            continue
        lines.append(f"  window: {option['window_start_pacific']} to {option['window_end_pacific']} Pacific")
        lines.append(f"          {option['window_start_utc']} to {option['window_end_utc']} UTC")
        lines.append(f"  average: {usd_per_kwh(option['average_usd_per_mwh']):.5f} $/kWh")
        lines.append(f"  job: {option['job_dollars']:.2f} dollars")
    winner = result["winner"]
    if winner is None:
        lines.append("winner: no node has a window inside the horizon and the daily hours")
    else:
        lines.append(
            f"winner: rank {winner['rank']} {winner['pnode_id']}  "
            f"average {usd_per_kwh(winner['average_usd_per_mwh']):.5f} $/kWh  "
            f"job {winner['job_dollars']:.2f} dollars"
        )
    lines.append(result["dlap_line"])
    return "\n".join(lines)


def recommend(
    site: str,
    duration: int,
    days: int,
    kw: float = DEFAULT_KW,
    start_hour: int | None = None,
    end_hour: int | None = None,
    range_start: str | pd.Timestamp | None = None,
    range_end: str | pd.Timestamp | None = None,
    *,
    table: pd.DataFrame | None = None,
    sites: pd.DataFrame | None = None,
    candidates: pd.DataFrame | None = None,
    saved: dict | None = None,
    weather: pd.DataFrame | None = None,
    load: pd.Series | None = None,
    umbrellas: pd.DataFrame | None = None,
    gas: pd.Series | None = None,
    horizon_limit: int = SEARCH_DAYS,
) -> dict:
    """Score the campus nodes and keep the cheapest block for the job.

    Args:
        site: Campus id, city, or street. Several matches are listed instead of guessed.
        duration: How many hours the job needs.
        days: How many days ahead to search. Clamped at three.
        kw: Cabinet power. The default is the 8 kW Inflect cabinet.
        start_hour: Earliest Pacific clock hour the block may occupy, inclusive.
        end_hour: Latest Pacific clock hour the block may occupy, inclusive.
        table: Dataset rows. Read from disk when omitted.
        sites: Campus table. Read from disk when omitted.
        candidates: Five nodes per campus. Read from disk when omitted.
        saved: Model bundle. Read from disk when omitted.
        weather: Day-5 forecast for the horizon. Fetched when a weather feature is required.
        load: Seven-day-ahead CAISO load for the horizon. Fetched when that feature is required.

    Returns:
        The five node windows, the winner, and the city's DLAP label.
    """
    if duration < 1:
        raise ValueError("duration must be at least 1 hour")
    if kw <= 0:
        raise ValueError("kw must be positive")
    _check_clock(start_hour, end_hour)
    horizon_days, clamped = clamp_days(days, horizon_limit)
    search_cap = min(int(horizon_limit), HORIZON_DAYS)
    if horizon_days * 24 < duration:
        raise ValueError("the job is longer than the horizon")
    if sites is None:
        sites = _read_sites()
    matched = match_campuses(sites, site)
    if matched.empty:
        raise ValueError(f"no campus matches {site!r}. Match a campus_id, city, or street.")
    if len(matched) > 1:
        raise AmbiguousSite(site, matched)
    if saved is None or table is None or candidates is None:
        saved, table, candidates = _load_model()
    campus = matched.iloc[0]
    features = list(saved["features"])
    leaked = illegal_feature_names(features)
    if leaked:
        raise ValueError(f"model features are not legal five days ahead: {leaked}")
    hours = _horizon(table, horizon_days)
    range_start_utc, range_end_utc, range_clamped = _clip_range(hours, range_start, range_end)
    nodes = candidates.loc[candidates["campus_id"].astype(str) == str(campus["campus_id"])].sort_values("rank")
    if nodes.empty:
        raise ValueError(f"no candidate nodes for {campus['campus_id']}")
    needs_weather = any(name in _METEO for name in features)
    if umbrellas is None and needs_weather and weather is None:
        umbrellas = _read_umbrellas()
    load_series, load_note = _resolve_load(features, hours, load)
    weather_cache: dict[tuple[float, float], pd.DataFrame | None] = {}
    options = []
    for node in nodes.itertuples(index=False):
        if weather is not None or not needs_weather:
            node_weather = weather
        else:
            latitude, longitude = _node_forecast_point(node, umbrellas, campus)
            key = (round(latitude, 4), round(longitude, 4))
            if key not in weather_cache:
                weather_cache[key] = _resolve_weather(features, latitude, longitude, hours, None)
            node_weather = weather_cache[key]
        prices = _prices(table, node.pnode_id)
        built = _feature_frame(hours, prices, _static(node), node_weather, load_series, features, gas=gas)
        predicted = predict_price(saved, built)
        # Load and the lagged gas print may be missing. The other features may not.
        required = [name for name in features if name not in {LOAD_FEATURE, GAS_FEATURE}]
        missing = built.loc[:, required].isna().any(axis=1).to_numpy()
        predicted = np.asarray(predicted, dtype=float)
        predicted[missing] = np.nan
        chosen = cheapest_block(
            hours,
            predicted,
            duration,
            start_hour,
            end_hour,
            range_start=range_start_utc,
            range_end=range_end_utc,
        )
        options.append(_option(node, chosen, kw, duration))
    ranked = [row for row in options if row["average_usd_per_mwh"] is not None]
    winner = min(ranked, key=lambda row: (row["average_usd_per_mwh"], row["rank"], row["pnode_id"])) if ranked else None
    node_ids = [row["pnode_id"] for row in options]
    dlap = _campus_dlap(campus)
    return {
        "campus_id": campus["campus_id"],
        "name": campus["name"],
        "city": campus["city"],
        "street": campus["street"],
        "dlap_id": dlap,
        "dlap_line": dlap_line(str(campus["city"]), dlap, node_ids),
        "duration_hours": duration,
        "horizon_days": horizon_days,
        "horizon_hours": int(len(hours)),
        "horizon_start_utc": str(hours[0]),
        "horizon_end_utc": str(hours[-1]),
        "clamped_to_3_days": bool(clamped and search_cap == SEARCH_DAYS),
        "range_clamped": range_clamped,
        "range_start_utc": str(range_start_utc),
        "range_end_utc": str(range_end_utc),
        "kw": kw,
        "job_kwh": job_kwh(kw, duration),
        "load_note": load_note,
        "options": options,
        "winner": winner,
    }


def _check_clock(start_hour: int | None, end_hour: int | None) -> None:
    if start_hour is None and end_hour is None:
        return
    if start_hour is None or end_hour is None:
        raise ValueError("pass both --start-hour and --end-hour, or neither")
    if not 0 <= start_hour <= 23:
        raise ValueError("start-hour must be a Pacific clock hour from 0 through 23")
    if not 0 <= end_hour <= 24:
        raise ValueError("end-hour must be a Pacific clock hour from 0 through 24")
    if end_hour < start_hour:
        raise ValueError("end-hour is earlier than start-hour")


def _inside_clock(hours: np.ndarray, start_hour: int | None, end_hour: int | None) -> bool:
    if start_hour is None:
        return True
    return bool(np.all((hours >= start_hour) & (hours <= end_hour)))


def _read_sites() -> pd.DataFrame:
    path = dataset_path().parent / "sites.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Build it with: python -m price_windows.build_dataset")
    return pd.read_csv(path)


def _load_model() -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    root = dataset_path().parent
    model_path = root / "model.joblib"
    if not dataset_path().exists():
        raise FileNotFoundError(f"{dataset_path()} is missing. Build it with: python -m price_windows.build_dataset")
    if not model_path.exists():
        raise FileNotFoundError(f"{model_path} is missing. Train it with: python -m price_windows.train_xgboost")
    saved = joblib.load(model_path)
    frame = pd.read_csv(dataset_path(), index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    candidates = pd.read_csv(root / "candidates.csv")
    return saved, frame.sort_index(), candidates


def _horizon(table: pd.DataFrame, days: int) -> pd.DatetimeIndex:
    """The next ``days`` times 24 hours after the last hour whose 120-hour lag exists."""
    if "lmp_lag_120" in table.columns:
        usable = table.loc[table["lmp_lag_120"].notna()]
        anchor = usable.index.max() if not usable.empty else table.index.max()
    else:
        anchor = table.index.max()
    start = pd.Timestamp(anchor).tz_convert("UTC").floor("h") + pd.Timedelta(hours=1)
    return pd.date_range(start, periods=days * 24, freq="h", tz="UTC")


def _prices(table: pd.DataFrame, pnode_id: str) -> pd.Series:
    """Hourly day-ahead price for one node, including hours recovered from legal lags."""
    part = table.loc[table["pnode_id"].astype(str) == str(pnode_id)]
    if part.empty or TARGET not in part.columns:
        return pd.Series(dtype=float)
    pieces = [_hourly_mean(part[TARGET])]
    for column in part.columns:
        match = _LAG_NAME.fullmatch(str(column))
        if not match:
            continue
        steps = int(match.group(1))
        if steps < MIN_LAG_HOURS:
            continue
        recovered = _hourly_mean(part[column])
        recovered.index = recovered.index - pd.Timedelta(hours=steps)
        pieces.append(recovered)
    stacked = pd.concat(pieces).dropna()
    if stacked.empty:
        return pd.Series(dtype=float)
    series = stacked.groupby(level=0).mean().sort_index()
    series.index = pd.to_datetime(series.index, utc=True)
    return series


def _hourly_mean(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").groupby(series.index).mean()
    values.index = pd.to_datetime(values.index, utc=True)
    return values


def _at_lag(prices: pd.Series, hours: pd.DatetimeIndex, steps: int) -> pd.Series:
    """Price ``steps`` hours before each horizon hour. A gap stays missing and does not shorten the lag."""
    if prices.empty:
        return pd.Series(np.nan, index=hours)
    start = min(prices.index.min(), hours.min() - pd.Timedelta(hours=steps))
    end = max(prices.index.max(), hours.max())
    full = pd.date_range(start, end, freq="h", tz="UTC")
    return prices.reindex(full).shift(steps).reindex(hours)


def _static(node) -> dict[str, float]:
    latitude = getattr(node, "node_latitude", None)
    longitude = getattr(node, "node_longitude", None)
    if latitude is None or (isinstance(latitude, float) and np.isnan(latitude)):
        latitude = node.latitude
    if longitude is None or (isinstance(longitude, float) and np.isnan(longitude)):
        longitude = node.longitude
    node_type = str(node.node_type)
    return {
        "node_latitude": float(latitude),
        "node_longitude": float(longitude),
        "distance_km": float(node.distance_km),
        "node_type_load": float("load" in node_type.lower()),
    }


def _feature_frame(hours, prices, static, weather, load, features: list[str], gas=None) -> pd.DataFrame:
    frame = _calendar(hours)
    for name in features:
        if name in CALENDAR_FEATURES:
            continue
        if name in STATIC_FEATURES:
            frame[name] = static[name]
            continue
        match = _LAG_NAME.fullmatch(name)
        if match:
            frame[name] = _at_lag(prices, hours, int(match.group(1)))
            continue
        if name == WEEK_COLUMN:
            parts = [_at_lag(prices, hours, step) for step in WEEK_LAGS]
            total = parts[0]
            for part in parts[1:]:
                total = total + part
            frame[name] = total / len(WEEK_LAGS)
            continue
        if name in WEATHER_FEATURES or name.endswith("_forecast_day5"):
            if weather is None or name not in weather.columns:
                frame[name] = np.nan
            else:
                frame[name] = pd.to_numeric(weather[name], errors="coerce").reindex(hours)
            continue
        if name == LOAD_FEATURE:
            if load is None or load.empty:
                frame[name] = np.nan
            else:
                frame[name] = pd.to_numeric(load, errors="coerce").reindex(hours)
            continue
        if name == GAS_FEATURE:
            if gas is None or gas.empty:
                frame[name] = np.nan
            else:
                frame[name] = pd.to_numeric(gas, errors="coerce").reindex(hours)
            continue
        raise ValueError(f"no way to build feature {name!r} for an hour after the dataset")
    return frame


def _as_pacific(value: str | pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize(LOCAL_TZ)
    return stamp.tz_convert(LOCAL_TZ)


def _clip_range(hours: pd.DatetimeIndex, range_start, range_end) -> tuple[pd.Timestamp, pd.Timestamp, bool]:
    """Keep the job inside the searched hours. A time outside them is clamped."""
    bound_start = pd.Timestamp(hours[0])
    bound_end = pd.Timestamp(hours[-1])
    if range_start is None and range_end is None:
        return bound_start, bound_end, False
    if range_start is None or range_end is None:
        raise ValueError("pass both --range-start and --range-end, or neither")
    start = _as_pacific(range_start).tz_convert("UTC")
    end = _as_pacific(range_end).tz_convert("UTC")
    if end < start:
        raise ValueError("range-end is earlier than range-start")
    clamped = bool(start < bound_start or end > bound_end)
    if start < bound_start:
        start = bound_start
    if end > bound_end:
        end = bound_end
    if end < start:
        raise ValueError("the range is outside the next 3 days")
    return start, end, clamped


def _read_umbrellas() -> pd.DataFrame | None:
    path = dataset_path().parent / "weather_umbrellas.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def _node_forecast_point(node, umbrellas: pd.DataFrame | None, campus: pd.Series) -> tuple[float, float]:
    """The umbrella coordinate the training row used for this node."""
    if umbrellas is not None and "pnode_id" in umbrellas.columns:
        match = umbrellas.loc[umbrellas["pnode_id"].astype(str) == str(node.pnode_id)]
        if not match.empty:
            return float(match.iloc[0]["umbrella_latitude"]), float(match.iloc[0]["umbrella_longitude"])
    return float(campus["latitude"]), float(campus["longitude"])


def _resolve_weather(features, latitude: float, longitude: float, hours, weather: pd.DataFrame | None) -> pd.DataFrame | None:
    needed = [name for name in features if name in _METEO]
    if not needed:
        return weather
    if weather is not None:
        return weather
    return _fetch_weather(float(latitude), float(longitude), hours, needed)


def _resolve_load(features, hours, load: pd.Series | None) -> tuple[pd.Series | None, str | None]:
    if LOAD_FEATURE not in features:
        return load, None
    if load is not None:
        return load, None
    series = _fetch_load(hours)
    if series.empty:
        return series, "7-day-ahead load forecast had no rows for this horizon; those cells are left missing"
    return series, None


def _fetch_weather(latitude: float, longitude: float, hours: pd.DatetimeIndex, columns: list[str]) -> pd.DataFrame:
    """The forecast issued five days before each horizon hour. Actual weather is not a substitute."""
    start = hours.min().tz_convert("UTC")
    end = hours.max().tz_convert("UTC")
    cache = dataset_path().parent / "cache" / "horizon_weather"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{latitude:.4f}_{longitude:.4f}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    if path.exists() and path.stat().st_size > 50:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        if all(column in frame.columns for column in columns):
            return frame
    url = "https://previous-runs-api.open-meteo.com/v1/forecast?" + urlencode(
        {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "hourly": ",".join(_METEO[column] for column in columns),
            "timezone": "UTC",
        }
    )
    payload = json.loads(_get(url).decode("utf-8"))
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        raise RuntimeError(f"Open-Meteo day-5 forecast missing for the horizon: {payload.get('reason')}")
    frame = pd.DataFrame(
        {column: hourly.get(_METEO[column]) for column in columns},
        index=pd.to_datetime(hourly["time"], utc=True),
    )
    frame.to_csv(path)
    return frame


def _fetch_load(hours: pd.DatetimeIndex) -> pd.Series:
    """Seven-day-ahead CAISO load for the horizon. An empty pull stays missing."""
    start = hours.min().tz_convert("UTC")
    end = hours.max().tz_convert("UTC") + pd.Timedelta(hours=1)
    cache = dataset_path().parent / "cache" / "horizon_load"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{start.strftime('%Y%m%d%H')}_{end.strftime('%Y%m%d%H')}.csv"
    if path.exists() and path.stat().st_size > 20:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        if LOAD_FEATURE in frame.columns and not frame.empty:
            return frame[LOAD_FEATURE]
    query = urlencode(
        [
            ("queryname", "SLD_FCST"),
            ("startdatetime", start.strftime("%Y%m%dT%H:%M-0000")),
            ("enddatetime", end.strftime("%Y%m%dT%H:%M-0000")),
            ("market_run_id", "7DA"),
            ("version", "1"),
            ("resultformat", "6"),
        ]
    )
    try:
        raw = _get(_OASIS + "?" + query)
    except (HTTPError, URLError, TimeoutError, RuntimeError):
        return pd.Series(dtype=float)
    frame = _oasis_table(raw)
    if frame.empty or "TAC_AREA_NAME" not in frame.columns:
        return pd.Series(dtype=float)
    total = frame.loc[frame["TAC_AREA_NAME"].astype(str).eq("CA ISO-TAC")].copy()
    if total.empty or "INTERVALSTARTTIME_GMT" not in total.columns:
        return pd.Series(dtype=float)
    total.index = pd.to_datetime(total["INTERVALSTARTTIME_GMT"], utc=True).dt.floor("h")
    total[LOAD_FEATURE] = pd.to_numeric(total["MW"], errors="coerce")
    series = total[LOAD_FEATURE].groupby(level=0).last().sort_index()
    series.to_frame().to_csv(path)
    return series


def _oasis_table(raw: bytes) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            name = archive.namelist()[0]
            payload = archive.read(name)
    except zipfile.BadZipFile:
        return pd.DataFrame()
    if payload.startswith(b"<?xml") or b"No data returned" in payload:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(payload))


def _get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                return response.read()
        except HTTPError as exc:
            exc.close()
            last_error = exc
            if exc.code != 429:
                raise
        except URLError as exc:
            last_error = exc
    raise RuntimeError(f"request failed: {url}") from last_error


def _campus_dlap(campus: pd.Series) -> str:
    if "dlap_id" in campus.index and pd.notna(campus["dlap_id"]) and str(campus["dlap_id"]).strip():
        return str(campus["dlap_id"]).strip()
    return dlap_for_city(str(campus["city"]))


def _option(node, chosen: dict | None, kw: float, duration: int) -> dict:
    row = {
        "rank": int(node.rank),
        "pnode_id": str(node.pnode_id),
        "node_type": str(node.node_type),
        "distance_km": float(node.distance_km),
        "average_usd_per_mwh": None,
        "job_dollars": None,
        "window_start_utc": None,
        "window_end_utc": None,
        "window_start_pacific": None,
        "window_end_pacific": None,
    }
    if chosen is None:
        return row
    start = chosen["window_start_utc"]
    end = chosen["window_end_utc"]
    average = chosen["average_usd_per_mwh"]
    row.update(
        {
            "average_usd_per_mwh": average,
            "job_dollars": job_dollars(average, kw, duration),
            "window_start_utc": str(start),
            "window_end_utc": str(end),
            "window_start_pacific": str(start.tz_convert(LOCAL_TZ)),
            "window_end_pacific": str(end.tz_convert(LOCAL_TZ)),
        }
    )
    return row


def _print_matches(query: str, matches: pd.DataFrame) -> None:
    print(f"Several campuses match {query!r}:")
    for row in matches.itertuples(index=False):
        print(f"  {row.campus_id}  {row.city}  {row.street}  {row.name}")
    print("Pass a campus_id or a street to pick one.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend the cheapest hours at the nearest P-nodes.")
    parser.add_argument("--site", required=True, help="campus id, city, or street")
    parser.add_argument("--duration", type=int, required=True, help="job length in hours")
    parser.add_argument("--days", type=int, default=SEARCH_DAYS, help="how many days ahead to search; above 3 is clamped")
    parser.add_argument("--kw", type=float, default=DEFAULT_KW, help="cabinet power in kW, default 8")
    parser.add_argument("--start-hour", type=int, default=None, help="earliest Pacific clock hour the block may occupy")
    parser.add_argument("--end-hour", type=int, default=None, help="latest Pacific clock hour the block may occupy")
    parser.add_argument("--range-start", default=None, help="earliest Pacific time the job may occupy, inside the next 3 days")
    parser.add_argument("--range-end", default=None, help="latest Pacific time the job may occupy, inside the next 3 days")
    args = parser.parse_args()
    try:
        result = recommend(
            args.site,
            args.duration,
            args.days,
            args.kw,
            args.start_hour,
            args.end_hour,
            args.range_start,
            args.range_end,
        )
    except AmbiguousSite as exc:
        _print_matches(exc.query, exc.matches)
        raise SystemExit(2) from exc
    print(format_report(result))
    if result["winner"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
