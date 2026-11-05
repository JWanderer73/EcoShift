"""Recommend a low-carbon window for one flexible job.

The model only knows yesterday's carbon and yesterday's weather, so the
window has to start and finish inside 24 hours. A longer wait is clamped.
The horizon is the latest 24 hours in the carbon dataset: those are the
latest hours whose features were already known a day earlier.

    python -m carbon_windows.recommend --duration 4 --max-wait 24 --kwh 10
"""

from __future__ import annotations

import argparse
import json

import joblib
import numpy as np
import pandas as pd

from carbon_windows.build_dataset import dataset_path
from carbon_windows.train_xgboost import predict_intensity
from src.build_demand_dataset import LOCAL_TZ

HORIZON_HOURS = 24
LOCATION = "CISO"


def _bundle():
    path = dataset_path().parent / "model.joblib"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. Train it with: python -m carbon_windows.train_xgboost")
    saved = joblib.load(path)
    frame = pd.read_csv(dataset_path(), index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return saved, frame.sort_index()


def recommend(duration: int, max_wait: int, kwh: float | None, location: str = LOCATION) -> dict:
    """Pick the lowest-intensity block that fits in the next 24 hours.

    Args:
        duration: How many hours the job needs.
        max_wait: Latest hour the job may finish, counted from the start of the horizon.
        kwh: Job energy. When given, emissions are reported in grams and kilograms.

    Returns:
        The chosen window, the intensity of starting immediately, and the percent saved.
    """
    if location != LOCATION:
        raise ValueError(f"this model is CAISO only; got location {location!r}")
    if duration < 1:
        raise ValueError("duration must be at least 1 hour")
    if max_wait < duration:
        raise ValueError("max-wait must be at least as long as the job")
    saved, frame = _bundle()
    horizon = frame.iloc[-HORIZON_HOURS:]
    predicted = predict_intensity(saved, horizon)
    wait = min(max_wait, HORIZON_HOURS)
    clamped = max_wait > HORIZON_HOURS
    if duration > wait:
        raise ValueError(f"a {duration}-hour job cannot finish inside the {wait}-hour horizon")

    starts = range(0, wait - duration + 1)
    means = [float(predicted[start : start + duration].mean()) for start in starts]
    best = int(np.argmin(means))
    chosen = means[best]
    now = means[0]
    saved_pct = 0.0 if now == 0 else 100.0 * (now - chosen) / now
    start_time = horizon.index[best]
    end_time = horizon.index[best + duration - 1] + pd.Timedelta(hours=1)
    result = {
        "location": LOCATION,
        "duration_hours": duration,
        "max_wait_hours": wait,
        "clamped_to_24h": clamped,
        "horizon_start": str(horizon.index[0]),
        "horizon_end": str(horizon.index[-1]),
        "window_start_utc": str(start_time),
        "window_end_utc": str(end_time),
        "window_start_pacific": str(start_time.tz_convert(LOCAL_TZ)),
        "window_end_pacific": str(end_time.tz_convert(LOCAL_TZ)),
        "window_g_per_kwh": chosen,
        "start_now_g_per_kwh": now,
        "percent_saved_vs_now": saved_pct,
    }
    if kwh is not None:
        result["job_kwh"] = kwh
        result["window_g"] = chosen * kwh
        result["window_kg"] = chosen * kwh / 1000.0
        result["start_now_g"] = now * kwh
        result["start_now_kg"] = now * kwh / 1000.0
    return result


def _print(result: dict) -> None:
    print(f"location: {result['location']}")
    print(f"horizon: {result['horizon_start']} to {result['horizon_end']} UTC")
    if result["clamped_to_24h"]:
        print("wait clamped to 24 hours, because yesterday's values are not known past that")
    print(f"window: {result['window_start_pacific']} to {result['window_end_pacific']} Pacific")
    print(f"        {result['window_start_utc']} to {result['window_end_utc']} UTC")
    print(f"window intensity: {result['window_g_per_kwh']:.1f} g/kWh")
    print(f"starting now:     {result['start_now_g_per_kwh']:.1f} g/kWh")
    print(f"percent saved vs starting now: {result['percent_saved_vs_now']:.1f}%")
    if "job_kwh" in result:
        print(f"job: {result['job_kwh']} kWh")
        print(f"window emissions: {result['window_g']:.0f} g ({result['window_kg']:.3f} kg)")
        print(f"starting now:     {result['start_now_g']:.0f} g ({result['start_now_kg']:.3f} kg)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recommend a low-carbon window for one job.")
    parser.add_argument("--duration", type=int, required=True, help="job length in hours")
    parser.add_argument("--max-wait", type=int, default=24, help="latest finish, in hours from the horizon start")
    parser.add_argument("--kwh", type=float, default=None, help="job energy, so emissions can be reported in g and kg")
    parser.add_argument("--location", default=LOCATION, help="balancing authority; only CISO is accepted")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()
    result = recommend(args.duration, args.max_wait, args.kwh, args.location)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print(result)


if __name__ == "__main__":
    main()
