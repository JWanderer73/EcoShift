# Why the EcoShift forecasts are built this way

This note is for a reader who does not need to read the code. It explains the pipeline, the datasets, the five forecasts, the grid search, and the charts. It gives the reasons those pieces exist. It does not report how well anything scored.

EcoShift has two jobs that fail in different places.

A **carbon report** multiplies intensity by energy. If the forecast says the grid is cleaner than it was, the report understates emissions. For that job, the level of the day matters: how many grams of CO₂ per kilowatt-hour the forecast is high or low.

A **shift** only needs the order of hours inside a day. The practical question is which four hours to run a batch of work in. A forecast that is 40 grams too clean in every hour still picks the right window, as long as the shape of the day is right. A forecast with a perfect average and the noon dip in the wrong place writes a fine report and schedules the work badly.

The five forecasts, the scores, and the charts exist to keep those two jobs separate.

## The path from raw data to a chart

The work happens in four layers. Each layer has one job, so a later notebook is not quietly redefining the target or the inputs.

1. **Look at the slow data.** `notebooks/Data1.ipynb` loads monthly California electricity sales and daily San Diego weather from 2020 onward. This is the demand-and-price picture. It does not train the hourly forecasts.
2. **Look at the grid.** `notebooks/Data2.ipynb` loads CAISO generation, demand, interchange, weather at five California cities, weather forecasts, and the CAISO solar and wind forecasts. It builds the carbon-intensity estimate and checks which outside measurements actually move the grid. This notebook is the survey. The training code then keeps only the signals that survey said were real, and only the ones a forecast is allowed to see.
3. **Build the same table every time.** `src/carbon_data.py` downloads the hourly ingredients, computes carbon intensity, adds the clock and the lags, and saves a cache. `src/modeling.py` holds the time split, the five forecasts, the scores, and the grid search. Notebooks import that code instead of rebuilding it, so every notebook is looking at the same forecasts.
4. **Ask one question per notebook.** Notebooks `01` through `05` load the cache, make the same five forecasts with locked settings, and draw the chart or table that matches one question. They do not search for better settings. Searching is a separate step, described below, and it is not allowed to see the final test period.

The first run needs an EIA API key in `.env`. The key stays in that file and is not written into the notebooks. Open-Meteo does not need a key for this use. After the first successful pull, the hourly table is cached at `data/processed/hourly_model_panel.csv`. Later runs read the cache. The cache is derived data: it can be rebuilt, and a version number stops an old cache from being reused after the formula changes.

## Why each dataset is here

There are two collections, because the project has two timescales. Monthly sales explain who uses electricity and how the year moves. Hourly grid data is what a shift decision needs. Mixing them into one model would hide both.

### Data1 — monthly sales and one city’s weather

**EIA monthly retail sales, California, all sectors, 2020 through the latest published month.** This is electricity sold to customers: price, sales, revenue, and customer counts, for residential, commercial, industrial, transportation, other, and the all-sectors total. It is here because a carbon forecast is only useful if we know demand is real and seasonal. Sales show that residential and commercial use follow the calendar, and that industrial use moves more with activity. Price is here so we can see that it is a tariff series: it climbs over the years and should not be treated as a weather outcome. The all-sectors row is the statewide total, so it is kept for context and kept out of any comparison that already includes the pieces. The “other” sector is empty in this window, so it is dropped anywhere a correlation would be undefined. Transportation is a real sector and a very small share of sales, which is why the charts give it its own axis and why it is not the first modeling target.

**Open-Meteo daily weather for downtown San Diego, same years.** Temperature, rain, wind, solar radiation, and sunshine. This is the local weather that can be lined up with monthly sales. It is one coastal grid cell on purpose for this notebook: it is the simple companion to statewide sales, and it is enough to see whether heat and sun move residential use. The notebook is explicit that San Diego misses inland heat. That limit is why Data2 adds Fresno, Sacramento, Los Angeles, and San Francisco before any hourly model is trained.

These two frames are joined by month. Weather is daily and EIA is monthly, so weather is rolled up first: a monthly mean for temperature, a sum for rain and radiation, a max for wind. The join can only run through the months EIA has already released.

From that survey, a first monthly model of residential sales would use the calendar month plus cooling degree days, and would try sunshine only as a second step. The reasons:

