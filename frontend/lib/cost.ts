// Cost-aware ranking: what a job pays for power, with carbon priced in. The blend is one number,
// the carbon price in USD per tonne of CO₂, so cost and emissions share a unit:
//   cost ($/MWh) = price ($/MWh) + carbon price ($/t) × intensity (t/MWh)
// gCO₂/kWh equals kgCO₂/MWh, so intensity / 1000 is tonnes per MWh.

import type { ForecastPoint } from "@/lib/api/types";
import { lastStartIndex, pickWindows, savedPct } from "@/lib/carbon";
import { HOUR_MS } from "@/lib/config";

const G_PER_KWH_TO_T_PER_MWH = 1 / 1000;

/** True when every hour has a price. Without prices the planner falls back to ranking by carbon. */
export function hasPrices(points: ForecastPoint[]): boolean {
  return points.length > 0 && points.every((p) => typeof p.price === "number");
}

/** One hour's price plus its carbon cost, in USD/MWh. Treats a missing price as 0. */
export function hourlyCost(point: ForecastPoint, carbonPrice: number): number {
  return (point.price ?? 0) + carbonPrice * point.intensity * G_PER_KWH_TO_T_PER_MWH;
}

/** Dollars for a job drawing `powerMw` for `hours` at an average `costPerMwh`. */
export function jobDollars(costPerMwh: number, powerMw: number, hours: number): number {
  return costPerMwh * powerMw * hours;
}

/**
 * Dollars `job` saves compared with `baseline` (usually starting now). Negative means it costs
 * more; null without prices.
 */
export function dollarsSaved(baseline: JobStats, job: JobStats, powerMw: number, hours: number): number | null {
  if (baseline.avgCost === null || job.avgCost === null) return null;
  return jobDollars(baseline.avgCost - job.avgCost, powerMw, hours);
}

/** Averages for a job that starts at one hour and runs a whole number of hours. */
export interface JobStats {
  /** Index of the job's first forecast hour. */
  startIndex: number;
  start: string;
  end: string;
  /** Mean gCO₂/kWh. */
  avgIntensity: number;
  /** Mean wholesale price, USD/MWh; null when the forecast has no prices. */
  avgPrice: number | null;
  /** Mean price plus carbon cost, USD/MWh; null when the forecast has no prices. */
  avgCost: number | null;
}

/** A ranked start time, compared with starting now. */
export interface JobWindow extends JobStats {
  /** 1 is the best. */
  rank: number;
  /** % less CO₂ than starting now. Negative means more. */
  co2SavedPct: number;
  /** % lower blended cost than starting now; null without prices. */
  costSavedPct: number | null;
}

/**
 * Averages for a job starting at `startIndex`.
 *
 * @param carbonPrice USD per tonne of CO₂ added to each hour's price.
 */
export function jobStats(points: ForecastPoint[], startIndex: number, hours: number, carbonPrice: number): JobStats {
  if (hours < 1 || startIndex < 0 || startIndex + hours > points.length) {
    throw new RangeError(`Job of ${hours}h at hour ${startIndex} does not fit a ${points.length}h forecast`);
  }
  const span = points.slice(startIndex, startIndex + hours);
  const mean = (f: (p: ForecastPoint) => number) => span.reduce((sum, p) => sum + f(p), 0) / hours;
  const priced = hasPrices(span);
  const start = Date.parse(points[startIndex].start);
  return {
    startIndex,
    start: points[startIndex].start,
    end: new Date(start + hours * HOUR_MS).toISOString(),
    avgIntensity: mean((p) => p.intensity),
    avgPrice: priced ? mean((p) => p.price ?? 0) : null,
    avgCost: priced ? mean((p) => hourlyCost(p, carbonPrice)) : null,
  };
}

/**
 * Rank the cheapest non-overlapping start times for a job, with carbon priced in.
 *
 * Ranks by blended cost when the forecast has prices, and by carbon intensity when it doesn't
 * (an API that predates prices), so the planner still gives a useful answer.
 *
 * @param points Hourly forecast, consecutive, where index 0 is the current hour.
 * @param hours Whole hours the job runs.
 * @param deadline The job must end at or before this time.
 * @param top Maximum number of windows to return.
 * @param carbonPrice USD per tonne of CO₂; 0 ranks by price alone.
 * @returns Windows best first; empty if none fit.
 */
export function findCheapestWindows(
  points: ForecastPoint[],
  hours: number,
  deadline: Date,
  top: number,
  carbonPrice: number,
): JobWindow[] {
  const lastStart = lastStartIndex(points, hours, deadline);
  if (lastStart < 0) return [];

  const priced = hasPrices(points);
  const scores = points.map((p) => (priced ? hourlyCost(p, carbonPrice) : p.intensity));
  const baseline = jobStats(points, 0, hours, carbonPrice);

  return pickWindows(scores, hours, lastStart, top).map(({ start }, i) => {
    const stats = jobStats(points, start, hours, carbonPrice);
    return {
      ...stats,
      rank: i + 1,
      co2SavedPct: savedPct(baseline.avgIntensity, stats.avgIntensity),
      costSavedPct: baseline.avgCost === null || stats.avgCost === null ? null : savedPct(baseline.avgCost, stats.avgCost),
    };
  });
}
