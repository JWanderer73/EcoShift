// Window-finding logic. Matches the CLI's src/windows.py so the dashboard and `carbon windows`
// rank the same forecast the same way.

import type { CarbonWindow, ForecastPoint } from "@/lib/api/types";
import { HOUR_MS, SMALL_GAIN_THRESHOLD_PCT, WAIT_THRESHOLD_PCT } from "@/lib/config";

/** Round to one decimal place, the precision the API and CLI report. */
export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/**
 * Average intensity of a job that starts at `startIndex` and runs `hours` hours.
 *
 * @param points Hourly forecast, consecutive.
 * @param startIndex Index of the first hour the job runs.
 * @param hours Whole hours the job runs; the span must fit inside `points`.
 * @returns Mean gCO₂/kWh over the job's hours.
 */
export function averageIntensity(points: ForecastPoint[], startIndex: number, hours: number): number {
  if (hours < 1 || startIndex < 0 || startIndex + hours > points.length) {
    throw new RangeError(`Job of ${hours}h at hour ${startIndex} does not fit a ${points.length}h forecast`);
  }
  let total = 0;
  for (let i = startIndex; i < startIndex + hours; i++) total += points[i].intensity;
  return total / hours;
}

/**
 * Percent less CO₂ a job emits at `intensity` compared with `baseline`. Negative means more.
 * Intensity is per kWh, so for the same job the CO₂ ratio equals the intensity ratio.
 */
export function savedPct(baseline: number, intensity: number): number {
  if (baseline <= 0) return 0;
  return ((baseline - intensity) / baseline) * 100;
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
 * Rank the lowest-emission, non-overlapping start times for a job.
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
export function findBestWindows(points: ForecastPoint[], hours: number, deadline: Date, top: number): CarbonWindow[] {
  const lastStart = lastStartIndex(points, hours, deadline);
  if (lastStart < 0) return [];

  const baselineAvg = averageIntensity(points, 0, hours);
  const candidates = [];
  for (let start = 0; start <= lastStart; start++) {
    candidates.push({ start, avg: averageIntensity(points, start, hours) });
  }
  // Ties go to the earlier start: finishing sooner is the better of two equal options.
  candidates.sort((a, b) => a.avg - b.avg || a.start - b.start);

  const chosen: typeof candidates = [];
  for (const candidate of candidates) {
    if (chosen.length === top) break;
    const overlaps = chosen.some((c) => candidate.start < c.start + hours && c.start < candidate.start + hours);
    if (!overlaps) chosen.push(candidate);
  }

  return chosen.map(({ start, avg }, i) => ({
    rank: i + 1,
    start: points[start].start,
    end: new Date(hourStart(points, start) + hours * HOUR_MS).toISOString(),
    avg_intensity_g_per_kwh: round1(avg),
    co2_saved_pct: round1(savedPct(baselineAvg, avg)),
  }));
}

/** Index of the forecast hour starting at `time`, or -1 when it is not in the forecast. */
export function indexOfTime(points: ForecastPoint[], time: string): number {
  const target = Date.parse(time);
  return points.findIndex((p) => Date.parse(p.start) === target);
}

export type Verdict = "wait" | "small-gain" | "run-now";

/** The one-line recommendation for the "Right now" card, from the best window's savings. */
export function verdictFor(bestSavedPct: number): Verdict {
  if (bestSavedPct >= WAIT_THRESHOLD_PCT) return "wait";
  if (bestSavedPct >= SMALL_GAIN_THRESHOLD_PCT) return "small-gain";
  return "run-now";
}