- Residential sales are the natural first target. Home heating and cooling move them, and use per customer is almost the same series because the customer count barely moves compared with the seasonal swing.
- Cooling degree days use a base of 18°C (about 65°F). A day at 21°C contributes 3 degree-days; a day at 14°C contributes nothing to cooling and 4 to heating. That base is the usual comfort threshold, so the feature is “how far was today from comfortable,” not raw temperature.
- A count of days at or above 28°C is a poor heat feature for this city. The coast rarely gets that hot, so the count barely varies. Degree days still vary on ordinary warm days.
- Mean temperature is a substitute for cooling degree days, not a second column beside them. They describe the same heat.
- Sunshine hours and radiation are one sunlight signal recorded twice. A model keeps one.
- Heating degree days mostly restate winter. Once the calendar month is removed, they stop adding a separate story. Rain and wind are weak companions for residential sales at this one coastal point. Wind’s link to price is a shared trend over the years (price climbed, wind drifted), which is why a chart removes that trend before anyone treats it as weather.
- Stacking temperature, cooling degree days, heating degree days, radiation, and sunshine in one straight-line model splits one seasonal cycle across several columns. The month feature already carries the cycle. Extra weather columns have to earn a place by still lining up with sales after that month effect is removed.
- The holdout for any monthly model should be a later year. Neighboring months are the same season, so a random split would train on June and test on July.

Data1 does not become the hourly forecast. Generation by fuel is a different EIA feed. Retail sales also miss rooftop solar: that power never passes through the utility meter, so a dull month can raise purchased electricity without the sales table saying why.

### Data2 — the hourly grid, and the pieces that did not enter the model

**EIA hourly generation by fuel for CAISO (respondent `CISO`), 2026-01-01 through 2026-10-18.** This is the ingredient list for the carbon estimate: gas, coal, oil, solar, wind, hydro, nuclear, geothermal, other, and storage, in megawatt-hours. Daily fuel data back to 2020 is loaded in the survey so the seasonal mix is visible. The forecast itself is hourly, because the decision is which hours of a day to run.

**EIA hourly region data for the same window.** Four series matter: demand (`D`), the day-ahead demand forecast (`DF`), net generation, and total interchange. Demand is what the grid actually served. The day-ahead forecast is the demand number a scheduler can know before the day starts. Net generation and interchange are loaded so the survey can see imports and the balance of the system. They are not model inputs. Imports are not in the fuel mix, so putting interchange into the carbon formula would pretend we know the carbon content of someone else’s power.

**EIA daily interchange with each neighboring balancing authority, from 2024.** This is the “who did we trade with” table. It is context for the survey. The model does not use it, because a day-ahead carbon forecast would need the carbon intensity of each neighbor, which this feed does not provide.

**Open-Meteo weather at five cities: San Diego, Los Angeles, Fresno, Sacramento, and San Francisco.** Daily from 2020, hourly for 2026. The five cities are the coast plus the Central Valley plus the two big coastal loads. San Diego alone cannot stand in for statewide sun and heat. Temperature and 10-meter wind are averaged across the five cities because that average is the series that lined up with demand. Fresno’s sunlight is also kept as its own column, because it tracked CAISO solar generation more closely than the coastal cities. The survey also pulled cloud cover, precipitation, and 100-meter wind. Those stay in the survey. The modeling table keeps the three measurements that had a job: temperature for demand, sunlight for solar, and 10-meter wind for wind generation. One hundred-meter wind is closer to a turbine, and it was checked; the model uses the 10-meter series that was actually carried into the shared table.

**Open-Meteo forecast feeds.** The next seven days, Los Angeles forecasts issued over the recent past (including the run from the day before), and archived forecasts for Sacramento and Fresno in August–September 2026. These exist to ask a fairness question: if the model is supposed to be day-ahead, it should eventually see the weather forecast that was available the day before, not the weather that actually happened. They are not in the current five forecasts. The five forecasts use yesterday’s observed weather, which is known for certain a day ahead, so the comparison does not depend on a second forecast’s error.

**CAISO OASIS solar and wind forecasts** for the three California hubs (NP15, SP15, ZP26), day-ahead and actual. This is the grid operator’s own renewable forecast. The survey keeps it because it is the number a real day-ahead scheduler would have. The current five forecasts do not use it. The pull covers a short recent window, and the training table is built to be one consistent hourly panel for all of 2026. Leaving it out keeps every hour on the same inputs.

