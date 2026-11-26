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

/**
 * Carbon price the planner adds to the power price, in USD per tonne of CO₂. It sets the blend:
 * 0 ranks purely by price, higher values favour cleaner hours.
 */
export const DEFAULT_CARBON_PRICE = 80;
export const MAX_CARBON_PRICE = 250;
export const CARBON_PRICE_STEP = 5;
/** One-tap carbon prices with where the number comes from. */
export const CARBON_PRICE_PRESETS = [
  { value: 0, label: "Price only" },
  { value: 80, label: "EU ETS" },
  { value: 190, label: "US social cost" },
] as const;

/** Average power the job draws, in MW. Only scales the dollar totals; it doesn't change the ranking. */
export const DEFAULT_POWER_MW = 1;
export const MIN_POWER_MW = 0.1;
export const MAX_POWER_MW = 500;

/** Site shown on first load: a Santa Clara facility, in the state's biggest data-center market. */
export const DEFAULT_REGION = "coresite-sv7";

/**
 * Grid the landing page and the released carbon CLI use. The CLI ranks by carbon, which is set
 * per balancing authority, so CAISO sites map to it.
 */
export const CLI_REGION = "CISO";
export const CLI_REGION_NAME = "California";

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
