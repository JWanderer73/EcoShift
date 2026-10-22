"""``carbon``: find the lowest-emission time to run a job, from the terminal.

The CLI only parses options, asks the API for windows, and prints the
response. See ``src/api.py`` for where the answer comes from.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from src.api import DEFAULT_REGION, DEFAULT_TOP, SUPPORTED_REGIONS, ApiError, get_windows

MAX_TOP = 10
MINUTES_PER_HOUR = 60
TIME_FORMAT = "%a %H:%M"  # weekday is enough to tell days apart within 48 hours
_DURATION_PATTERN = re.compile(r"(?:(?P<hours>\d+(?:\.\d+)?)h)?(?:(?P<minutes>\d+)m)?")

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Find the lowest-emission time to run a job."""


@app.command()
def windows(
    duration: Annotated[
        str, typer.Option("--duration", "-d", help="How long the job runs: 4h, 90m, 1h30m.")
    ],
    deadline: Annotated[
        str | None,
        typer.Option(
            help="When the job must finish: 2026-10-22T09:00 or 24h from now. "
            "Default: end of the 48h forecast."
        ),
    ] = None,
    region: Annotated[
        str, typer.Option("--region", "-r", help=f"Grid region: {', '.join(SUPPORTED_REGIONS)}.")
    ] = DEFAULT_REGION,
    top: Annotated[
        int, typer.Option(min=1, max=MAX_TOP, help="How many windows to show.")
    ] = DEFAULT_TOP,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the API response as JSON, for coding agents.")
    ] = False,
) -> None:
    """Show the best times to run a job before its deadline."""
    now = datetime.now(UTC)
    duration_hours = parse_duration_hours(duration)
    deadline_at = parse_deadline(deadline, now) if deadline else None
    try:
        response = get_windows(duration_hours, deadline_at, region.upper(), top, now)
    except ApiError as err:
        typer.echo(f"Error: {err}", err=True)
        raise typer.Exit(code=1) from err

    if response["job"]["deadline_clamped"]:
        typer.echo(
            "Warning: the deadline is past the 48-hour forecast; using the forecast end.",
            err=True,
        )
    if as_json:
        typer.echo(json.dumps(response, indent=2))
    else:
        _print_table(response)


def parse_duration_hours(text: str) -> int:
    """Parse a job length and round it up to whole hours.

    Args:
        text: ``4h``, ``90m``, ``1h30m``, or a bare number of hours.

    Returns:
        The duration in whole hours, rounded up.

    Raises:
        typer.BadParameter: If ``text`` isn't a positive duration.
    """
    hours = _parse_hours(text)
    if hours is None or not math.isfinite(hours) or hours <= 0:
        raise typer.BadParameter(
            f"{text!r} isn't a duration; try 4h, 90m, or 1h30m", param_hint="--duration"
        )
    return math.ceil(hours)


def parse_deadline(text: str, now: datetime) -> datetime:
    """Parse a deadline as a duration from ``now`` or an ISO 8601 datetime.

    Args:
        text: ``24h``-style duration, or a datetime like ``2026-10-22T09:00``.
            A datetime without a timezone is read as the machine's local time.
        now: Current time, timezone-aware.

    Returns:
        The deadline, timezone-aware.

    Raises:
        typer.BadParameter: If ``text`` is neither.
    """
    error = typer.BadParameter(
        f"{text!r} isn't a deadline; use a time like 2026-10-22T09:00 or a duration like 24h",
        param_hint="--deadline",
    )
    hours = _parse_hours(text)
    if hours is not None:
        if not math.isfinite(hours) or hours <= 0:
            raise error
        try:
            return now + timedelta(hours=hours)
        except OverflowError:
            raise error from None
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError:
        raise error from None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _parse_hours(text: str) -> float | None:
    """Return ``text`` as a number of hours, or None if it isn't duration syntax."""
    text = text.strip().lower()
    try:
        return float(text)
    except ValueError:
        pass
    match = _DURATION_PATTERN.fullmatch(text)
    if not match or not (match["hours"] or match["minutes"]):
        return None
    return float(match["hours"] or 0) + int(match["minutes"] or 0) / MINUTES_PER_HOUR


def _print_table(response: dict) -> None:
    console = Console()
    if response["data_source"] == "synthetic":
        console.print("[yellow]Synthetic data: made-up forecasts, not real grid data.[/yellow]")
    if response["stale"]:
        console.print("[yellow]Stale forecast: the API couldn't refresh it recently.[/yellow]")
    console.print(
        f"Region {response['region']} · forecast from {_local(response['generated_at'])} · "
        f"running now: {response['baseline']['avg_intensity_g_per_kwh']:.0f} gCO₂/kWh"
    )
    table = Table("Rank", "Start", "End", "Avg gCO₂/kWh", "CO₂ saved")
    for window in response["windows"]:
        table.add_row(
            str(window["rank"]),
            _local(window["start"]),
            _local(window["end"]),
            f"{window['avg_intensity_g_per_kwh']:.0f}",
            f"{window['co2_saved_pct']:.0f}%",
        )
    console.print(table)


def _local(iso_time: str) -> str:
    return datetime.fromisoformat(iso_time).astimezone().strftime(TIME_FORMAT)