**The carbon estimate itself.** Until an Electricity Maps or WattTime token is available, intensity is computed from the public fuel mix. Electricity Maps would be a measured and forecast grams-per-kWh series for zone `US-CAL-CISO`. WattTime would be marginal emissions, which is the better target for “what happens if this workload runs now,” because average intensity and the intensity of the next megawatt are different questions. AWS job runtime and a customer carbon report come later. They are not grid feeds. A NOAA weather token is unnecessary because Open-Meteo already covers the weather fields.

### How a gram per kilowatt-hour is computed

For each hour, emissions are gas megawatt-hours times 393, plus coal times 1003, plus oil times 814. Those factors are EPA combustion factors (kilograms of CO₂ per million Btu) times a typical heat rate (million Btu per megawatt-hour). A kilogram per megawatt-hour is the same number as a gram per kilowatt-hour, so the ratio can be labeled gCO₂/kWh.

The denominator is gas, coal, oil, solar, wind, hydro, nuclear, and geothermal. Nuclear, hydro, wind, solar, and geothermal add power and add no combustion emissions. Other fuels and storage (batteries and pumped hydro) are left out of the ratio. Storage moves energy in time; counting it as generation would double-count power that was already generated. Negative reported generation is set to zero before the division, so a sign quirk cannot create negative fuel. Hours with nothing in the denominator are left blank.

This number is the carbon of CAISO’s counted generation. It is not Electricity Maps’ number, because imports are missing and the factors are typical heat rates rather than plant-level measurements. It is still the right public stand-in: on a solar-shaped grid it is high overnight, when gas is covering the load, and low in the middle of the day, when solar is covering it. That shape is why a four-hour shift is a real choice.

### What the model is forbidden to see

The fuel columns, the fuel shares, and the generation totals are the ingredients of the target. They are used to build `carbon_intensity_g_per_kwh`, then they are dropped. A model that saw today’s gas and today’s solar would be copying the formula, not forecasting the hour. The code raises an error if a feature list tries to include them. The same ban covers today’s observed temperature, sunlight, wind, and demand when the forecast is supposed to be day-ahead. Those columns stay in the table so a later “what if we could see the hour as it happens” model can use them. The five day-ahead forecasts do not.

## The modeling table, column by column

`model_frame` starts from the hourly panel, forces a complete UTC hourly index, and builds every column the forecasts share. A missing hour does not shorten a lag: “24 hours ago” is always 24 timestamps ago, because the index was filled in first. Rows that are still missing any modeling column are dropped. The first 168 hours are dropped because the week-long carbon lag does not exist yet.

| Column | What it is | Why it is here |
| --- | --- | --- |
| `carbon_intensity_g_per_kwh` | The target, grams of CO₂ per kWh | This is the thing being forecast. It is never an input. |
| `demand_mwh` | Actual CAISO demand | Known as the hour happens. Kept for the survey and for a same-hour model. Withheld from the day-ahead forecasts. |
| `demand_forecast_mwh` | EIA’s day-ahead demand forecast | Known before the day. Demand and carbon move together, and this is the demand number a day-ahead model is allowed to see. |
| `temp`, `radiation`, `wind_10m` | Five-city averages of temperature, sunlight, and 10 m wind | The weather that lines up with demand, solar, and wind. The day-ahead models see yesterday’s values, not today’s. |
| `radiation_fresno` | Sunlight at Fresno only | Kept separate because Valley sun tracks CAISO solar better than the coastal average. |
| `hour_local` | Hour 0–23 in America/Los_Angeles | The solar day and people’s clocks are Pacific. EIA’s hourly stamps are UTC, so the code converts. This is the single strongest simple pattern: carbon follows the hour. |
| `dow` | Monday = 0 through Sunday = 6, Pacific | Weekdays and weekends are different load shapes. |
| `hour_sin`, `hour_cos`, `dow_sin`, `dow_cos` | The same clock, written as a circle | Hour 23 and hour 0 are neighbors on a clock and far apart as the numbers 23 and 0. Sine and cosine put midnight next to 11pm. A straight line can use that. The five forecasts instead treat hour and weekday as categories, so each hour can have its own level without assuming a smooth wave. The circle columns are built so that alternative is available. |
| `doy_sin`, `doy_cos` | Day of year as a circle, using 365.25 days | Season moves smoothly. December is next to January. A single “day number” would not say that. |
| `carbon_lag_1` | Carbon intensity one hour ago | Only the “previous hour” forecast sees this. It is the bound on how much of the miss is simply having to decide early. |
| `carbon_lag_24` | Carbon at the same UTC hour yesterday | Known a day ahead. Carries yesterday’s level and yesterday’s shape. |
| `carbon_lag_168` | Carbon at the same hour last week | Known a day ahead. Carries the weekly pattern, so a Monday can look like last Monday rather than like Sunday. |
| `temp_lag_24`, `radiation_lag_24`, `radiation_fresno_lag_24`, `wind_10m_lag_24` | Yesterday’s weather, same hour | Known for certain a day ahead. Today’s weather would leak the future into a day-ahead forecast. |

