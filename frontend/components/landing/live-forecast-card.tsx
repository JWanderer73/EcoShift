"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { SampleDataBadge } from "@/components/dashboard/status";
import { Card } from "@/components/ui/card";
import { SYNTHETIC_SOURCE } from "@/lib/api/types";
import { DEFAULT_JOB_HOURS, DEFAULT_REGION, FORECAST_HORIZON_HOURS } from "@/lib/config";
import { formatHours, formatIntensity, formatPct, formatRange } from "@/lib/format";
import { useDefaultForecast } from "@/lib/hooks/use-default-forecast";
import { findRegion } from "@/lib/regions";
import { MiniForecast } from "./mini-forecast";

const regionName = findRegion(DEFAULT_REGION)?.shortName ?? DEFAULT_REGION;

/** Hero card with the current forecast for the default region, so the landing page leads with real output. */
export function LiveForecastCard() {
  const { forecast, windows } = useDefaultForecast();
  const points = forecast.data?.points;
  const best = windows.data?.windows[0];

  let content;
  if (forecast.error || windows.error) {
    content = <p className="py-16 text-center text-ink-2">The forecast is unavailable right now.</p>;
  } else if (!points || !windows.data) {
    content = <div className="h-56 animate-pulse rounded-xl bg-surface-2" aria-label="Loading forecast" role="status" />;
  } else {
    const isNowBest = best?.start === points[0].start;
    content = (
      <>
        <p className="text-2xl font-semibold tracking-tight text-balance" data-testid="hero-headline">
          {!best || isNowBest ? (
            <>Right now is the cleanest time this {FORECAST_HORIZON_HOURS}h to run a {formatHours(DEFAULT_JOB_HOURS)} job.</>
          ) : (
            <>
              {regionName}&apos;s grid will be {formatPct(best.co2_saved_pct)} cleaner{" "}
              <span className="whitespace-nowrap">{formatRange(new Date(best.start), new Date(best.end))}</span> than right now.
            </>
          )}
        </p>
        <div className="mt-5">
          <MiniForecast points={points} bestStart={best?.start} durationHours={DEFAULT_JOB_HOURS} />
          <div className="mt-1 flex justify-between text-xs text-muted">
            <span>Now</span>
            <span>+{FORECAST_HORIZON_HOURS}h</span>
          </div>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-border pt-4 text-sm">
          <div>
            <dt className="text-muted">Right now</dt>
            <dd className="font-semibold">{formatIntensity(points[0].intensity)} gCO₂/kWh</dd>
          </div>
          {best && (
            <div>
              <dt className="text-muted">Best {formatHours(DEFAULT_JOB_HOURS)} window</dt>
              <dd className="font-semibold">avg {formatIntensity(best.avg_intensity_g_per_kwh)} gCO₂/kWh</dd>
            </div>
          )}
        </dl>
      </>
    );
  }

  return (
    <Card className="shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-ink-2">
          {regionName} grid · next {FORECAST_HORIZON_HOURS} hours
        </p>
        {forecast.data?.data_source === SYNTHETIC_SOURCE && <SampleDataBadge />}
      </div>
      {content}
      <Link href="/dashboard" className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
        Plan your own job <ArrowRight className="size-4" aria-hidden />
      </Link>
    </Card>
  );
}
