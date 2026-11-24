/** Hours of forecast the sample data covers. The deployed model serves up to 5 days past what CAISO has published. */
export const FORECAST_HORIZON_HOURS = 120;

/** Number of windows the planner returns (design doc: "top 3 windows"). */
export const TOP_WINDOWS = 3;

/** One-tap job lengths in the planner, in hours. */
export const JOB_LENGTH_PRESETS = [1, 2, 4, 8] as const;

export const DEFAULT_JOB_HOURS = 4;
export const MIN_JOB_HOURS = 1;
/** Longest job the planner accepts: half the horizon, so there is still a choice of start times. */
export const MAX_JOB_HOURS = 48;

/** Average power draw assumed for a job, in kW (one GPU box). The planner lets people change it. */
export const DEFAULT_KW = 8;
export const MAX_KW = 10_000;

/** Site shown on first load. Sample data only; with the deployed API the first site it lists is used. */
export const DEFAULT_REGION = "fresno-305-west-napa-avenue";

/**
 * Verdict thresholds, as $/MWh saved by waiting for the best window instead of running now.
 * At or above WAIT_THRESHOLD_USD_PER_MWH we tell people to wait; below SMALL_GAIN_USD_PER_MWH
 * the difference is within forecast error, so running now is fine. (The API's own delay
 * threshold is CARBON_MIN_SAVINGS_USD_PER_MWH, default 5.)
 */
export const WAIT_THRESHOLD_USD_PER_MWH = 10;
export const SMALL_GAIN_USD_PER_MWH = 5;

/** Base URL of the EcoShift API. Unset means the UI runs on built-in sample data. */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_ECOSHIFT_API_URL ?? "").replace(/\/$/, "");

/**
 * Which backend the UI talks to when `NEXT_PUBLIC_ECOSHIFT_API_MODE=carbon-v1`: the deployed
 * ECS API (`/v1/forecast`, `/v1/windows`), reached on the page's own origin through the load
 * balancer. Unset means the original contract above, or sample data when no URL is set.
 */
export const API_MODE = process.env.NEXT_PUBLIC_ECOSHIFT_API_MODE ?? "";


export const GITHUB_URL = "https://github.com/JWanderer73/EcoShift";

export const HOUR_MS = 60 * 60 * 1000;