## How the hours are split

The split is by time, always forward.

The **test block** is the last 28 days. It is scored once. Nothing in training, and nothing in a grid search, is allowed to look at it. Twenty-eight days is long enough to include weekdays and weekends, and short enough that most of 2026 remains for learning. A random split would train on Thursday and test on Wednesday of the same week. That pretends the forecast knew the future.

Inside the training block, a **14-day tail** is reserved for a later step: choosing how to blend several forecasts. The blend would be fit on the earlier hours, the weights would be chosen on those 14 days, and the specialists would then be refit on the whole training block before the test block is touched. The five forecasts below are not blended, so they do not use this cut. The cut exists so a later blend cannot be tuned on the exam.

**Grid search and cross-validation** use four forward folds inside the training block (`TimeSeriesSplit`). Each fold trains on earlier hours and scores the next later slice. Four folds means four such checks. The reason is the same as the holdout: neighboring hours share a weather system, so shuffling them leaks the answer.

Day-level scores keep only complete local days. The holdout starts and ends in the middle of a Pacific afternoon, so the first and last dates have fewer than 24 hours. A “cleanest four hours” decision is not the same decision on a partial day, so those dates are omitted from regret, shape, and the day scatters.

Every published prediction is clipped at zero. Carbon intensity cannot be negative, so a negative forecast is published as zero and scored as zero.

## The five forecasts

All five are built by `fixed_forecasts`. None of them is tuned. They share the training block and the test block. The two learned ones see only day-ahead columns. Locking the settings is deliberate: the notebooks are supposed to differ by the question they ask, not by a search that moved underneath them.

### 1. Hour-of-day mean

For each local hour, take the average carbon intensity of that hour in the training period, and predict that average later. If an hour were somehow missing from training, the forecast falls back to the average of all training hours.

This is the baseline. The survey said most of the carbon shape is the time of day, so a forecast that knows only the clock is the honest starting point. It uses no weather and no recent carbon. A fancier method has to beat this before it has earned its complexity. It also cannot represent a heat wave or a cloudy day, which is the point: those are the misses the other methods are allowed to fix.

### 2. Yesterday, same hour

Predict this hour with the actual intensity from the same hour yesterday. Nothing is fitted.

This is the persistence baseline. If the grid is in a stable pattern, yesterday is a strong guess, and it is legal in a day-ahead setting because yesterday has already happened. It carries yesterday’s level forward, so it is the method that should do well when today looks like yesterday and fail when the level jumps. It is the comparison that tells us whether a fitted model is learning anything beyond “copy yesterday.”

### 3. Day-ahead ridge

Ridge regression is a straight-line formula: one weight per input, plus an intercept. The penalty, called alpha, is fixed at 1. The penalty pulls weights toward zero when inputs repeat each other, so two columns that tell the same story cannot both grow huge weights. Alpha is fixed on purpose. Choosing it is a later pass. If each notebook picked its own penalty, a chart would no longer be comparing methods.

What it is allowed to see:

- Local hour and weekday, as categories. The code turns each category into a set of yes/no columns and drops one of them, because the intercept already represents the dropped case. Leaving all of them in would make the same clock twice.
- Season, as the day-of-year sine and cosine.
- Carbon at the same hour yesterday and last week.
- Yesterday’s temperature, five-city sunlight, Fresno sunlight, and 10-meter wind.
- The day-ahead demand forecast.

