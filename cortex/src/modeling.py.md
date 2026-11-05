src/modeling.py

# modeling.py

modeling.py exports check_features, train_test_split, fit_validation_split, feature_matrix, score_predictions, and hour_climatology.

<!-- cortex-file -->

## check_features

columns goes in. Sets leaked to sorted of set(columns) & LEAKED_COLUMNS. If ffeatures include the carbon formula: {leaked}, it continues.

<!-- cortex-logic -->

## train_test_split

frame and test_days go in. Sets cutoff to frame.index.max of ) - pd.Timedelta(days=test_days.

<!-- cortex-logic -->

## fit_validation_split

train and val_days go in. Sets cutoff to train.index.max of ) - pd.Timedelta(days=val_days.

<!-- cortex-logic -->

## feature_matrix

frame, categorical, and numeric go in. Sets columns to list of categorical) + list(numeric. Calls check_features with columns. Gives frame.loc[:, columns] back.

<!-- cortex-logic -->

## score_predictions

y_true and y_pred go in. It builds an object and gives that object back.

<!-- cortex-logic -->

## hour_climatology

train and when go in. Sets means to train.groupby of hour_local)[TARGET].mean(. Sets fallback to float of train[TARGET].mean(. Gives means.reindex of when[hour_local].to_numpy()).fillna(fallback).to_numpy( back.

<!-- cortex-logic -->

## pinball_loss

y_true, y_pred, and quantile go in. Sets error to np.asarray of y_true and dtype=float) - np.maximum(np.asarray(y_pred, dtype=float), 0.0.

<!-- cortex-logic -->

## coverage

y_true and y_pred go in. Sets actual to np.asarray of y_true and dtype=float. Sets predicted to np.maximum of np.asarray of y_pred and dtype=float and 0.0. Gives float of np.mean of actual <= predicted back.

<!-- cortex-logic -->

## result_row

name, y_true, y_pred, cv_mae, and climatology_mae go in. It gives row back unchanged.

<!-- cortex-logic -->

## linear_pipeline

estimator, categorical, and numeric go in. Calls check_features with list of categorical) + list(numeric.

<!-- cortex-logic -->

## cross_validated_mae

estimator, x_train, y_train, and n_splits go in. Sets folds to an empty list.

<!-- cortex-logic -->

## search_time_series

estimator, param_grid, x_train, y_train, and n_splits go in. Sets def _clipped_neg_mae(estimator, features, target): predicted to np.maximum of estimator.predict of features and 0.0.

<!-- cortex-logic -->

## _clipped_neg_mae

estimator, features, and target go in. Sets def _clipped_neg_mae(estimator, features, target): predicted to np.maximum of estimator.predict of features and 0.0.

<!-- cortex-logic -->

## make_tree

loss, quantile, and overrides go in. Sets params to dict of TREE_PARAMS.

<!-- cortex-logic -->

## fit_tree

train, categorical, numeric, loss, quantile, and overrides go in. Sets matrix to feature_matrix of train, categorical, and numeric.

<!-- cortex-logic -->

## predict_tree

model, frame, categorical, and numeric go in. Sets matrix to feature_matrix of frame, categorical, and numeric.

<!-- cortex-logic -->

## clip_prediction

predicted goes in. Gives np.maximum of np.asarray of predicted and dtype=float and 0.0 back.

<!-- cortex-logic -->

## error_components

y_true and y_pred go in. It builds an object and gives that object back.

<!-- cortex-logic -->

## shift_regret

actual, predicted, and hours go in. Sets actual to np.asarray of actual and dtype=float.

<!-- cortex-logic -->

## shape_mae

actual and predicted go in. Sets actual to np.asarray of actual and dtype=float.

<!-- cortex-logic -->

## local_day_labels

frame goes in. Sets dates to frame.index.tz_convert(America/Los_Angeles).date. Gives pd.Series of dates, index=frame.index, and name=local_day back.

<!-- cortex-logic -->

## _rank_correlation

actual and predicted go in. Gives float of pd.Series of actual).corr(pd.Series(predicted), method=spearman back.

<!-- cortex-logic -->

## day_scores

frame, predicted, and hours go in. Sets labels to local_day_labels of frame.

<!-- cortex-logic -->

## fixed_forecasts

train and test go in. It gives forecasts back unchanged.

<!-- cortex-logic -->

<!-- cortex-source-hash:28d41f98d2b649aa4fc26760c45091b3dd41b7a618f8e9c9956be636cc215512 -->
