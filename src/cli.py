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
from rich.text import Text

from src.api import (
    DEFAULT_REGION,
    DEFAULT_TOP,
    SUPPORTED_REGIONS,
    ApiError,
    get_forecast,
    get_windows,
)

MAX_TOP = 10
MINUTES_PER_HOUR = 60
HOUR = timedelta(hours=1)
TIME_FORMAT = "%a %H:%M"  # weekday is enough to tell days apart within 48 hours
BARS = "▁▂▃▄▅▆▇█"  # chart bars, lowest to highest intensity
INTENSITY_STYLES = ("green", "yellow", "red")  # cleanest third of the forecast to dirtiest
AXIS_LABEL_EVERY_HOURS = 12
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
        # Only the table draws the hourly chart; --json stays a single API call.
        forecast = None if as_json else get_forecast(region.upper(), now)
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
        _print_table(response, forecast, now)


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


def format_relative(moment: datetime, now: datetime) -> str:
    """Say how far ahead ``moment`` is: ``now``, ``in 25m``, ``in 3h`` or ``in 21h 25m``."""
    minutes = round((moment - now).total_seconds() / 60)
    if minutes <= 0:
        return "now"
    hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
    if not hours:
        return f"in {minutes}m"
    return f"in {hours}h {minutes}m" if minutes else f"in {hours}h"


def format_headline(response: dict, now: datetime) -> str:
    """One line naming the best window, when it starts, and the CO₂ it saves."""
    best = response["windows"][0]
    start = datetime.fromisoformat(best["start"])
    when = _local_span(best["start"], best["end"])
    if start == datetime.fromisoformat(response["baseline"]["start"]):
        return f"Best: run now ({when}). Nothing cleaner before the deadline."
    return (
        f"Best: {when} ({format_relative(start, now)}) · "
        f"{best['co2_saved_pct']:.0f}% less CO₂ than running now"
    )


def intensity_style(value: float, lowest: float, highest: float) -> str:
    """Color an intensity by which third of the forecast's range it falls in."""
    third = int(_fraction(value, lowest, highest) * len(INTENSITY_STYLES))
    return INTENSITY_STYLES[min(third, len(INTENSITY_STYLES) - 1)]


def render_chart(forecast: dict, response: dict) -> tuple[Text, Text, Text]:
    """Draw the forecast as one bar per hour, with the ranked windows marked underneath.

    Args:
        forecast: The API's ``/forecast`` response.
        response: The API's ``/windows`` response for the same region.

    Returns:
        Three lines: time labels every 12 hours; bars colored by intensity
        (dimmed after the deadline) followed by the intensity range; and a
        marker like ``└─1─┘`` under each window's hours.
    """
    points = forecast["points"]
    starts = [datetime.fromisoformat(point["start"]) for point in points]
    values = [point["intensity"] for point in points]
    lowest, highest = min(values), max(values)
    deadline = datetime.fromisoformat(response["job"]["deadline"])

    axis = [" "] * len(points)
    for i in range(0, len(points), AXIS_LABEL_EVERY_HOURS):
        label = _local(points[i]["start"])
        axis[i : i + len(label)] = label

    bars = Text()
    for start, value in zip(starts, values, strict=True):
        past_deadline = start + HOUR > deadline
        style = "dim" if past_deadline else intensity_style(value, lowest, highest)
        bars.append(BARS[round(_fraction(value, lowest, highest) * (len(BARS) - 1))], style=style)
    bars.append(f"  {lowest:.0f}–{highest:.0f} gCO₂/kWh", style="dim")

    column = {start: i for i, start in enumerate(starts)}
    width = response["job"]["duration_hours"]
    markers = [" "] * len(points)
    for window in response["windows"]:
        first = column.get(datetime.fromisoformat(window["start"]))
        if first is None:  # the forecast moved on since the windows were computed
            continue
        cells = ["─"] * width
        if width > 1:
            cells[0], cells[-1] = "└", "┘"
        label = str(window["rank"])
        if len(label) <= width:
            middle = (width - len(label)) // 2
            cells[middle : middle + len(label)] = label
        markers[first : first + width] = cells[: len(points) - first]

    return (
        Text("".join(axis).rstrip(), style="dim"),
        bars,
        Text("".join(markers).rstrip()),
    )


def _print_table(response: dict, forecast: dict, now: datetime) -> None:
    console = Console()
    if response["data_source"] == "synthetic":
        console.print("[yellow]Synthetic data: made-up forecasts, not real grid data.[/yellow]")
    if response["stale"]:
        console.print("[yellow]Stale forecast: the API couldn't refresh it recently.[/yellow]")
    console.print(
        f"Region {response['region']} · forecast from {_local(response['generated_at'])} · "
        f"running now: {response['baseline']['avg_intensity_g_per_kwh']:.0f} gCO₂/kWh"
    )
    console.print()
    console.print(format_headline(response, now), style="bold", highlight=False)
    console.print()
    for line in render_chart(forecast, response):
        console.print(line, no_wrap=True, overflow="crop")

    values = [point["intensity"] for point in forecast["points"]]
    lowest, highest = min(values), max(values)
    table = Table("Rank", "Start", "End", "Avg gCO₂/kWh", "CO₂ saved")
    for window in response["windows"]:
        intensity = window["avg_intensity_g_per_kwh"]
        saved = window["co2_saved_pct"]
        table.add_row(
            str(window["rank"]),
            _local(window["start"]),
            _local(window["end"]),
            Text(f"{intensity:.0f}", style=intensity_style(intensity, lowest, highest)),
            Text(f"{saved:.0f}%", style="green" if saved > 0 else "red" if saved < 0 else ""),
        )
    console.print(table)


def _fraction(value: float, lowest: float, highest: float) -> float:
    """Where ``value`` sits between ``lowest`` (0) and ``highest`` (1)."""
    return (value - lowest) / (highest - lowest) if highest > lowest else 0.0


def _local(iso_time: str) -> str:
    return datetime.fromisoformat(iso_time).astimezone().strftime(TIME_FORMAT)


def _local_span(start_iso: str, end_iso: str) -> str:
    """``Wed 17:00–19:00 PDT``, or ``Wed 23:00–Thu 02:00 PDT`` when it crosses midnight."""
    start = datetime.fromisoformat(start_iso).astimezone()
    end = datetime.fromisoformat(end_iso).astimezone()
    end_format = "%H:%M" if end.date() == start.date() else TIME_FORMAT
    return f"{start.strftime(TIME_FORMAT)}–{end.strftime(end_format)} {start.strftime('%Z')}"
