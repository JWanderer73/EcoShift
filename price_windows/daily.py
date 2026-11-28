"""Score the next three days from fresh prices without retraining.

The saved booster stays frozen. A lag of 72 hours is read from the price
cache, so tomorrow's forecast does not need another fit on the modeling
table. The command does not call the trainer and does not download the
history year again.

    python -m price_windows.daily

A node whose cache already reaches the newest published operating day is
skipped. HTTP 429 is retried the same way as the dataset build. If the
network still fails, the command scores whatever is cached and exits 0.
A second copy exits 0 without starting. A missing model exits 1 and does
not train.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

import price_windows.build_dataset as build
from price_windows.recommend import (
    _fetch_load,
    _fetch_weather,
    clamp_days,
    format_report,
    recommend,
)
from price_windows.schema import (
    BANNED_PARTS,
    DEFAULT_KW,
    GAS_FEATURE,
    HORIZON_DAYS,
    LOAD_FEATURE,
    LOCAL_TZ,
    MIN_LAG_HOURS,
    TARGET,
    WEATHER_FEATURES,
    illegal_feature_names,
)

# EIA bulk natural gas file. No API key. The Henry Hub spot series is one line.
EIA_NG_ZIP = "https://www.eia.gov/opendata/bulk/NG.zip"
HENRY_HUB_SERIES = "NG.RNGWHHD.D"
_USER_AGENT = "Mozilla/5.0 (compatible; ecoshift-price/1.0)"
_LMP_NAME = re.compile(r"^(?P<slug>.+)_(?P<start>\d{8})_(?P<end>\d{8})\.csv$")
# Enough history for a 336-hour lag at the far end of a five-day horizon.
_HISTORY_HOURS = 400
_GAS_MAX_AGE_SECONDS = 20 * 60 * 60


def folder() -> Path:
    """The price product directory."""
    return build.folder()


def acquire_lock(path: Path):
    """An exclusive lock, or None when another daily process holds it.

    The handle stays open until the caller closes it. Closing releases the lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def expected_published_hour(now: pd.Timestamp | None = None) -> pd.Timestamp:
    """Last hour of the newest operating day whose day-ahead prices should exist.

    CAISO posts the day-ahead market around 13:00 Pacific on the day before
    the operating day. A run at 07:15 already has today's prices. Before
    06:00 the expected hour is the end of yesterday.
    """
    moment = pd.Timestamp.now(tz=LOCAL_TZ) if now is None else pd.Timestamp(now)
    if moment.tzinfo is None:
        moment = moment.tz_localize(LOCAL_TZ)
    else:
        moment = moment.tz_convert(LOCAL_TZ)
    day = moment.normalize()
    if moment.hour < 6:
        day = day - pd.Timedelta(days=1)
    last = day + pd.Timedelta(hours=23)
    return last.tz_convert("UTC")


def _node_slug(node: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(node))


def lmp_paths(node: str, directory: Path) -> list[Path]:
    """Cached total-LMP files for one node, oldest end date first."""
    if not directory.exists():
        return []
    slug = _node_slug(node)
    found = []
    for path in directory.glob(f"{slug}_*.csv"):
        match = _LMP_NAME.match(path.name)
        if match and match.group("slug") == slug:
            found.append((match.group("end"), path.name, path))
    found.sort()
    return [item[-1] for item in found]


def newest_cached_hour(node: str, directory: Path) -> pd.Timestamp | None:
    """The latest cached hour for one node, or None when that node has no cache."""
    for path in reversed(lmp_paths(node, directory)):
        try:
            frame = pd.read_csv(path, usecols=["timestamp"])
        except (ValueError, OSError):
            continue
        if frame.empty:
            continue
        stamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dropna()
        if not stamps.empty:
            return pd.Timestamp(stamps.max())
    return None


def plan_lmp_fetches(newest: dict[str, pd.Timestamp | None], expected: pd.Timestamp) -> list[str]:
    """Nodes whose cache stops before the newest published hour.

    A node with no cache is left out. Filling it would download the history
    year, and this command does not do that.
    """
    due = []
    for node, stamp in newest.items():
        if stamp is None:
            continue
        if pd.Timestamp(stamp) < expected:
            due.append(node)
    return due


