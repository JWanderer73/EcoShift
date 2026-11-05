"""Check that the demand models learned something, and did not see the answer.

Run it after ``python -m src.compare_models``. It reads the comparison
table and the saved models, then asks five questions:

1. Does the best model beat copying demand from yesterday and from last
   week? Its skill against CAISO's own forecast is reported beside it.
2. Is any model much worse on the test block than on the forward folds
   inside training? That gap is overfitting.
3. If the target is shuffled, does XGBoost stop working? It should. A
   model that still scores well on a shuffled target is reading the
   answer from a feature.
4. Does one feature carry most of the importance? That is the usual
   sign of a leak.
5. Where does the best model miss: which hours of the day, and the
   hottest days of the test block?

Questions 1 and 3 fail the run. Questions 2 and 4 are warnings.

    python -m src.check_models
    python -m src.check_models --variant weather_forecast_standin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from src.build_demand_dataset import BENCHMARK, DEFAULT_VARIANT, LOCAL_TZ, VARIANTS, source_path
from src.carbon_data import repo_root
from src.column_audit import CITY_NAMES
from src.compare_models import results_path
from src.forecast_data import TARGET, data_path, features, score, train_test_hours
from src.xgb_benchmark import make_model as make_xgboost

# Test MAE above this multiple of the forward-fold MAE is flagged.
OVERFIT_RATIO = 1.5
# A shuffled-target model must stay at least this close to the error of
# predicting the training mean. Lower means it still found the answer.
SHUFFLED_MIN_RATIO = 0.8
# One feature carrying more than this share of importance is flagged.
DOMINANT_SHARE = 0.60
# The hottest share of test days scored on their own.
HOT_DAY_SHARE = 0.10
PERMUTATION_REPEATS = 5
SEED = 0


def checks_path(variant: str = DEFAULT_VARIANT) -> Path:
    """Where a variant's check report is written."""
    name = "model_checks.json" if variant == DEFAULT_VARIANT else f"model_checks_{variant}.json"
    return repo_root() / "results" / name


def beats_baselines(results: list[dict]) -> dict:
    """The best model against the two copy-the-past baselines, and its skill against CAISO."""
    models = [row for row in results if row["kind"] == "model"]
    baselines = {row["model"]: row["mae"] for row in results if row["kind"] == "baseline"}
    best = min(models, key=lambda row: row["mae"])
    naive = {name: mae for name, mae in baselines.items() if name != "CAISO forecast"}
    caiso = baselines.get("CAISO forecast")
    return {
        "best_model": best["model"],
        "best_mae": best["mae"],
        "baseline_mae": naive,
        "skill_vs_caiso": None if not caiso else 1.0 - best["mae"] / caiso,
        "skill_vs_yesterday": None if "Same hour yesterday" not in naive else 1.0 - best["mae"] / naive["Same hour yesterday"],
        "passed": all(best["mae"] < mae for mae in naive.values()),
    }


def overfit_gaps(results: list[dict]) -> dict:
    """Training, forward-fold, and test MAE per model, flagging a large test-to-fold gap."""
    rows = []
    for row in results:
        if row["kind"] != "model" or not row.get("cv_mae"):
            continue
        ratio = row["mae"] / row["cv_mae"]
        rows.append(
            {
                "model": row["model"],
                "train_mae": row["train_mae"],
                "cv_mae": row["cv_mae"],
                "test_mae": row["mae"],
                "test_over_cv": ratio,
                "flagged": ratio > OVERFIT_RATIO,
            }
        )
    return {"models": rows, "warning": any(row["flagged"] for row in rows)}


def shuffled_target(train: pd.DataFrame, test: pd.DataFrame, results: list[dict]) -> dict:
    """Refit XGBoost on a shuffled target and compare it with predicting the training mean."""
    params = next((row["best_params"] for row in results if row["model"] == "XGBoost"), {})
    model = make_xgboost().set_params(**params)
    shuffled = np.random.default_rng(SEED).permutation(train[TARGET].to_numpy())
    model.fit(features(train), shuffled)
    shuffled_mae = score(test[TARGET], np.maximum(model.predict(features(test)), 0.0))["mae"]
    mean_mae = score(test[TARGET], np.full(len(test), train[TARGET].mean()))["mae"]
    ratio = shuffled_mae / mean_mae
    return {
        "shuffled_mae": shuffled_mae,
        "predict_mean_mae": mean_mae,
        "ratio": ratio,
        "passed": ratio >= SHUFFLED_MIN_RATIO,
    }


def _shares(values: pd.Series) -> pd.Series:
    clipped = values.clip(lower=0.0)
    total = clipped.sum()
    return (clipped / total if total > 0 else clipped).sort_values(ascending=False)


def importance(best: dict, results: list[dict], test: pd.DataFrame) -> dict:
    """XGBoost gain shares and permutation-importance shares for the best model, on the test block."""
    report = {}
    xgb_row = next((row for row in results if row["model"] == "XGBoost"), None)
    if xgb_row:
        booster = joblib.load(xgb_row["model_path"]).get_booster()
        gain = pd.Series(booster.get_score(importance_type="gain"), dtype=float)
        report["xgboost_gain"] = _shares(gain).head(10).round(4).to_dict()
    model = joblib.load(best["model_path"])
    permuted = permutation_importance(
        model,
        features(test),
        test[TARGET],
        scoring="neg_mean_absolute_error",
        n_repeats=PERMUTATION_REPEATS,
        random_state=SEED,
    )
    shares = _shares(pd.Series(permuted.importances_mean, index=features(test).columns))
    report["permutation_model"] = best["model"]
    report["permutation"] = shares.head(10).round(4).to_dict()
    top = max([shares.iloc[0], *report.get("xgboost_gain", {0: 0.0}).values()])
    report["top_share"] = float(top)
    report["warning"] = bool(top > DOMINANT_SHARE)
    return report


