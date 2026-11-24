// Response shapes the UI expects. The deployed API's shapes (src/carbon/api/schemas.py) are mapped
// to these in lib/api/carbon-v1.ts. Field names are snake_case to match JSON on the wire.
// Prices are CAISO day-ahead LMPs in $/MWh and can be negative.

/** `data_source` value for generated sample data. Anything labeled this is not a real forecast. */
export const SYNTHETIC_SOURCE = "synthetic";

/** Whether an hour's price is already published by CAISO or is the model's estimate. */
export type PriceKind = "published" | "forecast";

/** Price for one hour, covering [start, start + 1h). */
export interface ForecastPoint {
  /** ISO 8601 timestamp at the start of the hour. */
  start: string;
  /** Day-ahead price over the hour, in $/MWh. */
  price: number;
  /** Absent for sample data and older API versions. */
  kind?: PriceKind;
}

export interface ForecastResponse {
  /** Site (datacenter campus) id. */
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

/** A datacenter campus the forecast is for. */
export interface Site {
  id: string;
  name: string;
  city?: string;
}

export interface WindowsRequest {
  region: string;
  /** Whole hours the job needs to run. */
  durationHours: number;
  /** Average power draw of the job, in kW. Sets the dollar figures. */
  kw?: number;
  /** ISO 8601 timestamp the job must finish by. */
  deadline: string;
  top?: number;
}

/** The "run it now" option every window is compared against. */
export interface Baseline {
  start: string;
  end: string;
  avg_price_usd_per_mwh: number;
  cost_usd: number;
}

/** A candidate start time for the job. */
export interface PriceWindow {
  /** 1 is the cheapest. */
  rank: number;
  start: string;
  end: string;
  avg_price_usd_per_mwh: number;
  /** Electricity cost of the job in this window. Negative means being paid to use power. */
  cost_usd: number;
  /** Dollars saved versus the baseline. Negative means worse than running now. */
  saved_usd: number;
  /** $/MWh below the baseline's average; what the verdict is judged on. */
  saved_usd_per_mwh: number;
}

export interface WindowsResponse {
  region: string;
  generated_at: string;
  stale: boolean;
  data_source: string;
  job: {
    duration_hours: number;
    kw: number;
    deadline: string;
    /** True when the requested deadline was past the forecast and got pulled in to its end. */
    deadline_clamped: boolean;
  };
  baseline: Baseline;
  /** Best first; empty when no window fits before the deadline. */
  windows: PriceWindow[];
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
