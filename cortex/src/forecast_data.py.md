src/forecast_data.py

# forecast_data.py

forecast_data.py exports cleaned_csv_path, data_path, load_hours, modeling_table, train_test_hours, and features.

<!-- cortex-file -->

## cleaned_csv_path

No parameters go in. Gives repo_root() / data / processed / cleaned_weather_carbon.csv back.

<!-- cortex-logic -->

## data_path

No parameters go in. Sets path to the result of cleaned_csv_path. Gives path back.

<!-- cortex-logic -->

## load_hours

path goes in. Sets path to data_path() if path is None else path.

<!-- cortex-logic -->

## modeling_table

path goes in. Sets hours to load_hours of path.

<!-- cortex-logic -->

## train_test_hours

path goes in. Sets table to modeling_table of path.

<!-- cortex-logic -->

## features

frame goes in. If the model is being shown the electricity use it is supposed to predict, it gives frame.loc[:, FEATURE_COLUMNS].astype(float back.

<!-- cortex-logic -->

## print_split

train and test go in. Sets total to len of train) + len(test.

<!-- cortex-logic -->

## _plain

value goes in. Calls str with key): _plain(item) for key and item in value.items(.

<!-- cortex-logic -->

## search_and_score

name, estimator, param_grid, train, and test go in. Sets x_train to features of train.

<!-- cortex-logic -->

## print_score

result goes in. Sets unit to result.get of unit and TARGET_UNIT.

<!-- cortex-logic -->

<!-- cortex-source-hash:340f55cf0f6a0cce93bd5eb4e28b73734997f73c5feca059c5d0ddc57381eb9b -->
