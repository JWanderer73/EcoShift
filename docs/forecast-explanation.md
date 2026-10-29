# What the carbon forecasts are doing

This note explains the hourly CAISO forecasts, the scores used to read them, and where they fail. It is not the project design document.

The target is grams of CO₂ per kilowatt-hour for each hour on the California grid. The number is estimated from generation by fuel: natural gas at 393 kg CO₂/MWh, coal at 1003, petroleum at 814, and nuclear, hydro, wind, solar, and geothermal at 0. Fuel megawatthours are not given to the models, because the target is computed from them.

The forecasts are fixed. Ridge uses penalty 1. The tree uses one size and absolute error. Nothing in this pass was tuned. The holdout is the last 28 days, from 20 Sep 2026 23:00 UTC through 18 Oct 2026. Those weeks averaged 172 g/kWh. The earlier months averaged 103.

## Two jobs

A carbon report multiplies intensity by energy. It needs the level of the hour. If every hour is forecast 40 g/kWh too clean, the report is low by 40 grams per kWh no matter how nice the shape of the day looks.

A shift only needs the order of hours inside the day. It can place a job in the clean window even when the whole day is forecast too clean. Those two jobs fail in different places, so they do not share one definition of accuracy.

## What the scores mean

All of these are in gCO₂/kWh. A training loss is the penalty inside a fit. These scores are how a finished forecast is read. They are not the same thing.

**Bias** is prediction minus actual. Negative means the forecast said the grid was cleaner than it was, so a report built from it understates emissions.

**MAE** is the average size of the miss, sign ignored. A MAE of 25 means a typical hour is off by 25 grams per kWh. For a 10 kWh job reported from one hour, that is about 250 grams.

**RMSE** squares the misses before averaging, so a few hours that are off by 100 grams count more than many hours off by 10. Squared error, as a training loss, pushes a fit toward RMSE. Absolute error pushes it toward MAE.

**Level error** is the day's average forecast minus the day's average actual. **Shape MAE** is what remains after each series has its own mean removed. A flat 40 g/kWh miss has a large level error and a shape MAE of zero.

**Regret** is the shift score. For each complete local day, take the hours the forecast calls cleanest and compare their actual intensity with the hours that really were cleanest. A 4-hour regret of 2 means a job in the forecast's clean window emits 2 grams more per kWh than a job in the true clean window. A 10 kWh job is then about 20 grams over. Regret is zero when the order is right, even if the level is badly wrong.

**Rank correlation** is the Spearman correlation of the 24 hours in a day. It is 1 when the forecast has the day's order exactly right.

Pinball loss is the training penalty for a quantile model. A quantile above 0.5 charges more for guessing too clean than for guessing too dirty. Coverage is the share of hours whose actual intensity falls at or below the forecast. Those two belong to a later tuning pass. They are not what these five notebooks use to rank the fixed forecasts.

## What the holdout did

Scores below use the 27 complete Pacific days inside the holdout for regret, shape, and rank. Bias and MAE use every holdout hour.

| Forecast | Bias | MAE | 4-hour regret | Rank correlation |
| --- | ---: | ---: | ---: | ---: |
| Hour-of-day average | −70 | 71 | 1.9 | 0.84 |
| Yesterday, same hour | −2 | 27 | 2.2 | 0.84 |
| Day-ahead ridge | −6 | 25 | 2.0 | 0.86 |
| Day-ahead tree | −21 | 31 | 2.5 | 0.84 |
| Previous hour | −2 | 10 | 0.8 | 0.93 |

The day-ahead ridge sees the clock, carbon at this hour yesterday and last week, yesterday's weather, and CAISO's day-ahead demand forecast. The previous-hour forecast adds carbon from the hour that just finished, so it is only available if the decision can wait.

MAE and regret do not rank these forecasts the same way. The hour-of-day average looks unusable on MAE and is slightly better than the ridge at a 4-hour shift (regret 1.9 versus 2.0). The ridge does help if the job is a single hour (1-hour regret 3.2 versus 4.3). About 79% of the ridge's daily MAE is the day's average being wrong, not the hours being out of order. Mean level error is −6.5 g/kWh: a bit too clean. On 15 of 27 days the level miss is larger than the shape miss.

Across those days, MAE and RMSE move with the size of the level miss (correlation about 0.93). They barely move with 4-hour regret (about 0.3). Days that jumped at least 15 g/kWh from yesterday have MAE 32 instead of 17, and the same 2 g/kWh of regret either way. So MAE tells you the report got worse. It does not tell you the shift got worse.

## Where the day-ahead ridge is wrong

The miss is the level, on days that do not look like yesterday. The morning of 17 Oct 2026 is the worst case. At 09:00 local time the grid was 236 g/kWh, the forecast said 99, and yesterday at that hour was 115. The surrounding morning hours are the same kind of miss, about 75 to 140 g/kWh too clean.

Overnight and late evening are forecast too clean, by about 11 to 13 g/kWh. The solar window, 10:00–15:00, is forecast a little too dirty, by about 5 g/kWh. Local hour 6 has the largest MAE, 28 g/kWh. Weekends are worse than weekdays (MAE 29 versus 24).

The fixed tree fails in the same direction with a larger bias, −21 g/kWh. Waiting until the previous hour changes the failure: MAE falls to 10, regret to 0.8, and most of what remains is the shape of the day rather than its level.

## What to read later

For a report, read bias and MAE. Absolute error is the training loss that matches MAE. The thing being fixed is the day's level, especially a day that comes in much dirtier than yesterday.

For a 4-hour shift, read regret. The hour-of-day shape already gets that regret to about 2 g/kWh, and training on MAE will spend its effort on the level, which this decision ignores. For a single hour, read 1-hour regret. The ridge helps there.

The notebooks that produced these numbers are `01_where_forecasts_miss.ipynb`, `02_level_versus_shape.ipynb`, `03_shift_decision.ipynb`, `04_which_score_matches_the_job.ipynb`, and `05_days_that_break.ipynb`.
