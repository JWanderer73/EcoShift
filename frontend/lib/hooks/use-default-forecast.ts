"use client";

import { getApiClient } from "@/lib/api/client";
import { forecastEnd } from "@/lib/carbon";
import { DEFAULT_JOB_HOURS, DEFAULT_REGION } from "@/lib/config";
import { useQuery } from "@/lib/hooks/use-query";

/**
 * The default region's forecast and its windows for a default-length job with no deadline.
 * The landing page's hero card and CLI demo both use it, so they show the same numbers.
 */
export function useDefaultForecast() {
  const forecast = useQuery({ region: DEFAULT_REGION }, (request, signal) => getApiClient().getForecast(request.region, signal));
  const points = forecast.data?.points;
  const windows = useQuery(
    points ? { region: DEFAULT_REGION, durationHours: DEFAULT_JOB_HOURS, deadline: new Date(forecastEnd(points)).toISOString() } : null,
    (request, signal) => getApiClient().getWindows(request, signal),
  );
  return { forecast, windows };
}
