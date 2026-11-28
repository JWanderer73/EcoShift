// "Where and when": the same job's best window at every California site, cheapest first.

import type { ForecastPoint, Site } from "@/lib/api/types";
import { findCheapestWindows, jobDollars, type JobWindow } from "@/lib/cost";

/** Something to compare: a data center campus, identified by the code the API takes. */
export interface Place {
  code: string;
  /** Short label for tight spaces. */
  shortName: string;
  city?: string;
}

/** A campus from the API as a `Place`. */
export function placeFromSite(site: Site): Place {
  return { code: site.id, shortName: site.city ? `${site.city}, ${site.name}` : site.name, city: site.city };
}

/** Cities to show first when comparing: the main data center hubs. */
const HUB_CITIES = ["Santa Clara", "San Jose", "Fremont", "El Segundo", "Los Angeles", "San Diego", "Sacramento", "Fresno"];

/**
 * Campuses to compare: the one on screen, then one campus from each hub city, then other cities,
 * at most `max` in all. Comparing all 200+ campuses would mean 200+ requests.
 */
export function pickComparisonSites(sites: Site[], currentId: string, max = 8): Site[] {
  const chosen: Site[] = [];
  const cities = new Set<string>();
  const add = (site: Site | undefined) => {
    if (!site || chosen.length >= max || chosen.some((c) => c.id === site.id)) return;
    chosen.push(site);
    cities.add(site.city ?? site.id);
  };
  add(sites.find((s) => s.id === currentId));
  for (const city of [...HUB_CITIES, ...sites.map((s) => s.city ?? "")]) {
    if (cities.has(city)) continue;
    add(sites.find((s) => s.city === city));
  }
  return chosen;
}

/** One site's forecast, or why it couldn't be loaded. */
export interface SiteForecast {
  region: Place;
  points?: ForecastPoint[];
  error?: string;
}

/** A site's best option for the job. */
export interface SiteOption {
  region: Place;
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
