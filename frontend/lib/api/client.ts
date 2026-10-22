import { ApiError, type ForecastResponse, type WindowsRequest, type WindowsResponse } from "@/lib/api/types";
import { averageIntensity, findBestWindows, forecastEnd, hourStart, round1 } from "@/lib/carbon";
import { API_BASE_URL, HOUR_MS, TOP_WINDOWS } from "@/lib/config";
import { generateMockForecast } from "@/lib/mock/forecast";

/** What the UI needs from the backend. Swap implementations without touching components. */
export interface EcoShiftApi {
  getForecast(region: string, signal?: AbortSignal): Promise<ForecastResponse>;
  getWindows(request: WindowsRequest, signal?: AbortSignal): Promise<WindowsResponse>;
}

/** Sample-data behaviours, picked with `?scenario=` on any page to demo or test UI states. */
export type MockScenario = "normal" | "stale" | "error" | "slow";

const MOCK_SCENARIOS: readonly MockScenario[] = ["normal", "stale", "error", "slow"];

/** Fake network delay, long enough to see loading states without slowing demos down. */
const MOCK_LATENCY_MS = 350;
const MOCK_SLOW_LATENCY_MS = 2500;

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    });
  });
}

/**
 * Client backed by generated sample data, used when no API URL is configured.
 * Builds the same response shapes the real API will return.
 *
 * @param scenario Which backend behaviour to imitate.
 */
export function createMockClient(scenario: MockScenario = "normal"): EcoShiftApi {
  const latency = scenario === "slow" ? MOCK_SLOW_LATENCY_MS : MOCK_LATENCY_MS;

  async function forecast(region: string, signal?: AbortSignal): Promise<ForecastResponse> {
    await delay(latency, signal);
    if (scenario === "error") throw new ApiError("Sample API is set to fail (?scenario=error)", 503);
    return generateMockForecast(region, Date.now(), scenario === "stale");
  }

  return {
    getForecast: forecast,
    async getWindows({ region, durationHours, deadline, top = TOP_WINDOWS }, signal) {
      const { generated_at, stale, data_source, points } = await forecast(region, signal);
      const end = forecastEnd(points);
      const requested = Date.parse(deadline);
      const clamped = requested > end;
      const effectiveDeadline = new Date(clamped ? end : requested);
      return {
        region,
        generated_at,
        stale,
        data_source,
        job: { duration_hours: durationHours, deadline: effectiveDeadline.toISOString(), deadline_clamped: clamped },
        baseline: {
          start: points[0].start,
          end: new Date(hourStart(points, 0) + durationHours * HOUR_MS).toISOString(),
          avg_intensity_g_per_kwh: round1(averageIntensity(points, 0, durationHours)),
        },
        windows: findBestWindows(points, durationHours, effectiveDeadline, top),
      };
    },
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
  if (!response.ok) throw new ApiError(`EcoShift API returned ${response.status}`, response.status);
  return (await response.json()) as T;
}

/**
 * Client for the deployed EcoShift API.
 *
 * @param baseUrl API root without a trailing slash, e.g. the API Gateway stage URL.
 */
export function createHttpClient(baseUrl: string): EcoShiftApi {
  return {
    async getForecast(region, signal) {
      const data = await getJson<ForecastResponse>(`${baseUrl}/forecast?${new URLSearchParams({ region })}`, signal);
      if (!Array.isArray(data.points)) throw new ApiError("Forecast response doesn't match the expected shape");
      return data;
    },
    async getWindows({ region, durationHours, deadline, top = TOP_WINDOWS }, signal) {
      const query = new URLSearchParams({
        region,
        duration_hours: String(durationHours),
        deadline,
        top: String(top),
      });
      const data = await getJson<WindowsResponse>(`${baseUrl}/windows?${query}`, signal);
      if (!Array.isArray(data.windows) || !data.baseline) {
        throw new ApiError("Windows response doesn't match the expected shape");
      }
      return data;
    },
  };
}

function scenarioFromUrl(): MockScenario {
  if (typeof window === "undefined") return "normal";
  const value = new URLSearchParams(window.location.search).get("scenario");
  return MOCK_SCENARIOS.find((s) => s === value) ?? "normal";
}

let client: EcoShiftApi | undefined;

/**
 * The app-wide API client: the real API when `NEXT_PUBLIC_ECOSHIFT_API_URL` is set, sample data
 * otherwise. Call it from effects or event handlers, not during render, so the sample scenario is
 * read from the browser's URL.
 */
export function getApiClient(): EcoShiftApi {
  client ??= API_BASE_URL ? createHttpClient(API_BASE_URL) : createMockClient(scenarioFromUrl());
  return client;
}
