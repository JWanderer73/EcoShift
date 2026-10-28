# `carbon` CLI — Design

Date: 2026-10-21
Status: approved for implementation

## Purpose

`carbon` prints the same result as the dashboard (the top lowest-emission
time windows for a job, with % CO₂ saved vs. running now) in the terminal,
for developers and coding agents. It ships with an agent skill file telling
coding agents when to run it and how to read the result.

```
you → carbon windows --duration 2h → API → "best: 2–4am, saves 31% CO₂"
```

The CLI only sends the job (length, deadline, region) to the API and prints
what comes back. The backend (pipeline, API, forecasts) does not exist yet,
so for now the "API" is a local stand-in (`src/api.py`) that returns the same
JSON response the real one will, computed from **synthetic forecast data**
generated in code. Every output is labeled synthetic so nobody mistakes it
for a real forecast.

## Non-goals

- No real API client, auth, or network calls (added when the API exists).
- No ML, dashboard, or backend work.
- No publishing to PyPI.

## Layout

```
src/
  forecast.py   # get_forecast(region) -> Forecast (synthetic for now)
  windows.py    # pure logic: forecast + job → best windows
  api.py        # get_windows(job), get_forecast(region) -> API response dicts (local stand-in)
  cli.py        # Typer app: `carbon windows`, talks only to api.py
tests/
  test_forecast.py, test_windows.py, test_api.py, test_cli.py
skills/carbon-windows/SKILL.md   # agent instruction file
pyproject.toml                   # `carbon` console script, pytest config
```

Dependencies point one way: `cli.py → api.py → forecast.py + windows.py`.
`windows.py` imports nothing from the others, so the future serving Lambda
can reuse it unchanged. When the real API exists, only `api.py` changes (to
an HTTP call) and `cli.py` stays the same.

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

## `src/api.py`

The API boundary, shaped like the real serving Lambda.

- `get_windows(duration_hours, deadline, region="CISO", top=3, now=None)
  -> dict` returns the JSON response shown under `src/cli.py`.
- Gets the forecast, clamps a deadline past the forecast end to that end
  (setting `deadline_clamped`), runs `find_best_windows`, and serializes
  times as ISO 8601 UTC.
- Raises `ApiError` for an unknown region or a job that doesn't fit before
  the deadline, with a message the CLI can print as is.
- `get_forecast(region="CISO", now=None) -> dict` returns the dashboard's
  `/forecast` response (`region`, `generated_at`, `stale`, `data_source`,
  and hourly `points` of `start` and `intensity`). The table output uses it
  to draw its chart.

## `src/cli.py`

```
carbon windows --duration 4h [--deadline 2026-10-22T09:00 | 24h]
               [--region CISO] [--top 3] [--json]
```

- `--duration` (required): `4h`, `90m`, `1h30m`, or a bare number of hours.
  Rounded up to whole hours.
- `--deadline`: ISO 8601 datetime (no timezone means the machine's local
  time) or a relative duration from now (`24h`). Default: end of forecast.
  If the response says `deadline_clamped`, a warning goes to stderr.
- `--region`: default `CISO`. `--top`: default 3, range 1–10.
- The CLI parses its options, calls `api.get_windows`, and renders the
  response. It does no window math itself.
- Default output, in local time:
  - a header naming the region, forecast time, the "running now"
    intensity, and a "synthetic data" warning;
  - a headline with the best window, how soon it starts, and % CO₂ saved
    (or "run now" when nothing before the deadline is cleaner);
  - a 48-hour chart, one bar per hour colored green, yellow or red by which
    third of the forecast's range it falls in, dimmed after the deadline,
    with each ranked window bracketed underneath (`└─1─┘`);
  - a table (Rank, Start, End, Avg gCO₂/kWh, CO₂ saved), with the same
    intensity colors and the saved % in green (or red when negative).
- `--json` prints the API response as is, and only that, to stdout
  (warnings stay on stderr):

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

- Errors: unparseable `--duration`/`--deadline` or out-of-range `--top`
  exit 2 (Typer's usage error). An `ApiError` (unknown region, job doesn't
  fit before the deadline) exits 1 with its message on stderr.

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
- `test_api.py`: response matches the schema, clamping sets
  `deadline_clamped`, `ApiError` for unknown region and a job that doesn't
  fit.
- `test_cli.py` (Typer `CliRunner`): table shows the synthetic warning,
  `--json` output equals the API response, duration/deadline parsing, clamp
  warning, exit codes 1 and 2.
