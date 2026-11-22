"""Build the day-ahead price table for Inflect's California datacenter campuses.

The target is the CAISO day-ahead locational marginal price, in dollars per
megawatt-hour, at the five P-nodes nearest each campus. Every price feature
is at least five days old. Congestion, loss, and the energy component are
never read into a lag, because those three numbers are the price taken apart.
Weather is the forecast that existed five days before the hour, not the
weather that actually arrived.

    python -m price_windows.build_dataset
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from price_windows.schema import (
    CALENDAR_FEATURES,
    HISTORY_END,
    HISTORY_START,
    LMP_LAG_168,
    LMP_LAGS,
    LOAD_FEATURE,
    LOCAL_TZ,
    STATIC_FEATURES,
    TARGET,
    TEST_DAYS,
    WEATHER_FEATURES,
    WEEK_COLUMN,
    WEEK_LAGS,
    assign_umbrellas,
    dlap_for_city,
    feature_columns,
    forecast_points,
    haversine_km,
    illegal_feature_names,
    nearest_five,
)
from src.build_demand_dataset import content_hash, us_holidays
from src.carbon_data import repo_root

INFLECT_PAGES = [
    "https://inflect.com/datacenters/na/usa/california",
    "https://inflect.com/datacenters/na/usa/california/fresno",
    "https://inflect.com/datacenters/na/usa/california/los-angeles",
    "https://inflect.com/datacenters/na/usa/california/modesto",
    "https://inflect.com/datacenters/na/usa/california/orange-county",
    "https://inflect.com/datacenters/na/usa/california/riverside",
    "https://inflect.com/datacenters/na/usa/california/sacramento",
    "https://inflect.com/datacenters/na/usa/california/san-diego",
    "https://inflect.com/datacenters/na/usa/california/san-francisco",
    "https://inflect.com/datacenters/na/usa/california/san-luis-obispo",
    "https://inflect.com/datacenters/na/usa/california/santa-rosa",
    "https://inflect.com/datacenters/na/usa/california/silicon-valley",
    "https://inflect.com/datacenters/na/usa/california/stockton",
]
COORDINATE_URL = (
    "https://raw.githubusercontent.com/emunsing/CAISO-Scrapers/master/"
    "LMP%20Location%20Scraper/LMPLocations.csv"
)
LISTING = re.compile(
    r'<h3 class="font-semibold tracking-tight text-lg">([^<]+)</h3>'
    r'<p class="text-sm text-gray-400">([^<]+)</p>'
)
ADDRESS = re.compile(r"^(?P<before>.+) CA (?P<zip>\d{5}) USA, (?P<city>.+)$")
USER_AGENT = "Mozilla/5.0 (compatible; ecoshift-price/1.0)"
OASIS = "http://oasis.caiso.com/oasisapi/SingleZip"
# Five seconds between calls. A 429 widens this for the rest of the run:
# a few hundred requests at the floor is what gets the feed to close.
_oasis_gap = 5.0


def folder() -> Path:
    """The price product directory."""
    return repo_root() / "price_windows"


def cache_dir() -> Path:
    """Downloaded pages. Safe to delete; the build fills them again."""
    path = folder() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_path() -> Path:
    """The modeling table."""
    return folder() / "price_dataset.csv"


def meta_path() -> Path:
    """Metadata beside the modeling table."""
    return dataset_path().with_suffix(".meta.json")


def _get(url: str, timeout: int = 90) -> bytes:
    """HTTP GET with retries when OASIS is busy.

    429 is the rate limit. 302 is the redirect loop OASIS returns when it is
    overloaded. The response is closed before this returns so a retry does
    not leak a socket.
    """
    global _oasis_gap
    request = Request(url, headers={"User-Agent": USER_AGENT})
    # One stuck OASIS call must not throw away the chunks already cached.
    deadline = time.monotonic() + 25 * 60
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            exc.close()
            if exc.code not in {302, 429, 500, 502, 503, 504} or time.monotonic() > deadline:
                raise
            attempt += 1
            if exc.code in {302, 429}:
                _oasis_gap = min(12.0, _oasis_gap + 3.0)
            pause = 300 if exc.code in {302, 429} else 20
            print(
                f"retry HTTP {exc.code} attempt {attempt}, pausing {pause}s, gap now {_oasis_gap:.0f}s",
                flush=True,
            )
            time.sleep(pause)
        except (TimeoutError, URLError, ConnectionError, IncompleteRead) as exc:
            if time.monotonic() > deadline:
                raise
            attempt += 1
            print(f"retry {type(exc).__name__} attempt {attempt}", flush=True)
            time.sleep(20)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:80] or "campus"


def _pages() -> list[tuple[str, str]]:
    """Inflect directory HTML, cached after the first download."""
    pages = []
    for url in INFLECT_PAGES:
        name = url.rstrip("/").split("/")[-1]
        path = cache_dir() / f"inflect_{name}.html"
        if not path.exists() or path.stat().st_size < 1000:
            path.write_bytes(_get(url))
            time.sleep(0.4)
        pages.append((url, path.read_text(errors="replace")))
    return pages


def _split_address(address: str) -> dict | None:
    """Street, city, and ZIP from Inflect's one-line address. None when it is not in California."""
    match = ADDRESS.match(address.strip())
    if not match:
        return None
    city = match.group("city").strip()
    street = match.group("before").strip()
    if street.lower().endswith(" " + city.lower()):
        street = street[: -(len(city) + 1)].strip()
    if not street or not city:
        return None
    return {"street": street, "city": city, "zip": match.group("zip")}


