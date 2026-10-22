// Response shapes the UI expects from the EcoShift API. They mirror the `carbon windows --json`
// output in docs/superpowers/specs/2026-10-21-carbon-cli-design.md, so the dashboard and the CLI
// share one contract. Field names are snake_case to match the JSON on the wire.

/** `data_source` value for generated sample data. Anything labeled this is not a real forecast. */
export const SYNTHETIC_SOURCE = "synthetic";

/** Forecast carbon intensity for one hour, covering [start, start + 1h). */
export interface ForecastPoint {
  /** ISO 8601 timestamp at the start of the hour. */
  start: string;
  /** Average grid carbon intensity over the hour, in gCO₂/kWh. */
  intensity: number;
}

export interface ForecastResponse {
  region: string;
  /** When the batch pipeline produced this forecast. */
  generated_at: string;
  /** True when the pipeline has missed refreshes and the API is serving the last good forecast. */
  stale: boolean;
  /** Where the numbers came from; `SYNTHETIC_SOURCE` for sample data. */
  data_source: string;
  /** Hourly points, consecutive, starting at the current hour. */
  points: ForecastPoint[];
}

export interface WindowsRequest {
  region: string;
  /** Whole hours the job needs to run. */
  durationHours: number;
  /** ISO 8601 timestamp the job must finish by. */
  deadline: string;
  top?: number;
}

/** The "run it now" option every window is compared against. */
export interface Baseline {
  start: string;
  end: string;
  avg_intensity_g_per_kwh: number;
}

/** A candidate start time for the job. */
export interface CarbonWindow {
  /** 1 is the cleanest. */
  rank: number;
  start: string;
  end: string;
  avg_intensity_g_per_kwh: number;
  /** % less CO₂ than the baseline. Negative means worse than running now. */
  co2_saved_pct: number;
}

export interface WindowsResponse {
  region: string;
  generated_at: string;
  stale: boolean;
  data_source: string;
  job: {
    duration_hours: number;
    deadline: string;
    /** True when the requested deadline was past the forecast and got pulled in to its end. */
    deadline_clamped: boolean;
  };
  baseline: Baseline;
  /** Best first; empty when no window fits before the deadline. */
  windows: CarbonWindow[];
}

/** Error thrown by API clients, carrying the HTTP status when there is one. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
