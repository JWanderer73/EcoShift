# Price windows

This folder forecasts the CAISO day-ahead price at the five P-nodes nearest each Inflect California datacenter campus, and picks a block of hours for one batch job.

The number being predicted is **dollars per megawatt-hour** (`lmp_usd_per_mwh`). A job's energy cost is that price times its energy in kWh, divided by 1000. An 8 kW cabinet, the size in the Inflect quote, running for 4 hours at 40 $/MWh costs $1.28. Prices may be negative, so predictions are not clipped at zero.

The sites are the campuses on Inflect's public California datacenter pages. Each campus keeps the five closest P-nodes that have published coordinates. The horizon is **five days**. Every price lag is at least 120 hours. Congestion, loss, and the energy component are not features, because they are the price split into parts. Weather is the forecast that existed five days before the hour.

## Commands

From the repo root, with `.venv` active:

```bash
python -m price_windows.build_dataset
python -m price_windows.train_xgboost
python -m price_windows.recommend --site "Santa Clara" --duration 4 --days 5 --kw 8
```

The price history is one year of CAISO day-ahead LMP, 2025-11-15 through 2026-11-14. The scored hours are the next `--days` times 24 hours after the last hour in that table whose 120-hour price lag exists. `--days` above 5 is clamped, and the output says so. `--kw` defaults to 8. `--start-hour` and `--end-hour` are inclusive Pacific clock hours; a block that would run outside that daily range is skipped. If `--site` matches more than one campus, the command lists them and stops.

`train_xgboost` accepts `--trials` (default 40) and `--minutes`. When `--minutes` is set, the search stops on the clock and keeps the trials that finished.

## What gets written

| File | Kept in git |
| --- | --- |
| `price_dataset.csv` | no |
| `model.joblib` | no |
| `cache/` | no |
| `sites.csv` | yes |
| `candidates.csv` | yes |
| `price_dataset.meta.json` | yes |
| `metrics.json` | yes |
