"""Streamlit dashboard. Talks to the API only; run with: streamlit run dashboard/app.py"""

from __future__ import annotations

import os

import altair as alt
import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
DEFAULT_LOCATION = os.environ.get("DEFAULT_LOCATION", "demo-region")

WARNING_TEXT = {
    "pipeline_failed": "The last pipeline run failed. You are seeing the most recent successful forecast.",
    "forecast_stale": "This forecast is out of date. Treat the recommendation with caution.",
    "model_fallback": "The main model could not be loaded, so a baseline model is being used.",
    "data_quality_degraded": "A lot of the input data was filled in, so accuracy may be lower than usual.",
    "wait_clamped_to_horizon": "That wait is longer than the forecast covers, so it was shortened.",
}

st.set_page_config(page_title="Carbon windows", layout="wide")
st.title("Carbon windows")
st.caption("When is the grid cleanest? Pick a job length and how long you can wait.")


def api_get(path: str, **params):
    try:
        r = httpx.get(f"{API_URL}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=10)
    except httpx.TransportError:
        st.error(f"Cannot reach the API at {API_URL}.")
        st.stop()
    if r.status_code >= 400:
        st.error(f"API error {r.status_code}: {r.json().get('error', r.text)}")
        st.stop()
    return r.json()


with st.sidebar:
    st.header("Your job")
    location = st.text_input("Location", DEFAULT_LOCATION)
    duration = st.number_input("Job length (hours)", min_value=1, max_value=24, value=4)
    max_wait = st.selectbox("Longest you can wait", ["3h", "6h", "12h", "1d", "2d"], index=3)

forecast = api_get("/v1/forecast", location=location)
windows = api_get("/v1/windows", location=location, duration_hours=duration, max_wait=max_wait)

for code in sorted(set(forecast["warnings"]) | set(windows["warnings"])):
    st.warning(WARNING_TEXT.get(code, code))

best = windows["best"]
c1, c2, c3 = st.columns(3)
c1.metric("Recommendation", "Delay" if windows["recommendation"] == "delay" else "Run now")
c2.metric("CO2 saved vs now", f"{best['savings_pct']}%")
c3.metric("Wait", f"{best['wait_minutes'] / 60:g} h")

df = pd.DataFrame(forecast["rows"])
df["ts"] = pd.to_datetime(df["ts"])
band = alt.Chart(df).mark_area(opacity=0.2).encode(x="ts:T", y="p10:Q", y2="p90:Q")
line = alt.Chart(df).mark_line().encode(
    x=alt.X("ts:T", title="Time (UTC)"), y=alt.Y("intensity:Q", title="Carbon intensity", scale=alt.Scale(zero=False))
)
win = pd.DataFrame(
    [{"start": pd.to_datetime(w["start"]), "end": pd.to_datetime(w["end"])} for w in [best, *windows["alternatives"]]]
)
shade = alt.Chart(win).mark_rect(opacity=0.25, color="green").encode(x="start:T", x2="end:T")
now_rule = alt.Chart(pd.DataFrame({"t": [df["ts"].iloc[0]]})).mark_rule(strokeDash=[4, 4]).encode(x="t:T")
st.altair_chart((band + shade + line + now_rule).properties(height=360), width="stretch")

left, right = st.columns(2)
with left:
    st.subheader("Top windows")
    table = pd.DataFrame(
        [
            {
                "Start (UTC)": w["start"],
                "Wait (h)": w["wait_minutes"] / 60,
                "Avg": w["avg"],
                "Range": f"{w['avg_p10']}-{w['avg_p90']}",
                "Saves %": w["savings_pct"],
            }
            for w in [best, *windows["alternatives"]]
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")
with right:
    st.subheader("What does waiting buy?")
    st.bar_chart(pd.DataFrame(windows["savings_by_max_wait"]).set_index("max_wait_hours")["savings_pct"])

st.caption(f"Model {forecast['model_version']} · generated {forecast['generated_at']}")