Before the line is fit, numeric columns are rescaled to a similar spread. The penalty treats every weight as if the columns were the same size. Demand is in megawatt-hours and a sine wave only runs from −1 to 1. Without scaling, the penalty would barely notice the demand weight and would crush the clock. Hour and weekday are not scaled; they are categories, not magnitudes.

Ridge’s internal fit cares about squared misses, plus the penalty. A miss of 10 grams costs more than twice a miss of 5 grams. That is a different choice from the tree, and it is why the notebooks report MAE, RMSE, and bias afterward instead of treating the training penalty as the result.

This is the forecast the later charts inspect. It is the day-ahead model a person can explain as “start from the clock, then adjust for yesterday, last week, yesterday’s weather, and the demand forecast.” The same weight applies all day. That is both the reason to include it and the reason the tree exists: a straight line cannot say “sunlight matters at noon and not at midnight” unless the inputs already encode that interaction.

### 4. Day-ahead tree

A histogram gradient boosting model is a sequence of small decision trees. Each tree asks yes/no questions and predicts a number. The next tree tries to correct the mistakes of the trees so far. “Histogram” means the numeric inputs are binned, which keeps the fit practical on thousands of hours.

It sees the same day-ahead columns as the ridge. Hour and weekday stay categories inside the tree, which is the natural form for a tree: each hour can be its own branch. They are not forced through the sine/cosine circle.

The tree is fit with absolute error. A miss of 10 grams costs twice a miss of 5 grams, not four times. That matches MAE, the “typical hour is off by this many grams” reading. The size of the tree is locked:

- Learning rate 0.08. Each new tree only moves the forecast a little, so the model cannot memorize the training hours in one step.
- Max depth 6. Each tree can ask a limited chain of questions. Deeper trees fit quirks of particular days.
- Minimum 40 hours in a leaf. A rule has to cover 40 hours before it is allowed to make its own prediction. A handful of odd hours cannot become a rule.
- 300 trees. Enough corrections to fit the daily shape, with the small learning rate keeping each one modest.
- L2 regularization 1.0. Leaf values are pulled back so one leaf cannot become extreme.
- Early stopping off. The model does not watch a side slice and decide to stop. That side slice would be a second, hidden choice of settings, and it would differ across notebooks.
- Random seed 0. The same trees come out on every run.

These were held fixed so that a later search can vary the tree’s structure, especially depth, without the notebooks silently differing in five other ways. The tree is here because the grid is not a straight line. The solar window, the evening ramp, and a hot afternoon interact. A tree can learn that yesterday’s sunlight matters in the middle of the day and barely matters at night. Ridge applies one weight everywhere.

### 5. Previous hour

A second ridge, with the same penalty of 1, the same hour and weekday categories, and the same day-ahead numbers, plus carbon from the hour that just finished.

This is not a fair day-ahead competitor. It answers a different question: if we could wait until the previous hour, how much of the miss goes away? The gap between this forecast and the day-ahead ones is the cost of having to decide a day early. A day-ahead model that loses to it can still be the right tool, because the previous hour is not known when the schedule is set. It is included so “we should just look at the recent grid” has a number attached, and so a day-ahead miss is not blamed on the model when the real limit is the clock.

It does not add today’s weather or today’s demand. Those would answer a third question, “what if we forecast the hour while it is happening.” That question has its own feature list in the code (`OBSERVED_NOW`) and is not one of the five.

## Grid search

Grid search is the procedure for choosing a setting. It is in `search_time_series`. The five forecasts above do not call it. Their settings are the locked ones in the previous section. The search is here so that when a setting is allowed to change, it changes under rules that keep the test block honest.

A grid is a list of candidates. For a tree, the intended candidates are structure choices such as depth. The other tree settings stay at the shared values, so the search changes one decision. The ridge penalty stays at 1 until a later pass. `cross_validated_mae` is the same forward check without a search: it reports how a locked model did on later slices of the training block.

For each candidate the code does the following.

1. Cut the training block into four forward folds. Each fold trains on earlier hours and scores the next block of later hours.
2. Fit the candidate on the earlier hours.
3. Predict the later hours, set any negative prediction to zero, and compute mean absolute error. MAE is the average number of grams per kilowatt-hour the forecast is off, with the sign ignored. It is the score that matches “a typical hour.” The clip is inside the score because a negative intensity would never be published, and the search should grade the forecast we would actually use.
4. Scikit-learn’s search tries to maximize a score. The code therefore hands it negative MAE. A smaller error is a larger (less negative) score. The number the search stores as its best score is that negative MAE. Closer to zero means a better candidate.
5. After the best candidate is chosen, refit it on every training hour. The folds exist to pick the setting. Once it is picked, no training hour is wasted. The last 28 days are still unseen.

