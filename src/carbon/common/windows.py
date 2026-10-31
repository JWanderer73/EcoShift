"""Window search. Pure functions over a list of hourly values, no ML involved."""

from __future__ import annotations

import numpy as np


def window_averages(values, duration: int, max_delay: int) -> list[float]:
    """Average intensity of a `duration`-hour job starting 0..max_delay hours from now."""
    last_start = min(max_delay, len(values) - duration)
    if duration < 1 or last_start < 0:
        return []
    csum = np.concatenate(([0.0], np.cumsum(np.asarray(values, dtype=float))))
    return [float((csum[s + duration] - csum[s]) / duration) for s in range(last_start + 1)]


def savings_pct(now_avg: float, avg: float) -> float:
    return 0.0 if now_avg <= 0 else 100.0 * (now_avg - avg) / now_avg


def best_windows(values, duration: int, max_delay: int, top: int = 3) -> list[dict]:
    """Top non-overlapping windows, best first. Savings are relative to starting now."""
    avgs = window_averages(values, duration, max_delay)
    if not avgs:
        return []
    now_avg = avgs[0]
    chosen: list[int] = []
    for start in sorted(range(len(avgs)), key=lambda s: (avgs[s], s)):
        if all(abs(start - c) >= duration for c in chosen):
            chosen.append(start)
        if len(chosen) == top:
            break
    return [
        {
            "start_offset_h": s,
            "avg": avgs[s],
            "savings_pct": savings_pct(now_avg, avgs[s]),
        }
        for s in chosen
    ]
