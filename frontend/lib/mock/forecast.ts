// Synthetic forecasts so the UI can be built and demoed before the real API exists.
// Shapes are plausible (solar dips, evening peaks, multi-day wind swings) but the numbers are
// made up, and the UI labels them "Sample data".

import { SYNTHETIC_SOURCE, type ForecastPoint, type ForecastResponse } from "@/lib/api/types";
import { FORECAST_HORIZON_HOURS, HOUR_MS } from "@/lib/config";

/** Knobs for one region's daily cycle. Intensities in gCO₂/kWh. */
interface Profile {
  /** IANA zone the grid operates in; places the solar dip and demand peak in local time. */
  timeZone: string;
  base: number;
  /** How far midday solar pulls intensity down. */
  solarDip: number;
  /** How far the evening demand peak pushes it up. */
  eveningPeak: number;
  /** Swing from multi-day wind patterns. */
  windSwing: number;
}

const PROFILES: Record<string, Profile> = {
  CISO: { timeZone: "America/Los_Angeles", base: 270, solarDip: 160, eveningPeak: 45, windSwing: 30 },
  ERCO: { timeZone: "America/Chicago", base: 400, solarDip: 90, eveningPeak: 40, windSwing: 110 },
  PJM: { timeZone: "America/New_York", base: 390, solarDip: 30, eveningPeak: 35, windSwing: 30 },
};

/** Design doc default: the batch pipeline refreshes forecasts every 3 hours. */
const REFRESH_EVERY_HOURS = 3;
/** Minutes after each refresh slot that the pipeline finishes writing. */
const PIPELINE_RUNTIME_MIN = 6;
/** How many refreshes a stale forecast has missed. */
const STALE_MISSED_REFRESHES = 3;
/** Random hour-to-hour jitter, as a fraction of the region's base intensity. */
const NOISE_FRACTION = 0.04;
/** No grid in the list goes below this, even at the sunniest, windiest hour. */
const MIN_INTENSITY = 15;

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

function intensityAt(code: string, profile: Profile, time: number): number {
  const hour = localHour(time, profile.timeZone);
  const hoursSinceEpoch = Math.floor(time / HOUR_MS);
  const value =
    profile.base -
    profile.solarDip * solarCurve(hour) +
    profile.eveningPeak * demandCurve(hour) -
    profile.windSwing * (windCurve(hoursSinceEpoch, code) - 0.5) * 2 +
    profile.base * NOISE_FRACTION * noise(`${code}:${hoursSinceEpoch}`);
  return Math.max(MIN_INTENSITY, Math.round(value));
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
 * Build a sample forecast for a region.
 *
 * @param code EIA region code from `REGIONS`.
 * @param now Current time in ms; the forecast starts at the hour containing it.
 * @param stale Simulate a pipeline that has stopped refreshing.
 * @returns A response shaped like the real `/forecast` endpoint's. The same region and hour always
 *   give the same numbers, so reloads and tests are stable.
 */
export function generateMockForecast(code: string, now: number, stale = false): ForecastResponse {
  const profile = PROFILES[code];
  if (!profile) throw new Error(`No sample data for region ${code}`);

  const first = startOfHour(now);
  const points: ForecastPoint[] = Array.from({ length: FORECAST_HORIZON_HOURS }, (_, i) => {
    const time = first + i * HOUR_MS;
    return { start: new Date(time).toISOString(), intensity: intensityAt(code, profile, time) };
  });

  return {
    region: code,
    generated_at: new Date(lastRefresh(now, stale ? STALE_MISSED_REFRESHES : 0)).toISOString(),
    stale,
    data_source: SYNTHETIC_SOURCE,
    points,
  };
}
