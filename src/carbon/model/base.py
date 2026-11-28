"""The interface every model implements.

This is the only contract between the modelling work and the rest of the system.
Replace or add a model by implementing `Model` and registering it in
`registry.py`; the jobs, API, dashboard and infrastructure do not change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

import numpy as np

from carbon.common.timeutil import HOUR, iso, parse_iso


@dataclass
class History:
    """Hourly observations. `values[0]` is the hour starting at `start` (UTC)."""

    start: datetime
    values: np.ndarray

    def __len__(self) -> int:
        return len(self.values)

    @property
    def end(self) -> datetime:
        """The first hour *after* the history, i.e. the first hour to forecast."""
        return self.start + len(self.values) * HOUR

    def head(self, n: int) -> "History":
        return History(self.start, self.values[:n])

    def to_dict(self) -> dict:
        return {"start": iso(self.start), "values": [round(float(v), 3) for v in self.values]}

    @classmethod
    def from_dict(cls, d: dict) -> "History":
        return cls(parse_iso(d["start"]), np.asarray(d["values"], dtype=float))


@dataclass
class Forecast:
    p50: np.ndarray
    p10: np.ndarray
    p90: np.ndarray


class Model(ABC):
    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def fit(cls, history: History) -> "Model":
        """Train on `history` and return a fitted model."""

    @abstractmethod
    def predict(self, history: History, horizon: int) -> Forecast:
        """Forecast the `horizon` hours after `history.end`.

        Must only use `history` and the fitted parameters, so the same call can
        be used for backtests (a truncated history) and for production.
        """

    @abstractmethod
    def params(self) -> dict:
        """JSON-serialisable fitted parameters."""

    @classmethod
    @abstractmethod
    def from_params(cls, params: dict) -> "Model": ...

    def to_dict(self) -> dict:
        return {"name": self.name, "params": self.params()}


def mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.asarray(y_true, float) - np.asarray(y_pred, float))))
