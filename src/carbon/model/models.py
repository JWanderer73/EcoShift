"""Baseline models. The first deployed champion is a baseline; later models must beat it."""

from __future__ import annotations

import numpy as np

from carbon.model.base import Forecast, History, Model


def _offsets(residuals: np.ndarray) -> tuple[float, float]:
    q10, q90 = np.percentile(residuals, [10, 90])
    return float(q10), float(q90)


class SeasonalNaive(Model):
    """Forecast = the value one week ago (or one day ago if history is short)."""

    name = "baseline"

    def __init__(self, period: int, q10: float, q90: float):
        self.period, self.q10, self.q90 = period, q10, q90

    @classmethod
    def fit(cls, history: History) -> "SeasonalNaive":
        v = history.values
        period = 168 if len(v) >= 168 + 24 else 24
        if len(v) <= period:
            raise ValueError(f"need more than {period} hours of history, got {len(v)}")
        residuals = (v[period:] - v[:-period])[-168:]
        return cls(period, *_offsets(residuals))

    def predict(self, history: History, horizon: int) -> Forecast:
        p50 = np.resize(history.values[-self.period :], horizon).astype(float)
        return Forecast(p50, p50 + self.q10, p50 + self.q90)

    def params(self) -> dict:
        return {"period": self.period, "q10": self.q10, "q90": self.q90}

    @classmethod
    def from_params(cls, params: dict) -> "SeasonalNaive":
        return cls(int(params["period"]), float(params["q10"]), float(params["q90"]))


class HourOfDayMean(Model):
    """Forecast = the average for that hour of the day over the training history."""

    name = "hod_mean"

    def __init__(self, means: list[float], q10: float, q90: float):
        self.means, self.q10, self.q90 = means, q10, q90

    @classmethod
    def fit(cls, history: History) -> "HourOfDayMean":
        hours = (history.start.hour + np.arange(len(history))) % 24
        means = np.array(
            [history.values[hours == h].mean() if (hours == h).any() else history.values.mean() for h in range(24)]
        )
        return cls(means.tolist(), *_offsets(history.values - means[hours]))

    def predict(self, history: History, horizon: int) -> Forecast:
        hours = (history.end.hour + np.arange(horizon)) % 24
        p50 = np.asarray(self.means)[hours]
        return Forecast(p50, p50 + self.q10, p50 + self.q90)

    def params(self) -> dict:
        return {"means": self.means, "q10": self.q10, "q90": self.q90}

    @classmethod
    def from_params(cls, params: dict) -> "HourOfDayMean":
        return cls([float(m) for m in params["means"]], float(params["q10"]), float(params["q90"]))
