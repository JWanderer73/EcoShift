---
name: carbon-windows
description: Use before starting a compute-heavy job that can wait (model training, batch data processing, large builds, long test suites) and takes about an hour or more. Runs the EcoShift `carbon windows` CLI to find the lowest-emission time to run it before its deadline.
---

# Carbon-aware job timing

`carbon windows` forecasts when the electricity grid will be cleanest over
the next 48 hours, so a heavy job can run then instead of right away.

## When to use it

Use it when **both** are true:
- The job takes about an hour or more.
- It can wait: nobody is blocked on the result right now, and it only has to
  be done by some later deadline.

Don't use it for interactive work, quick commands, or anything the user needs
immediately. Never delay a job on your own; recommend a time and let the user
decide.

## How to run it

```bash
carbon windows --duration <job length> [--deadline <latest finish>] [--region <region>] --json
```

- `--duration`: estimated run time, e.g. `3h`, `90m`, `1h30m`. Rounded up
  to whole hours.
- `--deadline`: when the job must be done, as a time (`2026-10-22T09:00`,
  read as local time) or a duration from now (`24h`). Leave it out to search
  the whole 48-hour forecast.
- `--region`: the grid the job runs on: `CISO` (California, the default),
  `ERCO` (Texas), or `PJM` (Mid-Atlantic).

Always pass `--json`. The default table is for people.

If `carbon` isn't installed, ask the user before installing it with
`brew install allghelierce/ecoshift/ecoshift` (macOS or Linux) or
`pipx install git+https://github.com/JWanderer73/EcoShift.git@v0.1.0`.

## Reading the result

```json
{
  "region": "CISO",
  "generated_at": "2026-10-22T00:00:00+00:00",
  "stale": false,
  "data_source": "synthetic",
  "job": {"duration_hours": 3, "deadline": "2026-10-23T00:00:00+00:00", "deadline_clamped": false},
  "baseline": {"start": "2026-10-22T00:00:00+00:00", "end": "2026-10-22T03:00:00+00:00", "avg_intensity_g_per_kwh": 240.3},
  "windows": [
    {"rank": 1, "start": "2026-10-22T19:00:00+00:00", "end": "2026-10-22T22:00:00+00:00",
     "avg_intensity_g_per_kwh": 125.0, "co2_saved_pct": 48.0}
  ]
}
```

- `windows[0]` is the recommendation. Times are UTC; convert them to the
  user's local time when you report them.
- `co2_saved_pct` is how much less CO₂ that window emits than starting now
  (`baseline`). If it's under about 10%, waiting isn't worth it: suggest
  running now.
- `data_source: "synthetic"` means the numbers are made up for development.
  Say so, and don't present the savings as real.
- `stale: true` means the forecast hasn't refreshed recently. Mention it.
- `job.deadline_clamped: true` means the deadline was past the 48-hour
  forecast, so only the next 48 hours were searched.
- Exit code 1: the request was rejected (unknown region, or the job can't
  finish before the deadline). The reason is on stderr. Exit code 2: a bad
  option value; fix the command.

## What to tell the user

One or two lines: the recommended start time in their local time, the %
CO₂ saved, and a question about how to proceed. For example:

> The cleanest time for this 3-hour training run is 12:00–15:00 today, about
> 48% less CO₂ than starting now (synthetic data). Want to wait for that
> window, or run it now?