The search runs candidates one at a time. The test block is not one of the folds. A setting that wins on the test block has memorized the exam, and that score can no longer be reported as an honest grade.

`fit_validation_split` is the related rule for blends. Weights that combine several forecasts are chosen on the 14-day tail inside training, then the pieces are refit on the full training block and applied once to the test block. The five forecasts are not blended, so this split is unused today. It is part of the pipeline so that step cannot drift onto the holdout later.

## How a forecast is read

Training penalties and reported scores are different objects. Squared error, absolute error, and pinball loss are penalties inside a fit. Bias, MAE, RMSE, shape, regret, and rank correlation are how we read a forecast afterward. The notebooks read them. They do not search settings.

**Bias** is prediction minus actual, in gCO₂/kWh. Negative means the forecast said the grid was cleaner than it was. A report that multiplies this forecast by energy understates emissions by that many grams per kilowatt-hour. Bias can look small when a morning miss and an evening miss cancel, which is why it is never the only number.

**MAE** is the average size of the miss, sign ignored. It is the right “typical hour” number for a report. It cannot tell a level miss from a shape miss, and it cannot tell a correct ranking from a wrong one.

**RMSE** squares the misses before averaging, then takes the square root. A few hours that are off by a lot count more than many hours that are off by a little. It is the reading to use when one badly timed hour is expensive. Ridge’s training penalty points this direction. The tree’s absolute-error penalty points toward MAE. Reporting both keeps that choice visible.

**Pinball loss**, at a chosen quantile, is the penalty a quantile model would train on. The middle quantile is half of MAE. A high quantile charges more for guessing too clean than for guessing too dirty. That is the direction a carbon report should fear when understating emissions is the costly mistake. None of the five forecasts is a quantile model. The loss is documented so a later model aimed at the report has a reason to use it, and so it is not confused with MAE.

**Level error** is the day’s average forecast minus the day’s average actual. A forecast that is 40 grams too clean in every hour has a level error of about −40 and a perfect shape.

**Shape MAE** subtracts each series’ own daily mean, then takes the MAE of what remains. It is the part of the error that is the order and the bumps of the day. A constant level miss has shape MAE zero.

**Regret**, for a 4-hour shift and for a 1-hour shift, is the actual intensity of the hours the forecast called cleanest, minus the actual intensity of the hours that really were cleanest. The unit is still gCO₂/kWh. Zero means the ranking of the window was right, even if every hour was far too clean. A wrong level that keeps the same order has regret zero. Four hours is the block because it is long enough to move a batch of work and short enough that “the clean part of the day” is a real choice on a solar-shaped grid. The one-hour version is the same idea for a single hour. Regret is computed inside each complete local day, then averaged across days.

**Rank correlation** is the Spearman correlation of the 24 hours: do the forecast and the actual day put the hours in the same order? It is 1 when the order matches. It is the all-day version of the shift question. Ties and flat days are left blank rather than forced into a correlation.

**Skill against the hour-of-day mean** is one minus the model’s MAE divided by the baseline’s MAE. It is the “did this beat the clock” reading. It is defined in the shared score row so a later table can use it. The current notebooks lead with the raw grams, because grams are what a report and a shift emit.

## Why the charts and tables look like this

Charts use a light grid, a notebook-sized figure, and shared axes when two panels must be compared in the same units. Blue (`#08519c` and `#3182bd`) is the actual grid or a neutral score. Orange (`#e6550d` and `#fd8d3c`) is the forecast or the miss. A horizontal line at zero is drawn wherever a signed miss can cancel. Partial days are already gone before a day-level chart is drawn.

The five forecast notebooks all start from the same printout: training end, holdout start and end, and the average carbon in each block. That printout is there so a reader can see that the test block is later than the training block before any score is trusted.

### Notebook 01 — where the forecasts miss

The table is bias, MAE, and RMSE for all five forecasts. Three columns because the three failures are different: a systematic lean, a typical miss, and a miss driven by a few bad hours.

