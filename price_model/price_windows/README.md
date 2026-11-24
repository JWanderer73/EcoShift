# Price windows

This folder forecasts the CAISO day-ahead price at the five P-nodes nearest each Inflect California datacenter campus, and picks a block of hours for one batch job.

The number being predicted is **dollars per megawatt-hour** (`lmp_usd_per_mwh`). The command prints that same price in **dollars per kilowatt-hour** (divide by 1000). A job's energy cost is the price per kWh times its energy in kWh. An 8 kW cabinet, the size in the Inflect quote, running for 4 hours at 40 $/MWh (0.04 $/kWh) costs $1.28. Prices may be negative, so predictions are not clipped at zero.

The sites are the campuses on Inflect's public California datacenter pages. Each campus keeps the five closest P-nodes that have published coordinates. The job search is the **next 3 days**. Price features stay legal out to five days: every price lag is at least 120 hours. Congestion, loss, and the energy component are not features, because they are the price split into parts. Weather is only an input: the forecast that existed five days before the hour, shared by P-nodes in the same region. San Mateo is one of those regional forecast points.

## Commands

From the repo root, with `.venv` active:

```bash
python -m price_windows.build_dataset
python -m price_windows.train_xgboost
python -m price_windows.recommend --site "Santa Clara" --duration 4 --days 3 --kw 8
python -m price_windows.daily
```

The price history is one year of CAISO day-ahead LMP, 2025-11-15 through 2026-11-14. The scored hours are the next `--days` times 24 hours after the last hour in that table whose 120-hour price lag exists. `--days` above 3 is clamped, and the output says so. `--range-start` and `--range-end` are Pacific times inside that search; a time outside it is clamped. `--kw` defaults to 8. `--start-hour` and `--end-hour` are inclusive Pacific clock hours; a block that would run outside that daily range is skipped. If `--site` matches more than one campus, the command lists them and stops.

`train_xgboost` accepts `--trials` (default 40) and `--minutes`. When `--minutes` is set, the search stops on the clock and keeps the trials that finished. A full 40-trial search is manual and rare. `python -m price_windows.train_xgboost --update-model` continues the saved booster on only the rows after `metrics.json` `train_end`. It does not run Optuna. The morning job does not pass that flag.

## Morning job

`python -m price_windows.daily` scores the next five days for every campus. `--days` above 5 is clamped. The cabinet default stays 8 kW, and the block is 4 hours. It reads `model.joblib` and the LMP cache. It does not call `train_xgboost`, and it does not download the history year again.

For each distinct node in `candidates.csv` it requests only the day-ahead hours after that node's newest cached hour, one node per OASIS call, five seconds apart, and it retries HTTP 429. A node that is already current is skipped. A node with no cache is skipped too, so a missing file does not turn into a year-long download. It then refreshes the day-5 Open-Meteo forecast and the 7DA load forecast for that five-day window. Lags, including the 120-hour price lag, are taken from the cache. The saved trees are not refit.

The report is `price_windows/reports/<Pacific date>.txt`. That folder is gitignored. If `model.joblib` is missing, the command says so and exits 1. It does not train. If the network still fails after the retries, it scores the cache it already has and exits 0. A second copy exits 0 while the first is running.

Install the macOS LaunchAgent (no sudo). It runs at 07:15 in the Mac's local time. This machine is set to America/Los_Angeles, which is after CAISO has posted the previous day's day-ahead prices (the post is about 13:00 Pacific the afternoon before):

```bash
sh price_windows/install_daily_job.sh
```

The job appends to `price_windows/cache/daily.log`. The same schedule as a crontab line, if you prefer that:

```
15 7 * * * cd /Users/kareha/Desktop/EcoShift && .venv/bin/python -m price_windows.daily >> price_windows/cache/daily.log 2>&1
```

## What was considered and not added to the frozen model

CAISO day-ahead prices move with fuel cost, load, and the weather that drives both. The saved model already uses the clock, price lags of 120, 144, 168, and 336 hours, the same-hour week mean, the day-5 weather forecast, and the 7DA load forecast. Fresh copies of those inputs are what the morning job updates.

Henry Hub daily spot is a free EIA series, `NG.RNGWHHD.D` in the bulk file `https://www.eia.gov/opendata/bulk/NG.zip` (no API key). A 2026 CAISO study found a strong correlation between fuel price and day-ahead LMP, about 0.74, using fuel prices known for that day ([arXiv:2605.27781](https://arxiv.org/html/2605.27781v1)). Same-day fuel is not legal here. The column `henry_hub_lag_120` keeps only a print dated at least 120 hours before the target hour. The morning job caches it when the download works. The saved `model.joblib` was fit without that column, so the score does not use it, and a missing value does not stop the report. Putting the column into the 8-million-row table would be a full rebuild, which this job does not do.

Left out, and why:

- Day-ahead solar and the other day-ahead renewable forecast (`SLD_REN_FCST`, market `DAM`) are for the next day, not five days ahead.
- Actual load, and the day-ahead or two-day load forecast, are newer than five days. The 7DA forecast is already a feature.
- Today's actual weather is not the forecast that existed five days earlier.
- Congestion, loss, the energy component, and the same-hour price are the price, at any lag.
- PG&E and SoCal citygate daily prices are not a free cacheable daily file. EIA citygate prices are monthly. The daily citygate series in the PG&E forecast study was supplied by the utility.
- Scheduled outages: OASIS `AGGR_OUTAGE_SCH` is published about 05:00 Pacific the day before the operating day (CAISO OASIS interface specification, aggregated generation outages). That is one day ahead, not five. `TRNS_OUTAGE` updates with each event. A five-day-old vintage would be another OASIS crawl, so it is not on the morning path.
- A longer price lag such as 720 hours is legal (the gate is 120, and the table already has 120, 144, 168, 336, and the week mean). The saved model has no split on a new lag. Adding one waits on a rebuild. The morning job refreshes the lags the model already uses.

## What gets written

| File | Kept in git |
| --- | --- |
| `price_dataset.csv` | no |
| `model.joblib` | no |
| `cache/` | no |
| `reports/` | no |
| `sites.csv` | yes |
| `candidates.csv` | yes |
| `price_dataset.meta.json` | yes |
| `metrics.json` | yes |
