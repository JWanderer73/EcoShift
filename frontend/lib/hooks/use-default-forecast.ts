"use client";

import { getApiClient } from "@/lib/api/client";
import { forecastEnd } from "@/lib/carbon";
import { CLI_REGION, DEFAULT_JOB_HOURS } from "@/lib/config";
import { useQuery } from "@/lib/hooks/use-query";

/**
 * The CLI grid's forecast and its windows for a default-length job with no deadline.
 * The landing page's hero card and CLI demo both use it, so they show the same numbers.
 */
export function useDefaultForecast() {
  const forecast = useQuery({ region: CLI_REGION }, (request, signal) => getApiClient().getForecast(request.region, signal));
  const points = forecast.data?.points;
  const windows = useQuery(
    points ? { region: CLI_REGION, durationHours: DEFAULT_JOB_HOURS, deadline: new Date(forecastEnd(points)).toISOString() } : null,
    (request, signal) => getApiClient().getWindows(request, signal),
  );
  return { forecast, windows };
}