def _balanced_json(text: str, start: int) -> str:
    """The JSON array that begins at ``start``, including its closing bracket."""
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unterminated JSON array in an Inflect page")


def _flight_text(html: str) -> str:
    """The Next.js payload embedded in the directory page. Empty when the page has none."""
    parts = re.findall(r"self\.__next_f\.push\(\[1,(.*?)\]\)\s*</script>", html, flags=re.S)
    decoded = []
    for part in parts:
        try:
            decoded.append(json.loads(part))
        except json.JSONDecodeError:
            continue
    return "\n".join(chunk for chunk in decoded if isinstance(chunk, str))


def _parse_page(html: str, source_url: str) -> list[dict]:
    """Listings on one directory page.

    The rendered cards stop at 100, and Silicon Valley has more than that.
    The page payload has every listing, including the operator. The cards are
    the fallback when that payload is missing.
    """
    rows = []
    flight = _flight_text(html)
    cursor = 0
    while flight and (found := re.search(r'"datacenters"\s*:\s*\[', flight[cursor:])):
        bracket = cursor + found.end() - 1
        for item in json.loads(_balanced_json(flight, bracket)):
            parsed = _split_address(str(item.get("address") or ""))
            if parsed is None:
                continue
            owner = item.get("owner") or {}
            rows.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "operator": str(owner.get("name") or "").strip(),
                    "source_url": source_url,
                    **parsed,
                }
            )
        cursor = bracket + 1
    if rows:
        return rows
    for name, address in LISTING.findall(html):
        parsed = _split_address(address)
        if parsed is None:
            continue
        rows.append({"name": name.strip(), "operator": "", "source_url": source_url, **parsed})
    return rows


def _listings() -> pd.DataFrame:
    """Every datacenter listing on the California pages, one row per name and address."""
    rows = []
    for url, html in _pages():
        rows.extend(_parse_page(html, url))
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("Inflect pages contained no California datacenter listings")
    return frame.drop_duplicates(["name", "street", "zip"]).reset_index(drop=True)


