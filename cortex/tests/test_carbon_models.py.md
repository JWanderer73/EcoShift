tests/test_carbon_models.py

# test_carbon_models.py

test_carbon_models.py exports test_carbon_intensity_half_gas_half_solar, test_carbon_intensity_clips_negative_generation, test_feature_lists_exclude_the_fuel_mix, test_model_frame_lag_is_twenty_four_hours, test_train_test_split_is_ordered_and_disjoint, and test_shift_regret_is...

<!-- cortex-file -->

## test_carbon_intensity_half_gas_half_solar

No parameters go in. Sets def test_carbon_intensity_half_gas_half_solar() -> None: fuels to pd.DataFrame of an object with NG a list of 50.0 and SUN a list of 50.0. Sets intensity to carbon_intensity of fuels.

<!-- cortex-logic -->

## test_carbon_intensity_clips_negative_generation

No parameters go in. Sets def test_carbon_intensity_clips_negative_generation() -> None: fuels to pd.DataFrame of an object with NG a list of 10.0, SUN a list of -4.0, and WND a list of 0.0. Sets intensity to carbon_intensity of fuels.

<!-- cortex-logic -->

## test_feature_lists_exclude_the_fuel_mix

No parameters go in. Sets def test_feature_lists_exclude_the_fuel_mix() -> None: used to set of DAY_AHEAD_CATEGORICAL + DAY_AHEAD_NUMERIC + CYCLICAL_NUMERIC + OBSERVED_NOW + PREVIOUS_HOUR.

<!-- cortex-logic -->

## test_model_frame_lag_is_twenty_four_hours

No parameters go in. Sets def test_model_frame_lag_is_twenty_four_hours() -> None: index to pd.date_range of 2026-01-01, periods=200, freq=h, and tz=UTC.

<!-- cortex-logic -->

## test_train_test_split_is_ordered_and_disjoint

No parameters go in. Sets def test_train_test_split_is_ordered_and_disjoint() -> None: index to pd.date_range of 2026-01-01, periods=24 * 40, freq=h, and tz=UTC.

<!-- cortex-logic -->

## test_shift_regret_is_zero_when_the_order_is_right

No parameters go in. Sets def test_shift_regret_is_zero_when_the_order_is_right() -> None: actual to np.array of a list of 10.0, 80.0, 20.0, and 90.0. Sets predicted to actual plus 40.0.

<!-- cortex-logic -->

## test_shift_regret_is_the_extra_carbon_of_the_wrong_hours

No parameters go in. Sets def test_shift_regret_is_the_extra_carbon_of_the_wrong_hours() -> None: actual to np.array of a list of 10.0, 80.0, 20.0, and 90.0. Sets predicted to np.array of a list of 90.0, 10.0, 80.0, and 20.0.

<!-- cortex-logic -->

## test_shape_mae_ignores_a_constant_level_miss

No parameters go in. Sets def test_shape_mae_ignores_a_constant_level_miss() -> None: actual to np.array of a list of 10.0, 30.0, and 20.0.

<!-- cortex-logic -->

<!-- cortex-source-hash:bfd3d199bfdeafcf648c68c457d8c2307a747cb40c1a86b1b364247732fbc6ec -->
