# Carbon windows

This folder forecasts CAISO grid carbon intensity and picks a block of hours for one flexible job.

The number being predicted is **grams of CO₂ per kilowatt-hour** (`carbon_intensity_g_per_kwh`). A job's emissions are that intensity times the job's energy in kWh, which is grams of CO₂. Divide by 1000 for kilograms. Percent saved compares the chosen window with starting at the first legal hour.

The model does not predict demand, and it does not predict kilograms directly. It is trained on CAISO (`CISO`) only. Passing any other location is rejected.

The honest horizon is **24 hours**. Open-Meteo weather and yesterday's fuel mix are lagged one day. CAISO's day-ahead solar and wind forecasts are for the target hour and are published the afternoon before, so they are legal inside that horizon. A longer `--max-wait` is clamped to 24 hours, and the result says so.

## Commands

From the repo root, with `.venv` active and `EIA_API_KEY` in `.env`. The weather file must already exist (`python -m src.build_demand_history`).

```bash
python -m carbon_windows.build_dataset
python -m carbon_windows.train_xgboost
python -m carbon_windows.recommend --duration 4 --max-wait 24 --kwh 10
```

`train_xgboost` accepts `--trials` (default 40) and `--minutes`. When `--minutes` is set, the search stops on the clock and keeps the trials that finished.

## What gets written

| File | Kept in git |
| --- | --- |
| `carbon_dataset.csv` | no |
| `model.joblib` | no |
| `carbon_dataset.meta.json` | yes |
| `metrics.json` | yes |

The EPA factors used as multipliers are gas 393, coal 1003, and oil 814 kg CO₂ per MWh, which is the same figure as g CO₂ per kWh. Nuclear, hydro, wind, solar, and geothermal are 0. The hourly shape comes from the EIA-930 fuel mix. The fuel megawatt-hours are not columns in the modeling table.
