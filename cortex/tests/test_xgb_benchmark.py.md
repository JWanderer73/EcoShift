tests/test_xgb_benchmark.py

# test_xgb_benchmark.py

test_xgb_benchmark.py exports _hourly_table, test_load_hours_keeps_demand_and_drops_fuel_and_carbon, test_split_is_the_first_sixty_percent, and test_short_xgb_fit_returns_finite_holdout_error.

<!-- cortex-file -->

## _hourly_table

periods goes in. Sets def _hourly_table(periods: int) -> pd.DataFrame: index to pd.date_range of 2026-01-01, periods=periods, freq=h, and tz=UTC.

<!-- cortex-logic -->

## test_load_hours_keeps_demand_and_drops_fuel_and_carbon

tmp_path goes in. Sets def test_load_hours_keeps_demand_and_drops_fuel_and_carbon(tmp_path) -> None: path to tmp_path / panel.csv. Calls _hourly_table with 24 * 40).to_csv(path. Sets loaded to load_hours of path.

<!-- cortex-logic -->

## test_split_is_the_first_sixty_percent

tmp_path goes in. Sets def test_split_is_the_first_sixty_percent(tmp_path) -> None: path to tmp_path / panel.csv. Calls _hourly_table with 24 * 80).to_csv(path. Sets train, test to train_test_hours of path.

<!-- cortex-logic -->

## test_short_xgb_fit_returns_finite_holdout_error

tmp_path goes in. Sets def test_short_xgb_fit_returns_finite_holdout_error(tmp_path) -> None: path to tmp_path / panel.csv.

<!-- cortex-logic -->

<!-- cortex-source-hash:5703739a8bac9b9e251ce7f48b2db75092f097c7e14ebcdb80325b835efce732 -->
