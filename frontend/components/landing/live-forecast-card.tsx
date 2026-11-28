"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { SampleDataBadge } from "@/components/dashboard/status";
import { Card } from "@/components/ui/card";
import { SYNTHETIC_SOURCE } from "@/lib/api/types";
import { DEFAULT_JOB_HOURS } from "@/lib/config";
import { formatHours, formatPrice, formatRange, formatUsd } from "@/lib/format";
import { useDefaultForecast } from "@/lib/hooks/use-default-forecast";
import { useSites } from "@/lib/hooks/use-sites";
import { findSite, siteLabel } from "@/lib/regions";
import { MiniForecast } from "./mini-forecast";

/** Hero card with the current forecast for the default campus, so the landing page leads with real output. */
export function LiveForecastCard() {
  const { forecast, windows } = useDefaultForecast();
  const sites = useSites();
  const points = forecast.data?.points;
  const best = windows.data?.windows[0];
  const regionName = siteLabel(findSite(sites, forecast.data?.region ?? ""), forecast.data?.region ?? "");
  const days = points ? Math.round(points.length / 24) : 0;

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
            <>Right now is the cheapest time in the next {days} days to run a {formatHours(DEFAULT_JOB_HOURS)} job.</>
          ) : (
            <>
              Power is cheapest{" "}
              <span className="whitespace-nowrap">{formatRange(new Date(best.start), new Date(best.end))}</span>: {formatUsd(best.saved_usd)}{" "}
              less than starting now for a {formatHours(DEFAULT_JOB_HOURS)} job.
            </>
          )}
        </p>
        <div className="mt-5">
          <MiniForecast points={points} bestStart={best?.start} durationHours={DEFAULT_JOB_HOURS} />
          <div className="mt-1 flex justify-between text-xs text-muted">
            <span>Now</span>
            <span>+{points.length}h</span>
          </div>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-border pt-4 text-sm">
          <div>
            <dt className="text-muted">Right now</dt>
            <dd className="font-semibold">{formatPrice(points[0].price)}/MWh</dd>
          </div>
          {best && (
            <div>
              <dt className="text-muted">Best {formatHours(DEFAULT_JOB_HOURS)} window</dt>
              <dd className="font-semibold">{formatUsd(best.cost_usd)} · avg {formatPrice(best.avg_price_usd_per_mwh)}/MWh</dd>
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
          {regionName} · next {days} days
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