def _hot_days(test: pd.DataFrame) -> set:
    """Local dates in the test block whose hottest hour is in the top ``HOT_DAY_SHARE``.

    Temperature comes from the cleaned table at the same hour. That is
    allowed here, because this only picks which days to score.
    """
    raw = pd.read_csv(source_path(), index_col=0, parse_dates=True)
    raw.index = pd.to_datetime(raw.index, utc=True)
    temp = raw[[f"{city}_temperature_2m" for city in CITY_NAMES]].mean(axis=1).reindex(test.index)
    daily_max = temp.groupby(test.index.tz_convert(LOCAL_TZ).date).max()
    return set(daily_max[daily_max >= daily_max.quantile(1.0 - HOT_DAY_SHARE)].index)


def slices(best: dict, test: pd.DataFrame) -> dict:
    """MAE by local hour, and on the hottest test days, for the best model, yesterday, and CAISO."""
    predicted = np.maximum(joblib.load(best["model_path"]).predict(features(test)), 0.0)
    forecasts = {
        best["model"]: pd.Series(predicted, index=test.index),
        "Same hour yesterday": test["demand_lag_24"],
        "CAISO forecast": test[BENCHMARK],
    }
    local = test.index.tz_convert(LOCAL_TZ)
    by_hour = {
        name: (test[TARGET] - forecast).abs().groupby(local.hour).mean().round(1).to_dict()
        for name, forecast in forecasts.items()
    }
    hot = _hot_days(test)
    in_hot = np.isin(local.date, list(hot))
    hot_days = {
        name: {"hot_mae": score(test[TARGET][in_hot], forecast[in_hot])["mae"], "other_mae": score(test[TARGET][~in_hot], forecast[~in_hot])["mae"]}
        for name, forecast in forecasts.items()
    }
    return {"mae_by_local_hour": by_hour, "hot_days": sorted(str(day) for day in hot), "hot_day_mae": hot_days}


def run(variant: str = DEFAULT_VARIANT) -> dict:
    """Run every check for one variant and write the report."""
    path_in = results_path(variant)
    if not path_in.exists():
        raise FileNotFoundError(f"{path_in} is missing. Run: python -m src.compare_models --variant {variant}")
    results = json.loads(path_in.read_text())
    train, test = train_test_hours(data_path(variant))
    best = min((row for row in results if row["kind"] == "model"), key=lambda row: row["mae"])

    report = {
        "variant": variant,
        "dataset_hash": test.attrs.get("content_hash"),
        "beats_baselines": beats_baselines(results),
        "overfit": overfit_gaps(results),
        "shuffled_target": shuffled_target(train, test, results),
        "importance": importance(best, results, test),
        "slices": slices(best, test),
    }
    report["passed"] = report["beats_baselines"]["passed"] and report["shuffled_target"]["passed"]
    path_out = checks_path(variant)
    path_out.write_text(json.dumps(report, indent=2, default=str))
    _print(report)
    print(f"wrote {path_out}")
    return report


def _print(report: dict) -> None:
    beat = report["beats_baselines"]
    print(f"variant: {report['variant']}")
    print(f"1. best model {beat['best_model']}: MAE {beat['best_mae']:.1f} MWh")
    for name, mae in beat["baseline_mae"].items():
        print(f"   {name}: MAE {mae:.1f} MWh")
    if beat["skill_vs_caiso"] is not None:
        print(f"   skill vs CAISO forecast: {beat['skill_vs_caiso']:.1%}")
    print(f"   {'PASS' if beat['passed'] else 'FAIL'}: beats both copy-the-past baselines")
    print("2. test MAE over forward-fold MAE:")
    for row in report["overfit"]["models"]:
        mark = "  <- flagged" if row["flagged"] else ""
        print(f"   {row['model']:<24} train {row['train_mae']:7.1f}  folds {row['cv_mae']:7.1f}  test {row['test_mae']:7.1f}  ratio {row['test_over_cv']:.2f}{mark}")
    shuffled = report["shuffled_target"]
    print(
        f"3. shuffled target: MAE {shuffled['shuffled_mae']:.1f} vs predicting the mean {shuffled['predict_mean_mae']:.1f} "
        f"(ratio {shuffled['ratio']:.2f}) {'PASS' if shuffled['passed'] else 'FAIL'}"
    )
    imp = report["importance"]
    print(f"4. top importance share {imp['top_share']:.0%} {'WARNING' if imp['warning'] else 'ok'}")
    for name, share in list(imp["permutation"].items())[:5]:
        print(f"   {name}: {share:.0%} of permutation importance ({imp['permutation_model']})")
    hot = report["slices"]["hot_day_mae"]
    print(f"5. hottest {len(report['slices']['hot_days'])} test days:")
    for name, values in hot.items():
        print(f"   {name:<24} hot-day MAE {values['hot_mae']:7.1f}  other days {values['other_mae']:7.1f}")
    print("PASSED" if report["passed"] else "FAILED")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the demand models after a comparison run.")
    parser.add_argument("--variant", choices=VARIANTS, default=DEFAULT_VARIANT)
    args = parser.parse_args()
    report = run(args.variant)
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