def read_recent_prices(node: str, directory: Path, hours: int = _HISTORY_HOURS) -> pd.Series:
    """The recent cached day-ahead price for one node. A hole stays missing."""
    frames = []
    for path in lmp_paths(node, directory)[-3:]:
        try:
            frame = pd.read_csv(path)
        except (ValueError, OSError):
            continue
        if "timestamp" not in frame.columns or TARGET not in frame.columns:
            continue
        frames.append(frame.loc[:, ["timestamp", TARGET]])
    if not frames:
        return pd.Series(dtype=float)
    whole = pd.concat(frames, ignore_index=True)
    whole["timestamp"] = pd.to_datetime(whole["timestamp"], utc=True, errors="coerce")
    whole[TARGET] = pd.to_numeric(whole[TARGET], errors="coerce")
    whole = whole.dropna(subset=["timestamp"]).drop_duplicates("timestamp", keep="last")
    series = whole.set_index("timestamp").sort_index()[TARGET]
    if series.empty:
        return series
    cutoff = series.index.max() - pd.Timedelta(hours=hours)
    return series.loc[series.index >= cutoff]


def _spans(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Chunks of at most 28 days. ``end`` is the last hour wanted."""
    cursor = pd.Timestamp(start).tz_convert("UTC").floor("h")
    stop = pd.Timestamp(end).tz_convert("UTC").floor("h") + pd.Timedelta(hours=1)
    spans = []
    while cursor < stop:
        nxt = min(cursor + pd.Timedelta(days=28), stop)
        spans.append((cursor, nxt))
        cursor = nxt
    return spans


def _oasis_frame(raw: bytes) -> pd.DataFrame:
    """The CSV inside one OASIS zip. An error page comes back empty."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if not names:
                return pd.DataFrame()
            with archive.open(names[0]) as handle:
                payload = handle.read()
    except zipfile.BadZipFile:
        return pd.DataFrame()
    if payload.startswith(b"<?xml") or b"No data returned" in payload:
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(payload))


def fetch_new_lmp(node: str, start: pd.Timestamp, end: pd.Timestamp, directory: Path) -> pd.DataFrame:
    """One day-ahead request for the hours the cache does not have yet.

    An empty response is not cached, so the next morning tries again.
    The call waits the same gap the dataset build uses, and ``build._get``
    retries HTTP 429.
    """
    params = [
        ("queryname", "PRC_LMP"),
        ("startdatetime", build._stamp(start)),
        ("enddatetime", build._stamp(end)),
        ("market_run_id", "DAM"),
        ("version", "1"),
        ("resultformat", "6"),
        ("node", node),
    ]
    url = build.OASIS + "?" + urlencode(params)
    raw = build._get(url)
    time.sleep(build._oasis_gap)
    kept = build._keep_total_lmp(_oasis_frame(raw))
    if kept.empty:
        return kept
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_node_slug(node)}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    kept.to_csv(path, index=False)
    return kept


def refresh_lmp(nodes: list[str], directory: Path, expected: pd.Timestamp) -> tuple[int, int, int]:
    """Fetch the gap since each node's newest cached hour.

    Returns counts of nodes refreshed, already current, and skipped for
    having no cache. A network error on one node is logged and the rest
    continue.
    """
    newest = {node: newest_cached_hour(node, directory) for node in nodes}
    due = plan_lmp_fetches(newest, expected)
    current = sum(stamp is not None and stamp >= expected for stamp in newest.values())
    uncached = sum(stamp is None for stamp in newest.values())
    refreshed = 0
    for node in due:
        stamp = newest[node]
        start = pd.Timestamp(stamp).tz_convert("UTC") + pd.Timedelta(hours=1)
        try:
            for span_start, span_end in _spans(start, expected):
                fetch_new_lmp(node, span_start, span_end, directory)
            refreshed += 1
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError) as exc:
            print(f"lmp {node} failed after retries: {exc}", flush=True)
            time.sleep(build._oasis_gap)
    if uncached:
        print(f"lmp skipped {uncached} nodes with no cache; the history year is not downloaded", flush=True)
    print(f"lmp refreshed {refreshed}, already current {current}, no cache {uncached}", flush=True)
    return refreshed, current, uncached


