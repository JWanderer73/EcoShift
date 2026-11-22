// Synthetic forecasts so the UI can be built and demoed before the real API exists.
// Shapes are plausible (solar dips, evening peaks, multi-day wind swings) but the numbers are
// made up, and the UI labels them "Sample data".

import { SYNTHETIC_SOURCE, type ForecastPoint, type ForecastResponse } from "@/lib/api/types";
import { FORECAST_HORIZON_HOURS, HOUR_MS } from "@/lib/config";

/** Knobs for one daily cycle, used for both intensity (gCO₂/kWh) and price (USD/MWh). */
interface Curve {
  base: number;
  /** How far midday solar pulls the value down. */
  solarDip: number;
  /** How far the evening demand peak pushes it up. */
  eveningPeak: number;
  /** Swing from multi-day wind patterns. */
  windSwing: number;
}

/** A balancing authority's carbon: one curve shared by every site on that grid. */
interface Grid {
  /** IANA zone the grid operates in; places the solar dip and demand peak in local time. */
  timeZone: string;
  intensity: Curve;
}

// Rough characters: CAISO's deep solar dip, Sacramento's hydro, Los Angeles's gas evenings.
const GRIDS: Record<string, Grid> = {
  CISO: { timeZone: "America/Los_Angeles", intensity: { base: 270, solarDip: 160, eveningPeak: 45, windSwing: 30 } },
  BANC: { timeZone: "America/Los_Angeles", intensity: { base: 200, solarDip: 60, eveningPeak: 45, windSwing: 25 } },
  LDWP: { timeZone: "America/Los_Angeles", intensity: { base: 360, solarDip: 120, eveningPeak: 50, windSwing: 20 } },
};

/**
 * Each data center's grid (for carbon) and the price curve at its nearest pricing node (USD/MWh).
 * Bay Area nodes sit near NP15, El Segundo near SP15, San Diego at SDG&E's higher, more congested prices.
 */
const SITES: Record<string, { grid: string; price: Curve }> = {
  "coresite-sv7": { grid: "CISO", price: { base: 56, solarDip: 40, eveningPeak: 62, windSwing: 8 } },
  "equinix-sv1": { grid: "CISO", price: { base: 55, solarDip: 42, eveningPeak: 58, windSwing: 8 } },
  "he-fremont2": { grid: "CISO", price: { base: 54, solarDip: 40, eveningPeak: 60, windSwing: 9 } },
  "equinix-la4": { grid: "CISO", price: { base: 50, solarDip: 55, eveningPeak: 65, windSwing: 8 } },
  "databank-san2": { grid: "CISO", price: { base: 62, solarDip: 50, eveningPeak: 80, windSwing: 6 } },
  "ntt-ca1": { grid: "BANC", price: { base: 48, solarDip: 30, eveningPeak: 55, windSwing: 8 } },
  "coresite-la1": { grid: "LDWP", price: { base: 52, solarDip: 45, eveningPeak: 60, windSwing: 6 } },
};

/** Design doc default: the batch pipeline refreshes forecasts every 3 hours. */
const REFRESH_EVERY_HOURS = 3;
/** Minutes after each refresh slot that the pipeline finishes writing. */
const PIPELINE_RUNTIME_MIN = 6;
/** How many refreshes a stale forecast has missed. */
const STALE_MISSED_REFRESHES = 3;
/** Random hour-to-hour jitter, as a fraction of the curve's base value. */
const NOISE_FRACTION = 0.04;
const PRICE_NOISE_FRACTION = 0.06;
/** No grid in the list goes below this, even at the sunniest, windiest hour. */
const MIN_INTENSITY = 15;
/** Oversupplied hours can go negative, but not without limit. */
const MIN_PRICE = -30;

const hourFormatters = new Map<string, Intl.DateTimeFormat>();

/** Hour of day (0-23) at `time` in `timeZone`. */
function localHour(time: number, timeZone: string): number {
  let formatter = hourFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", { timeZone, hour: "numeric", hourCycle: "h23" });
    hourFormatters.set(timeZone, formatter);
  }
  return Number(formatter.formatToParts(time).find((p) => p.type === "hour")?.value ?? 0);
}

/** Deterministic pseudo-random number in [-1, 1) for a string seed (FNV-1a hash). */
function noise(seed: string): number {
  let hash = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) / 2 ** 32) * 2 - 1;
}

