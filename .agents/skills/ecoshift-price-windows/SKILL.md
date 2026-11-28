---
name: ecoshift-price-windows
description: Use EcoShift's electricity-price forecast to recommend when or where to run a flexible computing job and estimate its cost and savings in USD.
---

# EcoShift price windows

1. Use the EcoShift API origin provided by the user or configured for the environment. Ask for it if there is no configured endpoint. Use GET requests only.
2. Collect the job duration in whole hours, average power draw in kW, and a campus or permission to compare campuses. Ask about the latest acceptable finish time if the user has one. Use GET `/v1/sites` to resolve names to location IDs. Clarify ambiguous matches.
3. Check GET `/v1/health` and GET `/v1/windows`. Pass `duration_hours`, `kw`, and `location`. For campus comparison use `location=any` on a deployment that supports it. On older deployments, compare successful, fresh per-campus results using the same inputs. Pass either an ISO 8601 `deadline` with timezone or `max_wait` such as `3h`. Apply the same constraint to every campus.
4. Report the recommended campus and window in the user's time zone. Use `best.cost_usd`, `run_now_cost_usd`, and `best.savings_usd` for the dollar comparison at that campus. Explain that the average price is in USD/MWh and the total cost depends on duration and kW. Surface any stale forecast, pipeline failure, forecast horizon limit, or unavailable site that affects the recommendation. If the API returns `data_source: synthetic`, label the result as sample data and use it only to illustrate the calculation.

The forecast estimates wholesale energy costs. For example, an 8 kW load running for four hours at $52.59/MWh costs about $1.68. If no fresh usable forecast is available, say so and include the last successful refresh time if known.
