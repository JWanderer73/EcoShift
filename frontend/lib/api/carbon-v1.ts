// Adapter from the deployed ECS API (`/v1/sites`, `/v1/forecast`, `/v1/windows`, see
// src/carbon/api/schemas.py) to the shapes the UI is built against (lib/api/types.ts).
// This file is the only place that knows the deployed contract.

import type { EcoShiftApi } from "@/lib/api/client";
import {
  ApiError,
  type ForecastResponse,
  type PriceKind,
  type PriceWindow,
  type Site,
  type WindowsRequest,
  type WindowsResponse,
} from "@/lib/api/types";
import { DEFAULT_KW, HOUR_MS, TOP_WINDOWS } from "@/lib/config";

const WAIT_CLAMPED = "wait_clamped_to_horizon";

interface V1Forecast {
  location: string;
  generated_at: string;
  data_source: string;
  stale: boolean;
  rows: { ts: string; price: number; kind?: PriceKind }[];
}

interface V1Window {
  start: string;
  end: string;
  wait_minutes: number;
  avg: number;
  cost_usd: number;
  savings_usd: number;
}

interface V1Windows {
  location: string;
  generated_at: string;
  data_source: string;
  stale: boolean;
  request: { duration_hours: number; max_delay_hours: number; kw: number };
  run_now_avg: number;
  run_now_cost_usd: number;
  best: V1Window;
  alternatives: V1Window[];
  warnings: string[];
}

interface V1Sites {
  sites: { location: string; name: string; city: string }[];
}

export function toForecast(region: string, v1: V1Forecast): ForecastResponse {
  return {
    region,
    generated_at: v1.generated_at,
    stale: v1.stale,
    data_source: v1.data_source,
    points: v1.rows.map((r) => ({ start: r.ts, price: r.price, kind: r.kind })),
  };
}

export function toSites(v1: V1Sites): Site[] {
  return v1.sites.map((s) => ({ id: s.location, name: s.name, city: s.city }));
}

export function toWindows(region: string, requestedDeadline: string, v1: V1Windows): WindowsResponse {
  const { duration_hours: hours, kw } = v1.request;
  const durationMs = hours * HOUR_MS;
  const baselineStart = Date.parse(v1.best.start) - v1.best.wait_minutes * 60_000;
  const lastStart = baselineStart + v1.request.max_delay_hours * HOUR_MS;
  const clamped = v1.warnings.includes(WAIT_CLAMPED);
  // The API reports dollars saved; the verdict is judged on $/MWh, so that is derived from the averages.
  const windows: PriceWindow[] = [v1.best, ...v1.alternatives].map((w, i) => ({
    rank: i + 1,
    start: w.start,
    end: w.end,
    avg_price_usd_per_mwh: w.avg,
    cost_usd: w.cost_usd,
    saved_usd: w.savings_usd,
    saved_usd_per_mwh: Math.round((v1.run_now_avg - w.avg) * 100) / 100,
  }));
  return {
    region,
    generated_at: v1.generated_at,
    stale: v1.stale,
    data_source: v1.data_source,
    job: {
      duration_hours: hours,
      kw,
      deadline: new Date(clamped ? lastStart + durationMs : Date.parse(requestedDeadline)).toISOString(),
      deadline_clamped: clamped,
    },
    baseline: {
      start: new Date(baselineStart).toISOString(),
      end: new Date(baselineStart + durationMs).toISOString(),
      avg_price_usd_per_mwh: v1.run_now_avg,
      cost_usd: v1.run_now_cost_usd,
    },
    windows,
  };
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("Couldn't reach the EcoShift API");
  }
  if (!response.ok) {
    let message = `EcoShift API returned ${response.status}`;
    try {
      const body = (await response.json()) as { error?: { message?: string } };
      if (body.error?.message) message = body.error.message;
    } catch {
      // keep the generic message
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

/**
 * Client for the deployed ECS API.
 *
 * @param baseUrl API origin without a trailing slash. Empty means the page's own origin, which is
 *   how it runs behind the load balancer (`/v1/*` routes to the API, everything else to the UI).
 */
export function createCarbonV1Client(baseUrl: string): EcoShiftApi {
  let sites: Promise<Site[]> | undefined;

  function loadSites(signal?: AbortSignal): Promise<Site[]> {
    sites ??= getJson<V1Sites>(`${baseUrl}/v1/sites`, signal)
      .then(toSites)
      .catch((error) => {
        sites = undefined; // try again next time instead of caching the failure
        throw error;
      });
    return sites;
  }

  /** Only campuses the API lists are passed on; anything else gets the API's default campus. */
  async function locationParam(region: string, signal?: AbortSignal): Promise<Record<string, string>> {
    if (!region) return {};
    if (region === "any") return { location: region };
    const known = await loadSites(signal).catch(() => [] as Site[]);
    return known.some((s) => s.id === region) ? { location: region } : {};
  }

  return {
    supportsAnyLocation: true,
    getSites: (signal) => loadSites(signal),
    async getForecast(region, signal) {
      const query = new URLSearchParams(await locationParam(region, signal));
      const data = await getJson<V1Forecast>(`${baseUrl}/v1/forecast?${query}`, signal);
      if (!Array.isArray(data.rows)) throw new ApiError("Forecast response doesn't match the expected shape");
      return toForecast(data.location ?? region, data);
    },
    async getWindows({ region, durationHours, kw = DEFAULT_KW, deadline, top = TOP_WINDOWS }: WindowsRequest, signal) {
      const query = new URLSearchParams({
        ...(await locationParam(region, signal)),
        duration_hours: String(durationHours),
        kw: String(kw),
        ...(deadline ? { deadline } : {}),
        top: String(Math.min(top, 5)),
      });
      const data = await getJson<V1Windows>(`${baseUrl}/v1/windows?${query}`, signal);
      if (!data.best || !Array.isArray(data.alternatives)) {
        throw new ApiError("Windows response doesn't match the expected shape");
      }
      return toWindows(data.location ?? region, deadline || data.best.end, data);
    },
  };
}