def _campuses(listings: pd.DataFrame) -> pd.DataFrame:
    """One campus per street address. Tenants in the same building share a row."""
    grouped = []
    for (street, city, zip_code), block in listings.groupby(["street", "city", "zip"], sort=False):
        names = sorted(block["name"].unique())
        grouped.append(
            {
                "campus_id": _slug(f"{city}-{street}"),
                "name": names[0],
                "street": street,
                "city": city,
                "zip": zip_code,
                "dlap_id": dlap_for_city(city),
            }
        )
    frame = pd.DataFrame(grouped)
    collisions = frame["campus_id"].duplicated(keep=False)
    if collisions.any():
        frame.loc[collisions, "campus_id"] = [
            _slug(f"{row.city}-{row.street}-{row.zip}") for row in frame.loc[collisions].itertuples(index=False)
        ]
    if frame["campus_id"].duplicated().any():
        raise RuntimeError("two campuses collapsed to the same id")
    return frame.reset_index(drop=True)


def _geocode_one(campus: dict) -> dict:
    """Latitude and longitude. Open-Meteo first, then the Census street geocoder."""
    path = cache_dir() / "geocode" / f"{campus['campus_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        saved = json.loads(path.read_text())
        return {**campus, **saved}
    query = f"{campus['street']}, {campus['city']}, CA {campus['zip']}"
    found = _open_meteo_point(query)
    source = "open-meteo"
    if found is None:
        found = _census_point(query)
        source = "census"
    if found is None:
        payload = {"latitude": None, "longitude": None, "geocode_source": "missing"}
    else:
        payload = {"latitude": found[0], "longitude": found[1], "geocode_source": source}
    path.write_text(json.dumps(payload))
    time.sleep(0.15)
    return {**campus, **payload}


def _open_meteo_point(query: str) -> tuple[float, float] | None:
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {"name": query, "count": 1, "language": "en", "format": "json"}
    )
    payload = json.loads(_get(url, timeout=30))
    results = payload.get("results") or []
    if not results:
        return None
    hit = results[0]
    if hit.get("country_code") not in (None, "US"):
        return None
    if hit.get("admin1") not in (None, "California"):
        return None
    return float(hit["latitude"]), float(hit["longitude"])


def _census_point(query: str) -> tuple[float, float] | None:
    """Street-level coordinates. Open-Meteo search does not resolve a street address."""
    url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?" + urlencode(
        {"address": query, "benchmark": "Public_AR_Current", "format": "json"}
    )
    payload = json.loads(_get(url, timeout=30))
    matches = payload.get("result", {}).get("addressMatches") or []
    if not matches:
        return None
    point = matches[0]["coordinates"]
    return float(point["y"]), float(point["x"])


