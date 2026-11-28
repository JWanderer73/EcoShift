import numpy as np
import pytest

from carbon.common.validate import ValidationError, drop_duplicate_timestamps, validate_series


def test_impossible_values_are_replaced():
    values, imputed = validate_series([100, -5, 120, 99999, 130])
    assert list(values) == [100, 110, 120, 125, 130]
    assert imputed == pytest.approx(0.4)


def test_short_gaps_are_interpolated():
    values, _ = validate_series([100, np.nan, np.nan, 130])
    assert list(values) == [100, 110, 120, 130]


def test_long_gaps_raise():
    with pytest.raises(ValidationError):
        validate_series([100] + [np.nan] * 5 + [100])


def test_duplicate_timestamps_keep_the_last_value():
    records = [("t2", 2.0), ("t1", 1.0), ("t2", 3.0)]
    assert drop_duplicate_timestamps(records) == [("t1", 1.0), ("t2", 3.0)]