The left bar chart is the average of actual minus day-ahead ridge, by local hour. Above zero, that hour was dirtier than the forecast. This is the chart that shows a lean that a single bias number would average away.

The right bar chart is MAE by local hour, on the same hours. An hour that is sometimes too high and sometimes too low still shows up here. The two panels share the hour axis so a tall MAE bar can be read against the signed bar beside it.

The line chart is the holdout’s daily mean of actual intensity against the daily mean of the ridge. It is there to see whether a miss is the whole period or a few days. Daily means are the right grain for that question; an hourly line over 28 days is too dense to see a level shift.

### Notebook 02 — level versus shape

The table, for each forecast, is the number of complete days, MAE, the average size of the level error, shape MAE, and the level’s share of MAE. The share says how much of a typical miss is “the whole day was high or low.”

The left scatter is one point per complete holdout day for the ridge: absolute level error against MAE. It asks whether a bad day is mostly a wrong level. If the points sit on a rising line, the day’s MAE is the level. If they sit flat, the day is bad for another reason.

The right scatter is shape MAE against 4-hour regret. It asks whether a bad shape is what makes the clean-window choice expensive. Regret is defined in the next notebook; this chart is the reason to define it.

### Notebook 03 — the shift decision

The table is 4-hour regret, 1-hour regret, rank correlation, and MAE, for all five forecasts. MAE is in the table so a reader can see a method win the report and lose the shift, or the reverse. The printout names the best method on regret and the best method on MAE separately, and translates 4-hour regret into extra grams for a 10 kWh job. That translation is why the unit stays gCO₂/kWh: energy times intensity is emissions.

The figure is two days of the ridge, the lowest-regret complete day and the highest. Each panel plots actual and forecast against local hour, with the regret in the title. A line with markers is used because the claim is about the order of the 24 hours, which a bar of averages would hide. The panels share the vertical axis so a calm day and a broken day are on the same gram scale.

### Notebook 04 — which score matches which job

The model table puts bias, MAE, RMSE, shape MAE, 4-hour regret, and rank correlation side by side. The day table is the same ideas, one row per forecast per complete day.

The alignment table correlates each score, across ridge days, with 4-hour regret and with the size of the level miss. There is no extra chart because the claim is “which number moves with which job,” and a correlation table is that claim. Rank miss (one minus rank correlation) is included because it is built from the order of hours, so it should be the score that tracks regret. MAE is included because it is the number people usually report, and the question is whether it is actually pointing at the shift. The level miss itself is left out of the “which score tracks the report” pick, because a score tracking itself is not a finding.

### Notebook 05 — the hours and days that break the ridge

This notebook stays on the day-ahead ridge and uses tables rather than new chart types. The blocks of the day are fixed cuts of the Pacific clock:

| Block | Local hours | Why it is its own row |
| --- | --- | --- |
| Night | 0–5 | Gas is on, solar is zero, the level is high and flat. |
| Morning ramp | 6–9 | Solar arrives and carbon falls. |
| Solar window | 10–15 | The clean hours a shift wants. |
| Evening ramp | 16–20 | Solar leaves and gas returns. This is the fastest change of the day. |
| Late evening | 21–23 | The return toward the overnight level. |

Each block reports MAE, the average “too clean” residual (actual minus predicted), and the number of hours. A positive residual is the miss that both places work in a dirty hour and understates a report.

Days are then split by whether the carbon level jumped from yesterday’s same-hour average by at least the median jump. Yesterday is the input the linear forecast leans on, so a jump is the failure mode of method 2 and a likely failure mode of the ridge. Weekday versus weekend is the same idea for the weekly clock. The last table is the hours with the largest absolute residual, with the clock time, the actual, the forecast, and yesterday’s value. Those rows are where a shift or a report would be most wrong, and yesterday’s value is shown because that is what the ridge was leaning on.

### Data1 charts — sales, weather, and whether weather is just the calendar

Small multiples give every sector its own panel and its own vertical scale. Transportation and the empty “other” sector would otherwise flatten residential, commercial, and industrial into a line at the bottom. Customer counts use a log scale for the same reason: the sectors differ by orders of magnitude. The indexed sales chart divides each sector by its own average so the seasonal shapes can share one axis. A value of 1 is an average month for that sector.

