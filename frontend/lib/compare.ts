// "Where and when": the same job's best window at every California site, cheapest first.

import type { ForecastPoint } from "@/lib/api/types";
import { findCheapestWindows, jobDollars, type JobWindow } from "@/lib/cost";
import type { Region } from "@/lib/regions";

/** One site's forecast, or why it couldn't be loaded. */
export interface SiteForecast {
  region: Region;
  points?: ForecastPoint[];
  error?: string;
}

/** A site's best option for the job. */
export interface SiteOption {
  region: Region;
  /** Best window at this site; null when none fits the deadline or the forecast failed. */
  best: JobWindow | null;
  /** What the job costs in that window, carbon included, in USD; null without prices. */
  dollars: number | null;
  error?: string;
}

/** Sort order: priced options by cost, then unpriced by carbon, then sites with no window, then failures. */
function tier(option: SiteOption): number {
  if (option.error) return 3;
  if (!option.best) return 2;
  return option.dollars === null ? 1 : 0;
}

/**
 * Rank sites by their best window for one job.
 *
 * @param sites Each site's forecast. Every forecast should start at the same hour.
 * @param hours Whole hours the job runs.
 * @param deadline The job must end at or before this time, at every site.
 * @param carbonPrice USD per tonne of CO₂ added to each hour's price.
 * @param powerMw Average power the job draws.
 * @returns One option per site, best first.
 */
export function compareSites(sites: SiteForecast[], hours: number, deadline: Date, carbonPrice: number, powerMw: number): SiteOption[] {
  const options = sites.map(({ region, points, error }): SiteOption => {
    if (!points || error) return { region, best: null, dollars: null, error: error ?? "No forecast" };
    const [best = null] = findCheapestWindows(points, hours, deadline, 1, carbonPrice);
    return { region, best, dollars: best?.avgCost == null ? null : jobDollars(best.avgCost, powerMw, hours) };
  });
  return options.sort(
    (a, b) =>
      tier(a) - tier(b) ||
      (a.dollars ?? 0) - (b.dollars ?? 0) ||
      (a.best?.avgIntensity ?? 0) - (b.best?.avgIntensity ?? 0) ||
      (a.best?.startIndex ?? 0) - (b.best?.startIndex ?? 0),
  );
}