def _get_bytes(url: str, timeout: int = 120, attempts: int = 3) -> bytes:
    """A short GET for the gas file. OASIS keeps its own longer retry."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            exc.close()
            last = exc
            if exc.code != 429 or attempt + 1 == attempts:
                raise
            time.sleep(20)
        except (URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt + 1 == attempts:
                raise
            time.sleep(5)
    raise RuntimeError(f"request failed: {url}") from last


def parse_henry_hub_zip(raw: bytes) -> pd.Series:
    """Daily Henry Hub spot, indexed at UTC midnight of the trading date."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if not names:
            return pd.Series(dtype=float)
        with archive.open(names[0]) as handle:
            for line in handle:
                if HENRY_HUB_SERIES.encode() not in line:
                    continue
                payload = json.loads(line)
                if payload.get("series_id") != HENRY_HUB_SERIES:
                    continue
                rows = payload.get("data") or []
                if not rows:
                    return pd.Series(dtype=float)
                frame = pd.DataFrame(rows, columns=["date", "usd_per_mmbtu"])
                stamps = pd.to_datetime(frame["date"], utc=True, errors="coerce")
                values = pd.to_numeric(frame["usd_per_mmbtu"], errors="coerce")
                series = pd.Series(values.to_numpy(), index=stamps).dropna()
                series = series[~series.index.isna()].sort_index()
                series = series[~series.index.duplicated(keep="last")]
                return series
    return pd.Series(dtype=float)


def read_henry_hub(path: Path) -> pd.Series:
    """The cached daily spot, or an empty series when the file is absent."""
    if not path.exists() or path.stat().st_size < 10:
        return pd.Series(dtype=float)
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame.empty or "usd_per_mmbtu" not in frame.columns:
        return pd.Series(dtype=float)
    stamps = pd.to_datetime(frame["date"], utc=True, errors="coerce")
    values = pd.to_numeric(frame["usd_per_mmbtu"], errors="coerce")
    series = pd.Series(values.to_numpy(), index=stamps).dropna()
    return series[~series.index.isna()].sort_index()


