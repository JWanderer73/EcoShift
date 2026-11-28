"""Validation applied to each source before it is joined into the clean table."""

from __future__ import annotations

import numpy as np


class ValidationError(ValueError):
    """The batch is unusable; the pipeline stops and keeps the previous clean table."""


def drop_duplicate_timestamps(records: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Keep the last value seen for each timestamp, sorted by timestamp."""
    latest: dict[str, float] = {}
    for ts, value in records:
        latest[ts] = value
    return sorted(latest.items())


def validate_series(
    values,
    min_value: float = 0.0,
    max_value: float = 2000.0,
    max_gap: int = 3,
) -> tuple[np.ndarray, float]:
    """Null out impossible values, then fill short gaps by interpolation.

    Returns (clean_values, imputed_fraction). Gaps longer than `max_gap` hours
    raise ValidationError instead of being papered over.
    """
    arr = np.asarray(values, dtype=float).copy()
    arr[~np.isfinite(arr) | (arr < min_value) | (arr > max_value)] = np.nan
    n = len(arr)
    imputed = 0
    i = 0
    while i < n:
        if not np.isnan(arr[i]):
            i += 1
            continue
        j = i
        while j < n and np.isnan(arr[j]):
            j += 1
        gap = j - i
        if gap > max_gap:
            raise ValidationError(f"gap of {gap} hours starting at index {i} (max {max_gap})")
        left = arr[i - 1] if i > 0 else None
        right = arr[j] if j < n else None
        if left is None and right is None:
            raise ValidationError("series has no valid values")
        if left is None:
            arr[i:j] = right
        elif right is None:
            arr[i:j] = left
        else:
            arr[i:j] = np.linspace(left, right, gap + 2)[1:-1]
        imputed += gap
        i = j
    return arr, (imputed / n if n else 0.0)
