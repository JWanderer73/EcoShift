"""UTC time helpers. Everything is stored in UTC; display code converts."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
HOUR = timedelta(hours=1)


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def utcnow() -> datetime:
    """Current time. Set CARBON_NOW to freeze it (tests, fixtures, demos)."""
    fixed = os.environ.get("CARBON_NOW")
    return parse_iso(fixed) if fixed else datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)