def refresh_henry_hub(cache: Path) -> pd.Series:
    """Cache the EIA daily spot. A failed download leaves the old file in place.

    This series is not required. The morning score still runs when it is missing.
    """
    path = cache / "gas" / "henry_hub_daily.csv"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < _GAS_MAX_AGE_SECONDS
    if fresh:
        return read_henry_hub(path)
    try:
        series = parse_henry_hub_zip(_get_bytes(EIA_NG_ZIP))
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"henry hub download failed; the morning score does not need it: {exc}", flush=True)
        return read_henry_hub(path)
    if series.empty:
        print("henry hub file had no daily spot; the morning score does not need it", flush=True)
        return read_henry_hub(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = series.rename("usd_per_mmbtu").rename_axis("date").reset_index()
    out.to_csv(path, index=False)
    return series


def henry_hub_for_hours(daily: pd.Series | None, hours: pd.DatetimeIndex) -> pd.Series:
    """The latest Henry Hub print dated at least 72 hours before each hour.

    A print from the last few days is left out. An empty series stays missing
    and does not raise.
    """
    if daily is None or len(daily) == 0 or len(hours) == 0:
        return pd.Series(np.nan, index=hours, dtype=float)
    daily = pd.to_numeric(daily, errors="coerce")
    daily.index = pd.to_datetime(daily.index, utc=True)
    daily = daily[~daily.index.isna()].sort_index()
    daily = daily[~daily.index.duplicated(keep="last")].dropna()
    if daily.empty:
        return pd.Series(np.nan, index=hours, dtype=float)
    stamps = pd.DatetimeIndex(daily.index)
    values = daily.to_numpy(dtype=float)
    cutoff = pd.DatetimeIndex(hours).tz_convert("UTC") - pd.Timedelta(hours=MIN_LAG_HOURS)
    position = stamps.searchsorted(cutoff, side="right") - 1
    out = np.full(len(hours), np.nan, dtype=float)
    usable = position >= 0
    out[np.asarray(usable)] = values[position[np.asarray(usable)]]
    return pd.Series(out, index=hours)


def load_price_table(nodes: list[str], directory: Path) -> pd.DataFrame:
    """Recent cached prices, one row per node-hour. Not the modeling table."""
    frames = []
    for node in nodes:
        series = read_recent_prices(node, directory)
        if series.empty:
            continue
        block = series.to_frame(TARGET)
        block["pnode_id"] = node
        block.index.name = "timestamp"
        frames.append(block)
    if not frames:
        return pd.DataFrame(columns=[TARGET, "pnode_id"])
    return pd.concat(frames).sort_index()


def score_campuses(
    sites: pd.DataFrame,
    candidates: pd.DataFrame,
    table: pd.DataFrame,
    saved: dict,
    *,
    days: int = HORIZON_DAYS,
    kw: float = DEFAULT_KW,
    duration: int = 4,
    weather: pd.DataFrame | None = None,
    load: pd.Series | None = None,
    gas: pd.Series | None = None,
    umbrellas: pd.DataFrame | None = None,
) -> tuple[list[dict], bool]:
    """Score every campus with the frozen model. Does not train and does not download.

    A feature list with a short price lag or a banned price component is refused.
    ``days`` above three is clamped.
    """
    features = list(saved["features"])
    leaked = illegal_feature_names(features)
    if leaked:
        raise ValueError(f"model features are not legal three days ahead: {leaked}")
    for name in features:
        if any(part in name.casefold() for part in BANNED_PARTS):
            raise ValueError(f"model features are not legal three days ahead: {[name]}")
    days, clamped = clamp_days(int(days), HORIZON_DAYS)
    if table.empty:
        return [], clamped
    load_series = load if load is not None else pd.Series(dtype=float)
    results = []
    for campus_id in sites["campus_id"].astype(str):
        results.append(
            recommend(
                campus_id,
                duration,
                days,
                kw,
                table=table,
                sites=sites,
                candidates=candidates,
                saved=saved,
                weather=weather,
                load=load_series,
                gas=gas,
                umbrellas=umbrellas,
                horizon_limit=HORIZON_DAYS,
            )
        )
    return results, clamped


def _report_text(results: list[dict], *, when: pd.Timestamp, days: int, clamped: bool, kw: float, duration: int, gas_note: str) -> str:
    local = pd.Timestamp(when).tz_convert(LOCAL_TZ)
    lines = [
        f"price windows daily {local.strftime('%Y-%m-%d')}",
        "model: frozen model.joblib. This command does not train.",
        f"cabinet: {kw:g} kW for {duration} hours",
        f"horizon: next {days} days",
    ]
    if clamped:
        lines.append("days clamped to 3")
    lines.append(gas_note)
    if not results:
        lines.append("no campus could be scored from the cache")
    for result in results:
        lines.append("")
        lines.append(format_report(result))
    return "\n".join(lines) + "\n"


def _gas_note(features: list[str], gas: pd.Series | None) -> str:
    if GAS_FEATURE not in features:
        return (
            f"{GAS_FEATURE} is cached when EIA is reachable and is not in the saved model, "
            "so this score does not use it."
        )
    if gas is None or gas.dropna().empty:
        return f"{GAS_FEATURE} is missing. Those cells stay blank and the score still runs."
    return f"{GAS_FEATURE} is the Henry Hub print from at least {MIN_LAG_HOURS} hours earlier."


def _prefetch_weather(saved: dict, hours: pd.DatetimeIndex, umbrellas: pd.DataFrame | None) -> bool:
    needed = [name for name in saved["features"] if name in WEATHER_FEATURES]
    if not needed or umbrellas is None or umbrellas.empty:
        return True
    points = umbrellas.loc[:, ["umbrella_latitude", "umbrella_longitude"]].drop_duplicates()
    failed = False
    for point in points.itertuples(index=False):
        try:
            _fetch_weather(float(point.umbrella_latitude), float(point.umbrella_longitude), hours, needed)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError, ValueError) as exc:
            print(f"day-3 weather failed after retries: {exc}", flush=True)
            failed = True
    return not failed


def _prefetch_load(features: list[str], hours: pd.DatetimeIndex) -> pd.Series:
    if LOAD_FEATURE not in features:
        return pd.Series(dtype=float)
    try:
        time.sleep(build._oasis_gap)
        return _fetch_load(hours)
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError) as exc:
        print(f"7-day load forecast failed after retries: {exc}", flush=True)
        return pd.Series(dtype=float)


def run_daily(
    root: Path | None = None,
    *,
    now: pd.Timestamp | None = None,
    fetch: bool = True,
    days: int = HORIZON_DAYS,
    duration: int = 4,
    kw: float = DEFAULT_KW,
) -> int:
    """Refresh the cache, score every campus, and write a dated report.

    Returns 0 when the score is written, when the network fails, or when a
    copy is already running. Returns 1 when ``model.joblib`` is missing.
    """
    root = folder() if root is None else Path(root)
    lock = acquire_lock(root / "cache" / "daily.lock")
    if lock is None:
        print("daily job already running; leaving it", flush=True)
        return 0
    try:
        return _run_locked(root, now=now, fetch=fetch, days=days, duration=duration, kw=kw)
    finally:
        lock.close()


