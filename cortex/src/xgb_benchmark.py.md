src/xgb_benchmark.py

# xgb_benchmark.py

xgb_benchmark.py exports make_model, run, and main.

<!-- cortex-file -->

## make_model

No parameters go in. Gives XGBRegressor of objective=reg:squarederror, tree_method=hist, n_jobs=-1, random_state=0, and verbosity=0 back.

<!-- cortex-logic -->

## run

path and param_grid go in. Sets train, test to train_test_hours of path.

<!-- cortex-logic -->

## main

No parameters go in. It handles main.

<!-- cortex-logic -->

<!-- cortex-source-hash:8410a1da9d003f66fa9dba47c6ab9b630000592a36c0693faf9c839eb586d74d -->
