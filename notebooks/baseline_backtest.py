"""Baseline backtest: forecast CAISO carbon intensity 24h ahead.

Pulls about 60 days of EIA-930 hourly generation by fuel (needs EIA_API_KEY in
.env) plus Open-Meteo weather, then compares two naive baselines with a
gradient-boosted model on a time-based split. If there is no key, it falls
back to synthetic grid data and labels the output that way.

Run: .venv/bin/python notebooks/baseline_backtest.py
"""

import os
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

REGION = "CISO"
LAT, LON = 36.8, -119.4  # central California
DAYS = 60
TEST_DAYS = 14
JOB_HOURS = 3  # job length used for the CO2-saved metric
ARCHIVE_LAG_DAYS = 7  # Open-Meteo archive trails real time by a few days
# Approximate eGRID-style emission factors, kg CO2 per MWh (= g/kWh).
EMISSION_FACTORS = {"COL": 1000, "NG": 400, "OIL": 800, "OTH": 400}
OUT = Path(__file__).resolve().parents[1] / "results"


def fetch_eia(key: str, start: date, end: date) -> pd.Series:
    """Hourly carbon intensity (gCO2/kWh) from EIA-930 generation by fuel."""
    url = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
    rows, offset = [], 0
    while True:
        params = {
            "api_key": key, "frequency": "hourly", "data[0]": "value",
            "facets[respondent][]": REGION, "start": f"{start}T00",
            "end": f"{end}T23", "offset": offset, "length": 5000,
        }
        page = requests.get(url, params=params, timeout=60).json()["response"]["data"]
        rows += page
        if len(page) < 5000:
            break
        offset += 5000
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["period"], utc=True)
    df["mwh"] = pd.to_numeric(df["value"], errors="coerce").clip(lower=0)  # drop impossible negatives
    df = df.drop_duplicates(["time", "fueltype"])
    df["co2"] = df["mwh"] * df["fueltype"].map(EMISSION_FACTORS).fillna(0)
    hourly = df.groupby("time")[["co2", "mwh"]].sum()
    return (hourly["co2"] / hourly["mwh"]).rename("intensity")


def fetch_weather(start: date, end: date) -> pd.DataFrame:
    """Hourly weather from the Open-Meteo archive."""
    params = {
        "latitude": LAT, "longitude": LON, "start_date": start, "end_date": end,
        "hourly": "temperature_2m,wind_speed_10m,shortwave_radiation", "timezone": "UTC",
    }
    hourly = requests.get("https://archive-api.open-meteo.com/v1/archive",
                          params=params, timeout=60).json()["hourly"]
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time")


def synthetic_intensity(weather: pd.DataFrame) -> pd.Series:
    """Fallback grid data: intensity falls with sun and wind, plus noise."""
    rng = np.random.default_rng(0)
    w = weather
    return (300 - 0.15 * w["shortwave_radiation"] - 2 * w["wind_speed_10m"]
            + rng.normal(0, 10, len(w))).rename("intensity")


def best_window_savings(pred: pd.Series, actual: pd.Series) -> float:
    """Mean % CO2 saved by picking the predicted-best window in the next 24h."""
    p = pred.rolling(JOB_HOURS).mean().shift(-(JOB_HOURS - 1))
    a = actual.rolling(JOB_HOURS).mean().shift(-(JOB_HOURS - 1))
    saved = []
    for i in range(len(p) - 24):
        best = p.iloc[i:i + 24 - JOB_HOURS].idxmin()
        saved.append(1 - a[best] / a.iloc[i])
    return 100 * float(np.nanmean(saved))


def main() -> None:
    load_dotenv()
    end = date.today() - timedelta(days=ARCHIVE_LAG_DAYS)
    start = end - timedelta(days=DAYS)
    weather = fetch_weather(start, end)
    key = os.getenv("EIA_API_KEY")
    source = "EIA-930" if key else "SYNTHETIC (no EIA_API_KEY)"
    intensity = fetch_eia(key, start, end) if key else synthetic_intensity(weather)

    df = weather.join(intensity, how="inner").dropna()
    df = df[df["intensity"].between(0, 1500)]  # filter impossible values
    df["hour"], df["dow"] = df.index.hour, df.index.day_of_week
    df["lag_24"] = df["intensity"].shift(24)  # earliest value known 24h ahead
    df["lag_168"] = df["intensity"].shift(168)
    df = df.dropna()

    split = df.index.max() - pd.Timedelta(days=TEST_DAYS)
    train, test = df[df.index <= split], df[df.index > split]  # never a random split
    features = ["hour", "dow", "temperature_2m", "wind_speed_10m",
                "shortwave_radiation", "lag_24", "lag_168"]
    model = HistGradientBoostingRegressor(random_state=0).fit(train[features], train["intensity"])
    preds = {
        "Same hour yesterday": test["lag_24"],
        "Same hour last week": test["lag_168"],
        "Gradient boosting": pd.Series(model.predict(test[features]), index=test.index),
    }

    rows = [{"model": name, "MAE (gCO2/kWh)": round(mean_absolute_error(test["intensity"], p), 1),
             f"CO2 saved, {JOB_HOURS}h job (%)": round(best_window_savings(p, test["intensity"]), 1)}
            for name, p in preds.items()]
    table = pd.DataFrame(rows)
    print(f"Region {REGION} | data: {source} | train {train.index.min():%b %d}–{split:%b %d}, "
          f"test {TEST_DAYS} days")
    print("Note: weather uses observed values, not forecasts (optimistic).")
    print(table.to_string(index=False))

    OUT.mkdir(exist_ok=True)
    table.to_csv(OUT / "baseline_backtest.csv", index=False)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(test.index, test["intensity"], label="Actual", color="black")
    ax.plot(test.index, preds["Gradient boosting"], label="Gradient boosting", alpha=0.8)
    ax.plot(test.index, test["lag_24"], label="Same hour yesterday", alpha=0.5, ls="--")
    ax.set(title=f"{REGION} carbon intensity, 24h-ahead forecast ({source})", ylabel="gCO2/kWh")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "baseline_backtest.png", dpi=150)
    print(f"Saved {OUT / 'baseline_backtest.png'}")


if __name__ == "__main__":
    main()