Boxplots by calendar month show the seasonal range of sales and of price, not just the average. The bar chart of month-of-year averages is the simpler companion: the typical seasonal profile. Heatmaps inside each sector show whether price, sales, revenue, customers, and use-per-customer are repeating one another. The residential pair plot is the same check as a scatter matrix, so a tight diagonal is visible before anyone puts two of those columns in one model. Price versus sales, colored by month, asks whether a price–sales link is really a seasonal cluster.

Weather is plotted as daily temperature (min, mean, max on one axis, because the spread inside a day matters) and as monthly temperature, cooling degree days, and heating degree days. Radiation, sunshine, rain, and wind each get a monthly panel because they are candidates, not because they are all expected to matter. Boxplots by month show the seasonal range. The weather correlation heatmap, the three colored scatters (temperature against radiation, radiation against sunshine, temperature against rain), the histograms, and the monthly pair plot are all the same test: which weather columns are one signal recorded twice. A model that keeps both has not gained a new measurement.

The joined heatmaps come in a pair of interpretations. The raw correlations of weather with sales, with use per customer, and with price count a shared seasonal cycle as a relationship. The adjusted heatmap subtracts each variable’s month-of-year average first. Color that remains is what a model can use on top of a month feature. Use per customer is plotted beside sales because it removes the slow growth in customer counts; for residential the two are nearly the same series, which is why either can be the target and both should not be.

Scatter plots with a fitted line, one weather feature at a time against residential sales, show the shape of each candidate rather than only a correlation. The small-multiple of sales against cooling degree days by sector asks whether heat is a residential story or a statewide one. Twin-axis seasonal profiles and twin-axis time series put sales and one weather series on the same months so a lag is visible: sun peaking before sales, for example. Calendar heatmaps (year by month) show whether a pattern repeats every year or is one unusual summer. The lag bars correlate this month’s sales with weather from the same month and up to six months earlier, which is how a seasonal offset is distinguished from a real delay. The residual scatter subtracts the usual month from both sales and cooling degree days before fitting a line, which is the picture behind the adjusted heatmap. The price-versus-wind pair is drawn twice, raw and after a straight time trend is removed, with the two time series underneath, because a correlation that disappears after detrending is a shared trend. The last pair plot is only the columns still worth comparing for a first model.

### Data2 charts — which outside measurements actually touch the grid

The stacked area chart is the monthly generation mix, so the carbon estimate has a visible cause: the share of gas versus solar, wind, hydro, and nuclear. The line under it is a 14-day average of the carbon estimate, so day-to-day noise does not hide the seasonal level. Fourteen days is long enough to smooth weekends and short enough to keep a season.

The daily correlation heatmap includes the fuel columns on purpose, and the title says the carbon estimate is computed from them. A strong link between gas and carbon, or between solar share and carbon, is the formula, not a discovery. The chart is there so that circular link is seen and then kept out of the model.

The scatter plots that are not circular are the ones the model is allowed to learn from: sunlight against solar generation, the hottest-city temperature against demand, and wind against wind generation. A fitted line is drawn so the relationship is visible as a slope, not only as a table. The horizontal bar chart ranks the five cities by how well each city’s radiation tracks CAISO solar. That chart is why Fresno’s sunlight is its own column and why a coastal city alone is not the sunlight feature.

The four-panel average day plots solar generation, demand, carbon intensity, and radiation against the local hour, with a shared hour axis. This is the picture behind the hour-of-day baseline and behind the four-hour shift: the clean hours are a block in the middle of the day, and carbon, solar, and demand are one daily shape seen four ways.

The last scatter is the CAISO day-ahead solar forecast against actual solar, daytime hours only. Nights are zero on both sides, so an all-hours picture would look stronger than the daytime decision. This chart is why that forecast is a candidate for a later day-ahead model, and why the current five forecasts can still be trained without it: the check is on a short recent window, while the modeling table has to cover every hour of 2026 with the same columns.

## What is deliberately not in this pass

The five forecasts are not tuned, not blended, and not given today’s weather, today’s demand, today’s fuel mix, or the CAISO renewable forecast. Quantile training, for a report that would rather guess too dirty than too clean, is described and not fitted. Electricity Maps and WattTime are the preferred targets when a token exists; the fuel-mix estimate stands in until then. Grid search is ready, and it runs only on earlier hours. The last 28 days stay the exam.
