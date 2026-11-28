"""Find the lowest-emission time windows for a job.

Pure logic with no I/O or data loading, so the local API stand-in and the
future serving Lambda can share it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean
from typing import Protocol

HOUR = timedelta(hours=1)


class HourlyPoint(Protocol):
    """One forecast hour: its ``start`` time and ``intensity`` in gCO2/kWh."""

    @property
    def start(self) -> datetime: ...

    @property
    def intensity(self) -> float: ...


@dataclass(frozen=True)
class Window:
    """A time to run the job.

    Attributes:
        start: When the job starts.
        end: When the job finishes.
        avg_intensity: Mean forecast intensity over the window, in gCO2/kWh.
        co2_saved_pct: Percent less CO2 than starting at the first forecast
            hour. Negative if this window is dirtier than running now.
    """

    start: datetime
    end: datetime
    avg_intensity: float
    co2_saved_pct: float


def find_best_windows(
    points: Sequence[HourlyPoint],
    duration_hours: int,
    deadline: datetime,
    top: int = 3,
) -> tuple[Window, list[Window]]:
    """Rank the cleanest non-overlapping windows that finish by the deadline.

    Args:
        points: Consecutive hourly forecast points, earliest first.
        duration_hours: Job length in whole hours.
        deadline: Latest time the job may finish.
        top: Maximum number of windows to return.

    Returns:
        ``(baseline, windows)``: the window starting at the first point
        ("run now"), and up to ``top`` non-overlapping windows, cleanest
        first. Ties go to the earlier start.

    Raises:
        ValueError: If ``duration_hours`` or ``top`` is below 1, or no window
            fits before the deadline.
    """
    if duration_hours < 1:
        raise ValueError("duration_hours must be at least 1")
    if top < 1:
        raise ValueError("top must be at least 1")
    job_length = duration_hours * HOUR
    starts = [
        i
        for i in range(len(points) - duration_hours + 1)
        if points[i].start + job_length <= deadline
    ]
    if not starts:
        raise ValueError(
            f"a {duration_hours}h job doesn't fit before the deadline "
            f"({deadline:%Y-%m-%d %H:%M %Z})"
        )

    averages = {i: fmean(p.intensity for p in points[i : i + duration_hours]) for i in starts}
    baseline_avg = averages[0]

    def to_window(i: int) -> Window:
        saved = (baseline_avg - averages[i]) / baseline_avg * 100 if baseline_avg else 0.0
        return Window(
            points[i].start, points[i].start + job_length, round(averages[i], 1), round(saved, 1)
        )

    # Greedy: take the cleanest start, skip any that overlap one already taken.
    chosen: list[int] = []
    for i in sorted(starts, key=lambda i: (averages[i], i)):
        if all(abs(i - j) >= duration_hours for j in chosen):
            chosen.append(i)
            if len(chosen) == top:
                break
    return to_window(0), [to_window(i) for i in chosen]