def _run_locked(root: Path, *, now, fetch: bool, days: int, duration: int, kw: float) -> int:
    model_path = root / "model.joblib"
    if not model_path.exists():
        print(
            "price_windows/model.joblib is missing. The morning job does not train. "
            "Run python -m price_windows.train_xgboost once, then rerun python -m price_windows.daily.",
            flush=True,
        )
        return 1
    sites_path = root / "sites.csv"
    nodes_path = root / "candidates.csv"
    if not sites_path.exists() or not nodes_path.exists():
        print("sites.csv or candidates.csv is missing. The morning job does not rebuild them.", flush=True)
        return 1
    import joblib

    saved = joblib.load(model_path)
    features = list(saved.get("features", []))
    leaked = illegal_feature_names(features)
    if leaked:
        print(f"saved model features are not legal three days ahead: {leaked}", flush=True)
        return 1
    sites = pd.read_csv(sites_path)
    candidates = pd.read_csv(nodes_path)
    nodes = sorted(candidates["pnode_id"].astype(str).unique())
    lmp_dir = root / "cache" / "lmp"
    moment = pd.Timestamp.now(tz=LOCAL_TZ) if now is None else pd.Timestamp(now)
    if moment.tzinfo is None:
        moment = moment.tz_localize(LOCAL_TZ)
    expected = expected_published_hour(moment)
    if fetch:
        try:
            refresh_lmp(nodes, lmp_dir, expected)
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError) as exc:
            print(f"lmp refresh failed after retries: {exc}", flush=True)
    table = load_price_table(nodes, lmp_dir)
    if table.empty:
        print("no cached day-ahead prices; nothing to score", flush=True)
        return 0
    anchor = pd.Timestamp(table.index.max())
    horizon_days, clamped_days = clamp_days(int(days), HORIZON_DAYS)
    start = anchor.tz_convert("UTC").floor("h") + pd.Timedelta(hours=1)
    hours = pd.date_range(start, periods=horizon_days * 24, freq="h", tz="UTC")
    umbrella_path = root / "weather_umbrellas.csv"
    umbrellas = pd.read_csv(umbrella_path) if umbrella_path.exists() else None
    load = pd.Series(dtype=float)
    gas_daily = pd.Series(dtype=float)
    if fetch:
        _prefetch_weather(saved, hours, umbrellas)
        load = _prefetch_load(features, hours)
        try:
            gas_daily = refresh_henry_hub(root / "cache")
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError, ValueError) as exc:
            print(f"henry hub failed after retries: {exc}", flush=True)
            gas_daily = pd.Series(dtype=float)
    else:
        gas_daily = read_henry_hub(root / "cache" / "gas" / "henry_hub_daily.csv")
    gas = henry_hub_for_hours(gas_daily, hours) if GAS_FEATURE in features else None
    try:
        results, clamped = score_campuses(
            sites,
            candidates,
            table,
            saved,
            days=horizon_days,
            kw=kw,
            duration=duration,
            weather=None,
            load=load,
            gas=gas,
            umbrellas=umbrellas,
        )
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ConnectionError) as exc:
        print(f"score failed after retries: {exc}", flush=True)
        return 0
    text = _report_text(
        results,
        when=moment,
        days=horizon_days,
        clamped=clamped or clamped_days,
        kw=kw,
        duration=duration,
        gas_note=_gas_note(features, gas if GAS_FEATURE in features else gas_daily),
    )
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{moment.tz_convert(LOCAL_TZ).strftime('%Y-%m-%d')}.txt"
    report_path.write_text(text)
    print(f"wrote {report_path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score the next three days from the frozen price model.")
    parser.add_argument("--days", type=int, default=HORIZON_DAYS, help="days ahead; above 3 is clamped")
    parser.add_argument("--duration", type=int, default=4, help="job length in hours")
    parser.add_argument("--kw", type=float, default=DEFAULT_KW, help="cabinet power in kW, default 8")
    args = parser.parse_args(argv)
    raise SystemExit(run_daily(days=args.days, duration=args.duration, kw=args.kw))


if __name__ == "__main__":
    main(sys.argv[1:])
