---
name: carbon-windows
description: Check when the electricity grid is cleanest before starting a long, deferrable job (model training, large batch jobs, big builds, bulk data processing) and report whether waiting would cut its carbon footprint. Use before launching jobs expected to run for an hour or more that do not need to finish right now.
---

# Carbon windows

Use the `carbon-windows` CLI to find the lowest-emission time to run a heavy job.

## When to use it

- Before starting a job that will run roughly an hour or longer **and** can be delayed (training runs, batch ETL, large simulations, big CI or build jobs).
- When the user asks about the carbon footprint or the best time to run something.

## When not to use it

- Short jobs (a few minutes), interactive work, or anything the user needs right now.
- When the deadline leaves no room to wait.

## How to use it

```bash
carbon-windows best --duration <hours> --max-wait <e.g. 6h or 1d> --json
```

- `--duration` is how long the job runs, in hours.
- `--max-wait` is the longest delay the user would accept. If the user has not said, ask, or use `--deadline <ISO time>` instead.
- Add `--location <id>` if the user is not in the default location.

## Reading the result

The JSON has:

- `recommendation`: `"run_now"` or `"delay"`.
- `best`: `start`, `end`, `wait_minutes`, `avg` (intensity), `savings_pct` (versus starting now).
- `alternatives`: other windows that also beat running now.
- `savings_by_max_wait`: how much extra waiting buys (for example 3h, 12h, 24h).
- `warnings`: read these. `forecast_stale` or `pipeline_failed` mean the forecast may be out of date.

## What to do with it

1. **Tell the user** the recommendation and the saving, for example: "Waiting 5 hours would cut this job's emissions by about 18%."
2. **Do not delay the job on your own.** The user decides. Offer to schedule it for the suggested start time, or to run it now.
3. If `warnings` includes `forecast_stale` or `pipeline_failed`, say so and treat the advice as unreliable.
4. If `savings_pct` is small, say that waiting is not worth it. The CLI already returns `run_now` in that case.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Bad arguments |
| 3 | API unreachable (set `CARBON_API_URL`). Run the job normally and mention that the check failed. |
| 4 | Data returned, but stale or the pipeline failed. Output is still printed. |
| 5 | API error, such as an unsupported location or no forecast yet. |

Never block or fail the user's task because this check failed. It is advisory only.
