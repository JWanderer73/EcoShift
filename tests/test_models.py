from datetime import datetime, timezone

import numpy as np
import pytest

from carbon.model import History, load_model, mae
from carbon.model.models import HourOfDayMean, SeasonalNaive

START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def periodic(days: int) -> History:
    day = np.array([100 + 10 * h for h in range(24)], dtype=float)
    return History(START, np.tile(day, days))


@pytest.mark.parametrize("cls", [SeasonalNaive, HourOfDayMean])
def test_perfectly_periodic_data_is_forecast_exactly(cls):
    history = periodic(14)
    model = cls.fit(history.head(len(history) - 48))
    pred = model.predict(history.head(len(history) - 48), 48)
    assert mae(history.values[-48:], pred.p50) == pytest.approx(0)
    assert (pred.p10 <= pred.p50).all() and (pred.p50 <= pred.p90).all()


@pytest.mark.parametrize("cls", [SeasonalNaive, HourOfDayMean])
def test_models_round_trip_through_json(cls):
    history = periodic(14)
    model = cls.fit(history)
    clone = load_model(model.to_dict())
    assert np.allclose(model.predict(history, 24).p50, clone.predict(history, 24).p50)


def test_too_little_history_is_an_error():
    with pytest.raises(ValueError):
        SeasonalNaive.fit(periodic(1))