/** 0 at night, rising to 1 at local noon. Uses the middle of the hour. */
function solarCurve(hour: number): number {
  const h = hour + 0.5;
  if (h <= 6 || h >= 18) return 0;
  return Math.sin((Math.PI * (h - 6)) / 12) ** 1.5;
}

/** Evening demand peak around 7 PM plus a smaller morning bump around 8 AM. */
function demandCurve(hour: number): number {
  const evening = Math.exp(-((hour - 19) ** 2) / 8);
  const morning = 0.4 * Math.exp(-((hour - 8) ** 2) / 4.5);
  return evening + morning;
}

/** Wind pattern in [0, 1] with a 31-hour main cycle, so the two days of a forecast differ. Higher is windier. */
function windCurve(hoursSinceEpoch: number, code: string): number {
  const phase = (noise(`${code}:phase`) + 1) * Math.PI;
  return 0.5 + 0.35 * Math.sin((2 * Math.PI * hoursSinceEpoch) / 31 + phase) + 0.15 * Math.sin((2 * Math.PI * hoursSinceEpoch) / 11 + phase * 2);
}

/** One hour of a curve. Wind lowers both intensity and price, so the two move together but not in lockstep. */
function curveAt(curve: Curve, hour: number, wind: number, jitter: number): number {
  return curve.base - curve.solarDip * solarCurve(hour) + curve.eveningPeak * demandCurve(hour) - curve.windSwing * (wind - 0.5) * 2 + jitter;
}

/**
 * One hour at a grid, plus a price when it's a site. Carbon is seeded by grid, so every site on
 * one grid shares the same intensity, as it would with real BA-level data.
 */
function pointAt(gridCode: string, siteCode: string | null, time: number): ForecastPoint {
  const grid = GRIDS[gridCode];
  const hour = localHour(time, grid.timeZone);
  const hoursSinceEpoch = Math.floor(time / HOUR_MS);
  const wind = windCurve(hoursSinceEpoch, gridCode);
  const intensityJitter = grid.intensity.base * NOISE_FRACTION * noise(`${gridCode}:${hoursSinceEpoch}`);
  const point: ForecastPoint = {
    start: new Date(time).toISOString(),
    intensity: Math.max(MIN_INTENSITY, Math.round(curveAt(grid.intensity, hour, wind, intensityJitter))),
  };
  if (siteCode) {
    const price = SITES[siteCode].price;
    const priceJitter = price.base * PRICE_NOISE_FRACTION * noise(`${siteCode}:price:${hoursSinceEpoch}`);
    point.price = Math.max(MIN_PRICE, Math.round(curveAt(price, hour, wind, priceJitter) * 100) / 100);
  }
  return point;
}

/** Start of the hour containing `time`. */
export function startOfHour(time: number): number {
  return Math.floor(time / HOUR_MS) * HOUR_MS;
}

/** When the most recent refresh before `now` finished, missing `missed` refreshes. */
function lastRefresh(now: number, missed: number): number {
  const slot = REFRESH_EVERY_HOURS * HOUR_MS;
  let finished = Math.floor(now / slot) * slot + PIPELINE_RUNTIME_MIN * 60 * 1000;
  if (finished > now) finished -= slot;
  return finished - missed * slot;
}

/**
 * Build a sample forecast for a site (with prices) or a balancing authority (carbon only).
 *
 * @param code A site code from `REGIONS`, or a balancing-authority code like "CISO".
 * @param now Current time in ms; the forecast starts at the hour containing it.
 * @param stale Simulate a pipeline that has stopped refreshing.
 * @returns A response shaped like the real `/forecast` endpoint's. The same region and hour always
 *   give the same numbers, so reloads and tests are stable.
 */
export function generateMockForecast(code: string, now: number, stale = false): ForecastResponse {
  const site = SITES[code];
  const gridCode = site ? site.grid : code;
  if (!GRIDS[gridCode]) throw new Error(`No sample data for region ${code}`);

  const first = startOfHour(now);
  const points: ForecastPoint[] = Array.from({ length: FORECAST_HORIZON_HOURS }, (_, i) =>
    pointAt(gridCode, site ? code : null, first + i * HOUR_MS),
  );

  return {
    region: code,
    generated_at: new Date(lastRefresh(now, stale ? STALE_MISSED_REFRESHES : 0)).toISOString(),
    stale,
    data_source: SYNTHETIC_SOURCE,
    points,
  };
}
