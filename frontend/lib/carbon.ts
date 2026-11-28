// Window-finding logic. Matches the CLI's src/windows.py so the dashboard and `carbon-windows`
// rank the same forecast the same way. Prices are $/MWh and may be negative.

import type { ForecastPoint, PriceWindow } from "@/lib/api/types";
import { DEFAULT_KW, HOUR_MS, SMALL_GAIN_USD_PER_MWH, WAIT_THRESHOLD_USD_PER_MWH } from "@/lib/config";

/** Round to two decimal places, the precision the API reports. */
export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Electricity cost of running `kw` for `hours` at `pricePerMwh`: price x kWh / 1000. */
export function jobCostUsd(pricePerMwh: number, kw: number, hours: number): number {
  return (pricePerMwh * kw * hours) / 1000;
}

/**
 * Average price of a job that starts at `startIndex` and runs `hours` hours.
 *
 * @param points Hourly forecast, consecutive.
 * @param startIndex Index of the first hour the job runs.
 * @param hours Whole hours the job runs; the span must fit inside `points`.
 * @returns Mean $/MWh over the job's hours.
 */
export function averagePrice(points: ForecastPoint[], startIndex: number, hours: number): number {
  if (hours < 1 || startIndex < 0 || startIndex + hours > points.length) {
    throw new RangeError(`Job of ${hours}h at hour ${startIndex} does not fit a ${points.length}h forecast`);
  }
  let total = 0;
  for (let i = startIndex; i < startIndex + hours; i++) total += points[i].price;
  return total / hours;
}

/** $/MWh cheaper than `baseline` the job's average `price` is. Negative means dearer. */
export function savedPerMwh(baseline: number, price: number): number {
  return baseline - price;
}

/** Percent less than `baseline` that `value` is. Negative means more. */
export function savedPct(baseline: number, value: number): number {
  if (baseline <= 0) return 0;
  return ((baseline - value) / baseline) * 100;
}

/** Time the hour at `index` starts, in ms since epoch. */
export function hourStart(points: ForecastPoint[], index: number): number {
  return Date.parse(points[index].start);
}

/** End of the forecast: the end of its last hour, in ms since epoch. */
export function forecastEnd(points: ForecastPoint[]): number {
  return hourStart(points, points.length - 1) + HOUR_MS;
}

/**
 * Last hour index a job can start at and still finish by the deadline and inside the forecast.
 *
 * @returns The index, or a negative number when no start time works.
 */
export function lastStartIndex(points: ForecastPoint[], hours: number, deadline: Date): number {
  if (points.length === 0) return -1;
  const hoursUntilDeadline = Math.floor((deadline.getTime() - hourStart(points, 0)) / HOUR_MS);
  return Math.min(points.length, hoursUntilDeadline) - hours;
}

/**
 * Pick the lowest-scoring, non-overlapping job start times.
 *
 * Every start from 0 to `lastStart` is a candidate, scored by the mean of `scores` over the
 * job's hours. Candidates are taken lowest first, skipping any that overlap one already chosen,
 * so the results are genuinely different options rather than the same dip shifted by an hour.
 *
 * @param scores One value per forecast hour; lower is better.
 * @returns Up to `top` picks, best first, with their mean score.
 */
export function pickWindows(scores: number[], hours: number, lastStart: number, top: number): { start: number; avg: number }[] {
  const candidates = [];
  for (let start = 0; start <= lastStart; start++) {
    let total = 0;
    for (let i = start; i < start + hours; i++) total += scores[i];
    candidates.push({ start, avg: total / hours });
  }
  // Ties go to the earlier start: finishing sooner is the better of two equal options.
  candidates.sort((a, b) => a.avg - b.avg || a.start - b.start);

  const chosen: typeof candidates = [];
  for (const candidate of candidates) {
    if (chosen.length === top) break;
    const overlaps = chosen.some((c) => candidate.start < c.start + hours && c.start < candidate.start + hours);
    if (!overlaps) chosen.push(candidate);
  }
  return chosen;
}

/**
 * Rank the cheapest, non-overlapping start times for a job.
 *
 * Every whole-hour start that ends by the deadline is a candidate. Candidates are taken
 * cheapest first, skipping any that overlap one already chosen, so the results are
 * genuinely different options rather than the same dip shifted by an hour. Starting now
 * is a candidate like any other.
 *
 * @param points Hourly forecast, consecutive, where index 0 is the current hour.
 * @param hours Whole hours the job runs.
 * @param deadline The job must end at or before this time.
 * @param top Maximum number of windows to return.
 * @returns Windows best first, rounded to one decimal; empty if none fit.
 */
export function findBestWindows(points: ForecastPoint[], hours: number, deadline: Date, top: number, kw: number = DEFAULT_KW): PriceWindow[] {
  const lastStart = lastStartIndex(points, hours, deadline);
  if (lastStart < 0) return [];

  const baselineAvg = averagePrice(points, 0, hours);
  const chosen = pickWindows(
    points.map((p) => p.price),
    hours,
    lastStart,
    top,
  );

  return chosen.map(({ start, avg }, i) => ({
    rank: i + 1,
    start: points[start].start,
    end: new Date(hourStart(points, start) + hours * HOUR_MS).toISOString(),
    avg_price_usd_per_mwh: round2(avg),
    cost_usd: round2(jobCostUsd(avg, kw, hours)),
    saved_usd: round2(jobCostUsd(baselineAvg - avg, kw, hours)),
    saved_usd_per_mwh: round2(savedPerMwh(baselineAvg, avg)),
  }));
}

/** Index of the forecast hour starting at `time`, or -1 when it is not in the forecast. */
export function indexOfTime(points: ForecastPoint[], time: string): number {
  const target = Date.parse(time);
  return points.findIndex((p) => Date.parse(p.start) === target);
}

export type Verdict = "wait" | "small-gain" | "run-now";

/** The one-line recommendation for the "Right now" card, from how many $/MWh the best window saves. */
export function verdictFor(bestSavedUsdPerMwh: number): Verdict {
  if (bestSavedUsdPerMwh >= WAIT_THRESHOLD_USD_PER_MWH) return "wait";
  if (bestSavedUsdPerMwh >= SMALL_GAIN_USD_PER_MWH) return "small-gain";
  return "run-now";
}
