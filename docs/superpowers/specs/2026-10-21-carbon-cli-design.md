# `carbon` CLI — Design

Date: 2026-10-21
Status: approved for implementation

## Purpose

`carbon` prints the same result as the dashboard (the top lowest-emission
time windows for a job, with % CO₂ saved vs. running now) in the terminal,
for developers and coding agents. It ships with an agent skill file telling
coding agents when to run it and how to read the result.

The backend (pipeline, API, forecasts) does not exist yet, so the CLI runs on
**synthetic forecast data** generated in code. Every output is labeled
synthetic so nobody mistakes it for a real forecast.

## Non-goals

- No real API client, auth, or network calls (added when the API exists).
- No ML, dashboard, or backend work.
- No publishing to PyPI.

## Layout

```
src/
  forecast.py   # get_forecast(region) -> Forecast (synthetic for now)
  windows.py    # pure logic: forecast + job → best windows
  cli.py        # Typer app: `carbon windows`
tests/
  test_forecast.py, test_windows.py, test_cli.py
skills/carbon-windows/SKILL.md   # agent instruction file
pyproject.toml                   # `carbon` console script, pytest config
```

`windows.py` imports nothing from `forecast.py` or `cli.py`, so the future
serving Lambda can reuse it unchanged. Swapping synthetic data for the real
API only changes `forecast.py`.

## `src/forecast.py`

- `ForecastPoint(start: datetime, intensity: float)`: one hour, gCO₂/kWh,
  covering `[start, start + 1h)`.
- `Forecast(region, generated_at, stale, data_source, points)`.
- `get_forecast(region: str, now: datetime | None = None) -> Forecast`
  returns 48 hourly points starting at the top of the current UTC hour.
  `generated_at` is that hour, `stale` is `False`, `data_source` is
  `"synthetic"`.
- Regions (EIA balancing-authority codes): `CISO` (California), `ERCO`
  (Texas), `PJM` (Mid-Atlantic). Each has a named constant profile: base
  intensity, midday solar dip, evening peak, and a fixed UTC offset used to
  place those in local time. The numbers are made up and commented as such.
- Small noise (±3%) seeded from region + hour, so the same hour always gives
  the same value.
- Unknown region raises `ValueError` naming the valid regions.

## `src/windows.py`

- `Window(start, end, avg_intensity, co2_saved_pct)`.
- `find_best_windows(points, duration_hours, deadline, top=3)
  -> tuple[Window, list[Window]]` returns `(baseline, windows)`.
  - A candidate window is `duration_hours` consecutive points starting at
    any point, ending at or before `deadline`.
  - Each is scored by its mean intensity.
  - `baseline` is the candidate starting at the first point ("run now").
  - `windows` is up to `top` non-overlapping candidates, picked greedily from
    lowest mean intensity (ties go to the earlier start). The baseline can
    appear here if it is among the best.
  - `co2_saved_pct = (baseline_avg - avg) / baseline_avg * 100`, rounded to
    one decimal.
- `ValueError` if `duration_hours < 1`, `top < 1`, or no candidate fits
  before the deadline.

## `src/cli.py`

```
carbon windows --duration 4h [--deadline 2026-10-22T09:00 | 24h]
               [--region CISO] [--top 3] [--json]
```

- `--duration` (required): `4h`, `90m`, `1h30m`, or a bare number of hours.
  Rounded up to whole hours.
- `--deadline`: ISO 8601 datetime (no timezone means the machine's local
  time) or a relative duration from now (`24h`). Default: end of forecast.
  A deadline past the forecast end is clamped to it, with a warning on
  stderr.
- `--region`: default `CISO`. `--top`: default 3, range 1–10.
- Default output: a table (Rank, Start, End, Avg gCO₂/kWh, CO₂ saved) in
  local time, under a header naming the region, forecast time, the
  "running now" intensity, and a "synthetic data" warning.
- `--json` prints only JSON to stdout (warnings stay on stderr):

```json
{
  "region": "CISO",
  "generated_at": "2026-10-21T21:00:00+00:00",
  "stale": false,
  "data_source": "synthetic",
  "job": {"duration_hours": 4, "deadline": "...", "deadline_clamped": false},
  "baseline": {"start": "...", "end": "...", "avg_intensity_g_per_kwh": 312.4},
  "windows": [
    {"rank": 1, "start": "...", "end": "...",
     "avg_intensity_g_per_kwh": 180.2, "co2_saved_pct": 42.3}
  ]
}
```

- Errors: bad `--duration`/`--deadline`/`--region`/`--top` values exit 2
  (Typer's usage error). A job that doesn't fit before the deadline exits 1
  with a message on stderr.

## Agent skill (`skills/carbon-windows/SKILL.md`)

Frontmatter `name`/`description`, then: when to run it (before deferrable
jobs over about an hour: training, batch processing, large builds), the exact
`--json` command, how to read it (use rank 1, check `stale` and
`data_source`, report % saved), and when not to (urgent or interactive work;
don't present synthetic results as real).

## Housekeeping

- `requirements.txt`: add `typer`.
- `pyproject.toml`: console script `carbon = "src.cli:app"`, and
  `pythonpath = ["."]` for pytest, so `from src...` imports keep working.
- `docs/AGENTS.md`: add `pip install -e .` and the `carbon windows` command
  to its setup and "Running things" sections, as the file's standing
  instruction requires.

## Testing

- `test_windows.py`: fits/doesn't fit, ranking, non-overlap, ties, % saved,
  baseline in results, input validation.
- `test_forecast.py`: 48 hourly points, deterministic, positive values,
  regions differ, unknown region error.
- `test_cli.py` (Typer `CliRunner`): table shows the synthetic warning,
  `--json` parses and matches the schema, duration/deadline parsing, clamp
  warning, exit codes 1 and 2.
