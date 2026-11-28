"""The only place that touches the vendored model code.

Importing is lazy and goes through `model_dir()` so the rest of the package (and the API) never
load pandas, xgboost or the model team's modules unless a price job actually runs.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from carbon.price.sites import model_dir


def load() -> SimpleNamespace:
    """Import the model team's modules and return the handful of functions we call.

    These are their private helpers (`_feature_frame`, `_fetch_weather`, ...). They are used as is,
    so when the model team changes `price_windows/`, `tests/test_price.py` is what
    tells us whether the names or signatures changed.
    """
    path = str(model_dir())
    if path not in sys.path:
        sys.path.insert(0, path)  # `price_windows` is the model team's package, used as is
    import price_windows.build_dataset as build
    import price_windows.recommend as recommend
    import price_windows.schema as schema

    return SimpleNamespace(
        TARGET=schema.TARGET,
        LOAD_FEATURE=schema.LOAD_FEATURE,
        GAS_FEATURE=schema.GAS_FEATURE,
        WEATHER_FEATURES=schema.WEATHER_FEATURES,
        HORIZON_HOURS=schema.HORIZON_DAYS * 24,
        feature_frame=recommend._feature_frame,
        static_features=recommend._static,
        predict_price=recommend.predict_price,
        fetch_weather=recommend._fetch_weather,
        fetch_load=recommend._fetch_load,
        fetch_lmp=build._lmp_chunk,
        illegal_feature_names=schema.illegal_feature_names,
    )
