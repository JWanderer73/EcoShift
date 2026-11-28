"""Window search. Pure functions over a list of hourly prices, no ML involved.

Prices are $/MWh and can be zero or negative, so savings are differences in dollars,
never percentages (a percentage is undefined when the price you start from is not positive).
"""

from __future__ import annotations

import numpy as np


def window_averages(values, duration: int, max_delay: int) -> list[float]:
    """Average price of a `duration`-hour job starting 0..max_delay hours from now."""
    last_start = min(max_delay, len(values) - duration)
    if duration < 1 or last_start < 0:
        return []
    csum = np.concatenate(([0.0], np.cumsum(np.asarray(values, dtype=float))))
    return [float((csum[s + duration] - csum[s]) / duration) for s in range(last_start + 1)]


def job_dollars(price_usd_per_mwh: float, kw: float, duration: int) -> float:
    """Wholesale cost of a constant `kw` load for `duration` hours: $/MWh x kWh / 1000."""
    return float(price_usd_per_mwh) * float(kw) * int(duration) / 1000.0


def best_windows(values, duration: int, max_delay: int, top: int = 3) -> list[dict]:
    """Top non-overlapping windows, cheapest first. `savings` is $/MWh below starting now."""
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
    return [{"start_offset_h": s, "avg": avgs[s], "savings": now_avg - avgs[s]} for s in chosen]
