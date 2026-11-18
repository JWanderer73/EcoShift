/** Hours of forecast the API serves (design doc: 48-hour horizon). */
export const FORECAST_HORIZON_HOURS = 48;

/** Number of windows the planner returns (design doc: "top 3 windows"). */
export const TOP_WINDOWS = 3;

/** One-tap job lengths in the planner, in hours. */
export const JOB_LENGTH_PRESETS = [1, 2, 4, 8] as const;

export const DEFAULT_JOB_HOURS = 4;
export const MIN_JOB_HOURS = 1;
/** Longest job the planner accepts: half the horizon, so there is still a choice of start times. */
export const MAX_JOB_HOURS = FORECAST_HORIZON_HOURS / 2;

/** Region shown on first load. CAISO has the clearest solar swing, which makes the demo legible. */
export const DEFAULT_REGION = "CISO";

/**
 * Verdict thresholds, as % CO₂ saved by waiting for the best window instead of running now.
 * At or above WAIT_THRESHOLD_PCT we tell people to wait; below SMALL_GAIN_THRESHOLD_PCT
 * the difference is within forecast error, so running now is fine.
 */
export const WAIT_THRESHOLD_PCT = 20;
export const SMALL_GAIN_THRESHOLD_PCT = 5;

/** Base URL of the EcoShift API. Unset means the UI runs on built-in sample data. */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_ECOSHIFT_API_URL ?? "").replace(/\/$/, "");

export const GITHUB_URL = "https://github.com/JWanderer73/EcoShift";

export const HOUR_MS = 60 * 60 * 1000;