def _geocode(campuses: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    kept = []
    missed = []
    for campus in campuses.to_dict(orient="records"):
        located = _geocode_one(campus)
        if located["latitude"] is None:
            missed.append(f"{campus['name']}, {campus['street']}, {campus['city']}")
            continue
        kept.append(located)
    if not kept:
        raise RuntimeError("every campus failed geocoding")
    return pd.DataFrame(kept), missed


def _oasis_csv(params: list[tuple[str, str]], cache_name: str) -> pd.DataFrame:
    """One OASIS zip, cached. An empty or error span comes back as an empty frame."""
    path = cache_dir() / "oasis" / cache_name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 40:
        return pd.read_csv(path)
    url = OASIS + "?" + urlencode(params)
    raw = _get(url)
    time.sleep(_oasis_gap)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            name = archive.namelist()[0]
            payload = archive.read(name)
    except zipfile.BadZipFile:
        path.write_text("XML_DATA_ITEM,INTERVALSTARTTIME_GMT,MW,note\n")
        return pd.DataFrame()
    if name.endswith(".xml") or payload.startswith(b"<?xml"):
        if b"No data returned" in payload or b"31 days" in payload:
            path.write_text("XML_DATA_ITEM,INTERVALSTARTTIME_GMT,MW,note\n")
            return pd.DataFrame()
        text = payload.decode("utf-8", "replace")
        raise RuntimeError(f"OASIS refused {cache_name}: {text[text.find('ERR_DESC'):text.find('ERR_DESC')+160]}")
    frame = pd.read_csv(io.BytesIO(payload))
    frame.to_csv(path, index=False)
    return frame


def _spans() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """28-day windows covering the training year. OASIS rejects a longer request."""
    cursor = pd.Timestamp(HISTORY_START, tz="UTC")
    stop = pd.Timestamp(HISTORY_END, tz="UTC") + pd.Timedelta(days=1)
    spans = []
    while cursor < stop:
        end = min(cursor + pd.Timedelta(days=28), stop)
        spans.append((cursor, end))
        cursor = end
    return spans


def _stamp(moment: pd.Timestamp) -> str:
    return moment.strftime("%Y%m%dT%H:%M-0000")


def _active_nodes() -> pd.DataFrame:
    """Live P-node ids that also have a public latitude and longitude."""
    day = pd.Timestamp("2026-11-14", tz="UTC")
    start, end = day, day + pd.Timedelta(days=1)
    atlas = _oasis_csv(
        [
            ("queryname", "ATL_PNODE"),
            ("startdatetime", _stamp(start)),
            ("enddatetime", _stamp(end)),
            ("version", "1"),
            ("resultformat", "6"),
        ],
        "atl_pnode.csv",
    )
    if atlas.empty or "PNODE_ID" not in atlas.columns:
        raise RuntimeError("OASIS returned no P-node atlas")
    coords_path = cache_dir() / "lmp_locations.csv"
    if not coords_path.exists():
        coords_path.write_bytes(_get(COORDINATE_URL))
    coords = pd.read_csv(coords_path)
    coords = coords.rename(columns={"name": "pnode_id", "type": "node_type"})
    coords["pnode_id"] = coords["pnode_id"].astype(str)
    active = set(atlas["PNODE_ID"].astype(str))
    located = coords[coords["pnode_id"].isin(active)].drop_duplicates("pnode_id")
    located = located.dropna(subset=["latitude", "longitude"])
    if located.empty:
        raise RuntimeError("no active P-node had coordinates")
    return located.loc[:, ["pnode_id", "node_type", "latitude", "longitude"]].reset_index(drop=True)


def _candidates(campuses: pd.DataFrame, nodes: pd.DataFrame) -> pd.DataFrame:
    """Five nearest located nodes for every campus."""
    frames = []
    for campus in campuses.itertuples(index=False):
        chosen = nearest_five(campus.latitude, campus.longitude, nodes)
        if len(chosen) < 5:
            raise RuntimeError(f"{campus.campus_id} has only {len(chosen)} located nodes")
        chosen.insert(0, "campus_id", campus.campus_id)
        frames.append(chosen)
    return pd.concat(frames, ignore_index=True)


def _keep_total_lmp(frame: pd.DataFrame) -> pd.DataFrame:
    """The total day-ahead price only. Component rows are discarded before any lag.

    OASIS puts the dollars-per-megawatt-hour number in a column named ``MW``.
    A negative price is kept. Congestion, loss, energy, and greenhouse gas are not.
    """
    empty = pd.DataFrame(columns=["timestamp", TARGET])
    if frame.empty or "XML_DATA_ITEM" not in frame.columns:
        return empty
    total = frame.loc[frame["XML_DATA_ITEM"].astype(str).str.upper().eq("LMP_PRC"), ["INTERVALSTARTTIME_GMT", "MW"]].copy()
    if total.empty:
        return empty
    total["timestamp"] = pd.to_datetime(total["INTERVALSTARTTIME_GMT"], utc=True).dt.floor("h")
    total[TARGET] = pd.to_numeric(total["MW"], errors="coerce")
    return total.loc[:, ["timestamp", TARGET]]


def _lmp_chunk(node: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Total day-ahead LMP only. Component rows are dropped before the frame is cached."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", node)
    filtered = cache_dir() / "lmp" / f"{safe}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    filtered.parent.mkdir(parents=True, exist_ok=True)
    if filtered.exists():
        frame = pd.read_csv(filtered, parse_dates=["timestamp"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame
    raw_name = f"lmp_raw_{safe}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
    frame = _oasis_csv(
        [
            ("queryname", "PRC_LMP"),
            ("startdatetime", _stamp(start)),
            ("enddatetime", _stamp(end)),
            ("market_run_id", "DAM"),
            ("version", "1"),
            ("resultformat", "6"),
            ("node", node),
        ],
        raw_name,
    )
    if (frame.empty or "XML_DATA_ITEM" not in frame.columns) and end - start > pd.Timedelta(days=7):
        weeks = []
        cursor = start
        while cursor < end:
            week_end = min(cursor + pd.Timedelta(days=7), end)
            weeks.append(_lmp_chunk(node, cursor, week_end))
            cursor = week_end
        present = [week for week in weeks if not week.empty]
        result = pd.concat(present, ignore_index=True) if present else pd.DataFrame(columns=["timestamp", TARGET])
        result.to_csv(filtered, index=False)
        return result
    result = _keep_total_lmp(frame)
    result.to_csv(filtered, index=False)
    return result


def _with_lags(hourly: pd.Series) -> pd.DataFrame:
    """Price lags on a complete hourly index.

    A missing hour stays missing. The lag is 120 clock hours, not 120 rows,
    so a hole in the archive does not pull a nearer price into the feature.
    """
    hourly = hourly.sort_index()
    hourly = hourly[~hourly.index.duplicated(keep="last")]
    full = pd.date_range(hourly.index.min(), hourly.index.max(), freq="h", tz="UTC")
    hourly = hourly.reindex(full)
    frame = pd.DataFrame({TARGET: hourly})
    for hours in set(LMP_LAGS) | set(WEEK_LAGS):
        frame[f"lmp_lag_{hours}"] = hourly.shift(int(hours))
    frame[WEEK_COLUMN] = sum(frame[f"lmp_lag_{hours}"] for hours in WEEK_LAGS) / len(WEEK_LAGS)
    frame.index.name = "timestamp"
    return frame


def _prices(nodes: list[str]) -> pd.DataFrame:
    """Day-ahead total LMP for each distinct candidate node, one node per request."""
    frames = []
    for index, node in enumerate(nodes, start=1):
        print(f"lmp {index}/{len(nodes)} {node}")
        chunks = [_lmp_chunk(node, start, end) for start, end in _spans()]
        present = [chunk for chunk in chunks if not chunk.empty]
        if not present:
            print(f"  no day-ahead price for {node}")
            continue
        series = pd.concat(present, ignore_index=True)
        series = series.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        lagged = _with_lags(series[TARGET])
        lagged["pnode_id"] = node
        frames.append(lagged.reset_index(names="timestamp"))
    if not frames:
        raise RuntimeError("OASIS returned no day-ahead prices for the candidate nodes")
    return pd.concat(frames, ignore_index=True)


def _weather_one(latitude: float, longitude: float) -> pd.DataFrame:
    path = cache_dir() / "weather" / f"{latitude:.4f}_{longitude:.4f}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 100:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        return frame
    url = "https://previous-runs-api.open-meteo.com/v1/forecast?" + urlencode(
        {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "start_date": HISTORY_START,
            "end_date": HISTORY_END,
            "hourly": ",".join(
                [
                    "temperature_2m_previous_day5",
                    "cloud_cover_previous_day5",
                    "wind_speed_10m_previous_day5",
                    "shortwave_radiation_previous_day5",
                ]
            ),
            "timezone": "UTC",
        }
    )
    payload = json.loads(_get(url, timeout=120))
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        raise RuntimeError(f"Open-Meteo day-5 forecast missing for {latitude}, {longitude}: {payload.get('reason')}")
    frame = pd.DataFrame(
        {
            "temperature_forecast_day5": hourly.get("temperature_2m_previous_day5"),
            "cloud_cover_forecast_day5": hourly.get("cloud_cover_previous_day5"),
            "wind_speed_forecast_day5": hourly.get("wind_speed_10m_previous_day5"),
            "shortwave_forecast_day5": hourly.get("shortwave_radiation_previous_day5"),
        },
        index=pd.to_datetime(hourly["time"], utc=True),
    )
    frame.to_csv(path)
    return frame


def _fill_from_nearest(arrays: dict[str, np.ndarray], points: pd.DataFrame) -> int:
    """Copy a missing hour from the nearest umbrella that has the day-5 forecast.

    All four weather values at that hour come from the same neighbor. The count
    is the number of umbrella-hours that were empty and then filled.
    """
    names = list(points["umbrella"])
    lat = points["umbrella_latitude"].to_numpy(dtype=float)
    lon = points["umbrella_longitude"].to_numpy(dtype=float)
    count = len(names)
    distance = np.zeros((count, count))
    for index in range(count):
        distance[index] = haversine_km(lat[index], lon[index], lat, lon)
        distance[index, index] = np.inf
    order = np.argsort(distance, axis=1)
    present = np.ones((arrays[WEATHER_FEATURES[0]].shape[0], count), dtype=bool)
    for feature in WEATHER_FEATURES:
        present &= np.isfinite(arrays[feature])
    filled = 0
    for index in range(count):
        missing = ~present[:, index]
        for donor in order[index]:
            if not missing.any():
                break
            if not np.isfinite(distance[index, donor]):
                continue
            take = missing & present[:, donor]
            if not take.any():
                continue
            for feature in WEATHER_FEATURES:
                arrays[feature][take, index] = arrays[feature][take, donor]
            filled += int(take.sum())
            missing[take] = False
    return filled


def _regional_weather(points: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Day-5 forecast for each umbrella. A hole is filled from the nearest umbrella."""
    fetched: dict[str, pd.DataFrame] = {}

    def fetch(row):
        return row.umbrella, _weather_one(float(row.umbrella_latitude), float(row.umbrella_longitude))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, row) for row in points.itertuples(index=False)]
        for future in as_completed(futures):
            name, frame = future.result()
            fetched[name] = frame
            print(f"weather {name}: {int(frame[WEATHER_FEATURES[0]].notna().sum())} hours")
    if not fetched:
        raise RuntimeError("no regional weather forecast")
    start = min(frame.index.min() for frame in fetched.values())
    end = max(frame.index.max() for frame in fetched.values())
    index = pd.date_range(start, end, freq="h", tz="UTC")
    names = list(points["umbrella"])
    arrays = {feature: np.full((len(index), len(names)), np.nan) for feature in WEATHER_FEATURES}
    for column, name in enumerate(names):
        frame = fetched[name].reindex(index)
        for feature in WEATHER_FEATURES:
            arrays[feature][:, column] = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=float)
    filled = _fill_from_nearest(arrays, points)
    blocks = []
    for column, name in enumerate(names):
        block = pd.DataFrame({feature: arrays[feature][:, column] for feature in WEATHER_FEATURES}, index=index)
        block["umbrella"] = name
        blocks.append(block)
    combined = pd.concat(blocks)
    combined.index.name = "timestamp"
    print(f"weather hours filled from a neighbor umbrella: {filled}")
    return combined.reset_index(), filled


def _load_forecast() -> pd.DataFrame | None:
    """CAISO seven-day-ahead system load. Omitted entirely when the pull is empty."""
    frames = []
    for start, end in _spans():
        frame = _oasis_csv(
            [
                ("queryname", "SLD_FCST"),
                ("startdatetime", _stamp(start)),
                ("enddatetime", _stamp(end)),
                ("market_run_id", "7DA"),
                ("version", "1"),
                ("resultformat", "6"),
            ],
            f"load_7da_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv",
        )
        if not frame.empty:
            frames.append(frame)
    if not frames:
        print("7-day-ahead load forecast returned no rows; the column is omitted")
        return None
    raw = pd.concat(frames, ignore_index=True)
    total = raw[raw["TAC_AREA_NAME"].astype(str).eq("CA ISO-TAC")].copy()
    if total.empty:
        print("7-day-ahead load forecast had no CA ISO-TAC rows; the column is omitted")
        return None
    total["timestamp"] = pd.to_datetime(total["INTERVALSTARTTIME_GMT"], utc=True).dt.floor("h")
    total[LOAD_FEATURE] = pd.to_numeric(total["MW"], errors="coerce")
    series = total.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    return series.loc[:, [LOAD_FEATURE]]


def _calendar(index: pd.DatetimeIndex) -> pd.DataFrame:
    local = index.tz_convert(LOCAL_TZ)
    hour = local.hour.to_numpy()
    weekday = local.dayofweek.to_numpy()
    day_of_year = local.dayofyear.to_numpy()
    holidays = us_holidays(range(int(local.year.min()), int(local.year.max()) + 1))
    return pd.DataFrame(
        {
            "hour_sin": np.sin(2 * np.pi * hour / 24),
            "hour_cos": np.cos(2 * np.pi * hour / 24),
            "dow_sin": np.sin(2 * np.pi * weekday / 7),
            "dow_cos": np.cos(2 * np.pi * weekday / 7),
            "doy_sin": np.sin(2 * np.pi * day_of_year / 365.25),
            "doy_cos": np.cos(2 * np.pi * day_of_year / 365.25),
            "is_holiday": np.isin(local.date, list(holidays)).astype(float),
        },
        index=index,
    )


def _drop_correlated(frame: pd.DataFrame, features: list[str]) -> tuple[list[str], dict[str, str]]:
    """Drop a feature that moves with another at 0.95 or more, using training hours only."""
    cutoff = frame.index.max() - pd.Timedelta(days=TEST_DAYS)
    train = frame.loc[frame.index <= cutoff]
    kept = list(features)
    dropped: dict[str, str] = {}
    changed = True
    while changed and len(kept) > 1:
        changed = False
        block = train.loc[:, kept].apply(pd.to_numeric, errors="coerce")
        corr = block.corr().abs()
        with_target = block.corrwith(train[TARGET]).abs()
        for left_index, left in enumerate(kept):
            for right in kept[left_index + 1 :]:
                value = corr.loc[left, right]
                if pd.isna(value) or value < 0.95:
                    continue
                loser = left if with_target.get(left, 0.0) <= with_target.get(right, 0.0) else right
                kept.remove(loser)
                dropped[loser] = f"|r|={value:.3f} with another feature; kept the one closer to price"
                changed = True
                break
            if changed:
                break
    return kept, dropped


def _assemble(campuses, candidates, prices, weather, load, assignment, filled_hours: int) -> tuple[pd.DataFrame, dict]:
    """One row per campus, per candidate node, per hour, then the leakage gate."""
    include_load = load is not None
    proposed = feature_columns(include_load)
    banned = illegal_feature_names(proposed)
    if banned:
        raise RuntimeError(f"refusing to write; features include the price or a short lag: {banned}")
    nodes = candidates.rename(columns={"latitude": "node_latitude", "longitude": "node_longitude"})
    nodes["node_type_load"] = nodes["node_type"].str.contains("load", case=False).astype(float)
    nodes = nodes.merge(assignment, on="pnode_id", how="left")
    table = nodes.merge(prices, on="pnode_id", how="inner")
    table = table.merge(weather, on=["umbrella", "timestamp"], how="left")
    if include_load:
        table = table.merge(load.reset_index(), on="timestamp", how="left")
    table = table.set_index("timestamp").sort_index()
    # One calendar row per hour. Joining the duplicated index to itself would multiply rows.
    unique_hours = pd.DatetimeIndex(pd.Index(table.index).unique()).sort_values()
    table = table.join(_calendar(unique_hours))
    required = [TARGET, *proposed]
    required = [column for column in required if column != LOAD_FEATURE]
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise RuntimeError(f"assembled table is missing columns: {missing}")
    before = len(table)
    table = table.dropna(subset=required)
    print(f"rows with a price, a full lag, and a day-5 forecast: {len(table)} of {before}")
    if table.empty:
        raise RuntimeError("every row was dropped; a lag or the day-5 forecast is missing")
    features, dropped = _drop_correlated(table, proposed)
    banned = illegal_feature_names(features)
    if banned:
        raise RuntimeError(f"refusing to write after the correlation pass: {banned}")
    # The same-hour-last-week column is the baseline even when correlation drops it as a feature.
    baseline = [LMP_LAG_168] if LMP_LAG_168 not in features else []
    keep = ["campus_id", "pnode_id", "node_type", TARGET, *baseline, *features]
    table = table.loc[:, [column for column in keep if column in table.columns]]
    table.index.name = "timestamp"
    meta = {
        "target": TARGET,
        "target_unit": "USD/MWh",
        "horizon_hours": 120,
        "features": features,
        "banned_substrings": ["cong", "loss", "energy", "mcc", "mce", "mcl"],
        "minimum_price_lag_hours": 120,
        "dropped": dropped,
        "calendar": list(CALENDAR_FEATURES),
        "static": list(STATIC_FEATURES),
        "weather": list(WEATHER_FEATURES),
        "weather_umbrellas": int(assignment["umbrella"].nunique()) if not assignment.empty else 0,
        "san_mateo_umbrella": "san-mateo" in set(assignment["umbrella"]) if not assignment.empty else False,
        "weather_hours_filled_from_neighbor": int(filled_hours),
        "load_forecast": LOAD_FEATURE if include_load else None,
        "campuses": int(table["campus_id"].nunique()),
        "distinct_nodes": int(table["pnode_id"].nunique()),
        "rows": int(len(table)),
        "start": str(table.index.min()),
        "end": str(table.index.max()),
        "history_start": HISTORY_START,
        "history_end": HISTORY_END,
        "content_hash": content_hash(table),
        "geocode": (
            "Open-Meteo search is tried first. It does not resolve street addresses, "
            "so a miss falls through to the US Census one-line geocoder."
        ),
    }
    return table, meta


def main() -> None:
    """Download campuses, nodes, prices, and weather, then write the modeling table."""
    listings = _listings()
    listings.to_csv(folder() / "sites_raw.csv", index=False)
    campuses, missed = _geocode(_campuses(listings))
    campuses.to_csv(folder() / "sites.csv", index=False)
    print(f"campuses: {len(campuses)}; no geocode: {len(missed)}")
    nodes = _active_nodes()
    print(f"located active nodes: {len(nodes)}")
    candidates = _candidates(campuses, nodes)
    candidates.to_csv(folder() / "candidates.csv", index=False)
    distinct = sorted(candidates["pnode_id"].unique())
    print(f"distinct candidate nodes: {len(distinct)}")
    assignment = assign_umbrellas(candidates)
    assignment.to_csv(folder() / "weather_umbrellas.csv", index=False)
    print(f"weather umbrellas: {assignment['umbrella'].nunique()}")
    prices = _prices(distinct)
    weather, filled_hours = _regional_weather(forecast_points(candidates))
    load = _load_forecast()
    table, meta = _assemble(campuses, candidates, prices, weather, load, assignment, filled_hours)
    meta["ungeocoded_campuses"] = missed
    dataset_path().parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(dataset_path())
    meta_path().write_text(json.dumps(meta, indent=2))
    digest = hashlib.sha256(dataset_path().read_bytes()).hexdigest()[:12]
    print(f"wrote {dataset_path()}")
    print(f"rows: {meta['rows']}, features: {len(meta['features'])}, {meta['start']} to {meta['end']}")
    print(f"file sha256: {digest}")


if __name__ == "__main__":
    main()
