---
name: carbon-windows
description: Check when electricity is cheapest (CAISO day-ahead price) before starting a long, deferrable job (model training, large batch jobs, big builds, bulk data processing) and report whether waiting would cut its electricity cost. Use before launching jobs expected to run for an hour or more that do not need to finish right now.
---

# Carbon windows

Use the `carbon-windows` CLI to find the cheapest time to run a heavy job, from CAISO day-ahead prices (published for tomorrow, forecast for the next three days).

## When to use it

- Before starting a job that will run roughly an hour or longer **and** can be delayed (training runs, batch ETL, large simulations, big CI or build jobs).
- When the user asks about electricity cost or the best time to run something.

## When not to use it

- Short jobs (a few minutes), interactive work, or anything the user needs right now.
- When the deadline leaves no room to wait.

## How to use it

```bash
carbon-windows best --duration <hours> --max-wait <e.g. 6h or 1d> [--kw <average draw>] --json
```

- `--duration` is how long the job runs, in hours.
- `--max-wait` is the longest delay the user would accept. If the user has not said, ask, or use `--deadline <ISO time>` instead.
- `--location <campus id>` picks the datacenter campus (`carbon-windows sites` lists them); `--node <id>` prices at one of its five nearby nodes.
- `--kw` is the job's average power draw (default 8 kW, a single GPU box). Cost is price x kWh / 1000.

## Reading the result

The JSON has:

- `recommendation`: `"run_now"` or `"delay"`.
- `best`: `start`, `end`, `wait_minutes`, `avg` ($/MWh), `cost_usd`, `savings_usd` (versus starting now). `run_now_cost_usd` is the cost of starting now.
- `alternatives`: other windows that also beat running now.
- `savings_by_max_wait`: dollars saved for each max wait (for example 3h, 12h, 24h, 72h).
- `warnings`: read these. `forecast_stale` or `pipeline_failed` mean the forecast may be out of date.

## What to do with it

1. **Tell the user** the recommendation and the saving, for example: "Waiting 5 hours would cut this job's electricity cost by about $0.40 (from $1.28 to $0.88)." Prices can be negative; a negative window means being paid to use power.
2. **Do not delay the job on your own.** The user decides. Offer to schedule it for the suggested start time, or to run it now.
3. If `warnings` includes `forecast_stale` or `pipeline_failed`, say so and treat the advice as unreliable.
4. If the saving is small, say that waiting is not worth it. The CLI already returns `run_now` in that case.
5. Hours marked `published` are known day-ahead prices; `forecast` hours (day 2 onward) are model estimates, so say which one the window falls in.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Bad arguments |
| 3 | API unreachable (set `CARBON_API_URL`). Run the job normally and mention that the check failed. |
| 4 | Data returned, but stale or the pipeline failed. Output is still printed. |
| 5 | API error, such as an unsupported location or no forecast yet. |

Never block or fail the user's task because this check failed. It is advisory only.
