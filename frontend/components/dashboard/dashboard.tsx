"use client";

import { ChartSpline, Table } from "lucide-react";
import { useState } from "react";
import { CliCommand } from "@/components/cli-command";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { getApiClient } from "@/lib/api/client";
import { SYNTHETIC_SOURCE, type ForecastPoint } from "@/lib/api/types";
import { forecastEnd, hourStart, lastStartIndex, savedPct } from "@/lib/carbon";
import { clamp } from "@/lib/chart";
import { buildCliCommand } from "@/lib/cli";
import {
  CLI_REGION,
  DEFAULT_CARBON_PRICE,
  DEFAULT_JOB_HOURS,
  DEFAULT_POWER_MW,
  DEFAULT_REGION,
  FORECAST_HORIZON_HOURS,
  HOUR_MS,
  TOP_WINDOWS,
} from "@/lib/config";
import { compareSites } from "@/lib/compare";
import { dollarsSaved, findCheapestWindows, hasPrices, hourlyCost, jobStats, type JobWindow } from "@/lib/cost";
import { formatDayTime, formatHours, formatIntensity, formatPct, formatRange, formatUsd } from "@/lib/format";
import { useMinuteClock } from "@/lib/hooks/use-clock";
import { useQuery } from "@/lib/hooks/use-query";
import { BALANCING_AUTHORITIES, findRegion, REGIONS, type BalancingAuthority } from "@/lib/regions";
import { cn } from "@/lib/utils";
import { CHART_HEIGHT, ForecastChart, type ChartSeries } from "./forecast-chart";
import { ForecastTable } from "./forecast-table";
import { NowCard } from "./now-card";
import { SiteComparison } from "./site-comparison";
import { CarbonPriceField, DeadlineField, fieldLabel, JobLengthPicker, PowerField, WindowList } from "./planner";
import { ErrorState, FreshnessBadge, SampleDataBadge, StaleBanner } from "./status";

type View = "chart" | "table";
/** What the chart plots: price plus carbon cost (what's ranked), the price alone, or carbon alone. */
type Metric = "cost" | "price" | "carbon";

/** Ignore differences under a dollar when saying another window is cheaper; it's rounding noise. */
const CHEAPER_EPSILON_USD = 1;
/** Ignore differences under this many gCO₂/kWh when saying a window is cleaner (no-price fallback). */
const CLEANER_EPSILON = 0.5;

function RegionSelect({ value, onChange }: { value: string; onChange: (code: string) => void }) {
  return (
    <label className="flex flex-col gap-2">
      <span className={fieldLabel}>Location</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-lg border border-border bg-surface px-3 text-sm font-medium text-ink"
      >
        {(Object.keys(BALANCING_AUTHORITIES) as BalancingAuthority[]).map((ba) => (
          <optgroup key={ba} label={BALANCING_AUTHORITIES[ba]}>
            {REGIONS.filter((r) => r.balancingAuthority === ba).map((r) => (
              <option key={r.code} value={r.code}>
                {r.name} · {r.city}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

/** A small segmented control. */
function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string; icon?: typeof Table }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex rounded-lg border border-border p-0.5" role="group" aria-label={label}>
      {options.map(({ value: option, label: text, icon: Icon }) => (
        <button
          key={option}
          type="button"
          aria-pressed={value === option}
          onClick={() => onChange(option)}
          className={cn(
            "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium",
            value === option ? "bg-surface-2 text-ink" : "text-muted hover:text-ink",
          )}
        >
          {Icon && <Icon className="size-3.5" aria-hidden />}
          {text}
        </button>
      ))}
    </div>
  );
}

const VIEW_OPTIONS = [
  { value: "chart" as const, label: "Chart", icon: ChartSpline },
  { value: "table" as const, label: "Table", icon: Table },
];

const METRIC_OPTIONS = [
  { value: "cost" as const, label: "Cost" },
  { value: "price" as const, label: "Price" },
  { value: "carbon" as const, label: "Carbon" },
];

function Legend({ name }: { name: string }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      <li className="flex items-center gap-1.5">
        <svg width="16" height="8" aria-hidden>
          <line x1="0" x2="16" y1="4" y2="4" stroke="var(--forecast)" strokeWidth="2" strokeLinecap="round" />
        </svg>
        {name}
      </li>
      <li className="flex items-center gap-1.5">
        <span className="size-3 rounded-sm bg-window/30" aria-hidden />
        Best windows, numbered by rank
      </li>
      <li className="flex items-center gap-1.5">
        <span className="h-3 w-5 rounded bg-window" aria-hidden />
        Your job (drag to compare)
      </li>
    </ul>
  );
}

/** The chart's series for a metric, with the other numbers for the hour in the tooltip. */
function seriesFor(metric: Metric, points: ForecastPoint[], carbonPrice: number): ChartSeries & { title: string } {
  const detail = (i: number) => {
    const p = points[i];
    return metric === "carbon" && p.price !== undefined
      ? `${formatUsd(p.price)}/MWh power`
      : `${p.price !== undefined && metric === "cost" ? `${formatUsd(p.price)} power · ` : ""}${formatIntensity(p.intensity)} gCO₂/kWh`;
  };
  if (metric === "carbon") {
    return { title: "Carbon intensity", name: "carbon intensity", unit: "gCO₂/kWh", values: points.map((p) => p.intensity), format: formatIntensity, detail };
  }
  if (metric === "price") {
    return { title: "Wholesale power price", name: "power price", unit: "$/MWh", values: points.map((p) => p.price ?? 0), format: formatUsd, detail };
  }
  return {
    title: `Cost with carbon at ${formatUsd(carbonPrice)}/t`,
    name: "cost",
    unit: "$/MWh",
    values: points.map((p) => hourlyCost(p, carbonPrice)),
    format: formatUsd,
    detail,
  };
}

function JobReadout({
  points,
  jobStart,
  durationHours,
  powerMw,
  carbonPrice,
  best,
}: {
  points: ForecastPoint[];
  jobStart: number;
  durationHours: number;
  powerMw: number;
  carbonPrice: number;
  best: JobWindow | undefined;
}) {
  const job = jobStats(points, jobStart, durationHours, carbonPrice);
  const baseline = jobStats(points, 0, durationHours, carbonPrice);
  const saved = dollarsSaved(baseline, job, powerMw, durationHours);
  const co2 = savedPct(baseline.avgIntensity, job.avgIntensity);
  const co2Text = `${formatPct(co2)} ${co2 >= 0 ? "less" : "more"} CO₂`;

  let vsNow;
  if (jobStart === 0) vsNow = "starting now";
  else if (saved === null) vsNow = `${co2Text} than starting now`;
  else vsNow = `${saved >= 0 ? `${formatUsd(saved)} less` : `${formatUsd(-saved)} more`} and ${co2Text} than starting now`;

  let missed = null;
  if (best && best.startIndex !== jobStart) {
    const extra = dollarsSaved(job, best, powerMw, durationHours);
    if (extra !== null && extra > CHEAPER_EPSILON_USD) missed = <> · the best window saves {formatUsd(extra)} more</>;
    if (extra === null && job.avgIntensity - best.avgIntensity > CLEANER_EPSILON) {
      missed = <> · the best window is {formatPct(savedPct(job.avgIntensity, best.avgIntensity))} cleaner</>;
    }
  }

  return (
    <p className="mt-3 text-sm text-ink-2" aria-live="polite" data-testid="job-readout">
      <span className="font-medium text-ink">
        Your {formatHours(durationHours)} job: {formatRange(new Date(job.start), new Date(job.end))}
      </span>{" "}
      · {job.avgCost === null ? `avg ${formatIntensity(job.avgIntensity)} gCO₂/kWh` : `${formatUsd((job.avgCost ?? 0) * powerMw * durationHours)} at ${formatUsd(job.avgPrice ?? 0)}/MWh`} ·{" "}
      {vsNow}
      {missed}
    </p>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4" aria-busy="true">
      <span className="sr-only" role="status">
        Loading forecast…
      </span>
      <div className="h-44 animate-pulse rounded-2xl bg-surface-2" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
        <div className="animate-pulse rounded-2xl bg-surface-2" style={{ height: CHART_HEIGHT + 120 }} />
        <div className="h-96 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    </div>
  );
}

/** The dashboard: location and freshness, the "right now" verdict, the forecast chart, and the job planner. */
export function Dashboard() {
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [durationHours, setDurationHours] = useState(DEFAULT_JOB_HOURS);
  const [powerMw, setPowerMw] = useState(DEFAULT_POWER_MW);
  const [carbonPrice, setCarbonPrice] = useState(DEFAULT_CARBON_PRICE);
  /** Value from the deadline input (local wall-clock time); null means the end of the forecast. */
  const [deadlineInput, setDeadlineInput] = useState<string | null>(null);
  /** Where the user has dragged the job to; null means "follow the best window". */
  const [pickedStart, setPickedStart] = useState<number | null>(null);
  const [highlightedRank, setHighlightedRank] = useState<number | null>(null);
  const [view, setView] = useState<View>("chart");
  const [metric, setMetric] = useState<Metric>("cost");
  const now = useMinuteClock();

  const forecast = useQuery({ region }, (request, signal) => getApiClient().getForecast(request.region, signal));
  const data = forecast.data;
  const points = data?.points ?? [];
  const priced = hasPrices(points);
  const end = points.length ? forecastEnd(points) : null;
  const customDeadline = deadlineInput && !Number.isNaN(Date.parse(deadlineInput)) ? new Date(deadlineInput) : null;
  const deadline = end === null ? null : (customDeadline ?? new Date(end));
  const site = findRegion(region);

  // Every site's forecast for the comparison. A site that fails (e.g. an API that doesn't cover
  // it yet) shows as unavailable instead of failing the whole table.
  const allSites = useQuery({ sites: REGIONS.map((r) => r.code) }, (request, signal) =>
    Promise.all(
      request.sites.map((code) =>
        getApiClient()
          .getForecast(code, signal)
          .then(
            (f) => ({ code, points: f.points, error: undefined }),
            (error: unknown) => {
              if (signal.aborted) throw error;
              return { code, points: undefined, error: error instanceof Error ? error.message : String(error) };
            },
          ),
      ),
    ),
  );

  function changeRegion(code: string) {
    setRegion(code);
    setPickedStart(null);
    setHighlightedRank(null);
  }

  function changeDuration(hours: number) {
    setDurationHours(hours);
    setPickedStart(null);
  }

  function changeDeadline(value: string | null) {
    setDeadlineInput(value);
    setPickedStart(null);
  }

  /** Switch to a site from the comparison, and bring its answer into view. */
  function selectSite(code: string) {
    changeRegion(code);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function changeCarbonPrice(value: number) {
    setCarbonPrice(value);
    setPickedStart(null);
  }

  let body;
  if (forecast.error) {
    body = (
      <ErrorState
        title="Couldn't load the forecast"
        message={`${forecast.error.message}. Your settings are kept; try again in a moment.`}
        onRetry={forecast.retry}
      />
    );
  } else if (!data || deadline === null || end === null) {
    body = <LoadingState />;
  } else {
    // Ranked here rather than by the API: the slider re-ranks on every move, and the forecast
    // already carries everything the ranking needs.
    const windows = findCheapestWindows(points, durationHours, deadline, TOP_WINDOWS, carbonPrice);
    const baseline = jobStats(points, 0, Math.min(durationHours, points.length), carbonPrice);
    const lastStart = lastStartIndex(points, durationHours, deadline);
    const jobStart = lastStart < 0 ? null : clamp(pickedStart ?? windows[0]?.startIndex ?? 0, 0, lastStart);
    const shown = findRegion(data.region);
    const regionName = shown?.name ?? data.region;
    const nowHours = now === null ? null : clamp((now - hourStart(points, 0)) / HOUR_MS, 0, points.length);
    const deadlineHours = clamp((deadline.getTime() - hourStart(points, 0)) / HOUR_MS, 0, points.length);
    const shownMetric = priced ? metric : "carbon";
    const series = seriesFor(shownMetric, points, carbonPrice);
    const siteOptions = allSites.data
      ? compareSites(
          allSites.data.flatMap(({ code, points: sitePoints, error }) => {
            const r = findRegion(code);
            return r ? [{ region: r, points: sitePoints, error }] : [];
          }),
          durationHours,
          deadline,
          carbonPrice,
          powerMw,
        )
      : undefined;

    body = (
      <div className={cn("space-y-4 transition-opacity", forecast.isRefetching && "opacity-60")} aria-busy={forecast.isRefetching}>
        <NowCard
          regionName={regionName}
          location={shown ? `${shown.address} · ${shown.utility}` : undefined}
          current={points[0]}
          durationHours={durationHours}
          powerMw={powerMw}
          carbonPrice={carbonPrice}
          best={windows[0]}
          baseline={baseline}
        />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
          <Card className="min-w-0">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>
                  {series.title}, next {FORECAST_HORIZON_HOURS} hours
                </CardTitle>
                <CardDescription>
                  {series.unit} · {regionName} · times in your time zone
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                {priced && view === "chart" && <Segmented label="Plot" value={metric} options={METRIC_OPTIONS} onChange={setMetric} />}
                <Segmented label="Show forecast as" value={view} options={VIEW_OPTIONS} onChange={setView} />
              </div>
            </div>
            <div className="mb-2">
              <Legend name={series.title} />
            </div>
            {view === "chart" ? (
              <ForecastChart
                points={points}
                series={series}
                windows={windows}
                durationHours={durationHours}
                jobStart={jobStart}
                lastStart={lastStart}
                deadlineHours={deadlineHours}
                nowHours={nowHours}
                highlightedRank={highlightedRank}
                onJobStartChange={setPickedStart}
                onHighlightRank={setHighlightedRank}
              />
            ) : (
              <ForecastTable points={points} windows={windows} durationHours={durationHours} carbonPrice={carbonPrice} priced={priced} />
            )}
            {jobStart !== null && (
              <JobReadout
                points={points}
                jobStart={jobStart}
                durationHours={durationHours}
                powerMw={powerMw}
                carbonPrice={carbonPrice}
                best={windows[0]}
              />
            )}
          </Card>

          <Card className="min-w-0 space-y-6">
            <section aria-labelledby="best-times">
              <CardTitle id="best-times">Best start times</CardTitle>
              <CardDescription className="mb-3">
                {formatHours(durationHours)} job{priced && <> · {powerMw} MW</>} · done by {formatDayTime(deadline)}
              </CardDescription>
              {windows.length > 0 ? (
                <WindowList
                  windows={windows}
                  baseline={baseline}
                  powerMw={powerMw}
                  durationHours={durationHours}
                  jobStart={jobStart}
                  highlightedRank={highlightedRank}
                  onHighlight={setHighlightedRank}
                  onSelect={(w) => setPickedStart(w.startIndex)}
                />
              ) : (
                <p className="rounded-xl border border-border px-3 py-3 text-sm text-ink-2">
                  No {formatHours(durationHours)} window fits before the deadline. Pick a later time or a shorter job.
                </p>
              )}
            </section>

            {site?.balancingAuthority === CLI_REGION && (
              <section aria-labelledby="cli-heading">
                <h3 id="cli-heading" className="mb-2 text-sm font-medium text-ink">
                  Carbon-only answer in your terminal
                </h3>
                <CliCommand command={buildCliCommand({ region: CLI_REGION, durationHours, deadline: customDeadline })} />
                <p className="mt-1.5 text-xs text-muted">
                  The CLI ranks the whole CAISO grid by carbon for now. Add <code className="font-mono">--json</code> for coding agents.
                </p>
              </section>
            )}
          </Card>
        </div>

        <SiteComparison
          options={siteOptions}
          error={allSites.error}
          onRetry={allSites.retry}
          current={region}
          durationHours={durationHours}
          powerMw={powerMw}
          carbonPrice={carbonPrice}
          deadline={deadline}
          onSelect={selectSite}
        />
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-4 px-4 py-6 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Compute planner</h1>
          <p className="text-sm text-muted">Find the cheapest, cleanest time and data center for a heavy job in California.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && <FreshnessBadge generatedAt={data.generated_at} stale={data.stale} now={now} />}
          {data?.data_source === SYNTHETIC_SOURCE && <SampleDataBadge />}
        </div>
      </div>

      {/* Everything the answer depends on, above the answer. */}
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <RegionSelect value={region} onChange={changeRegion} />
        <JobLengthPicker value={durationHours} onChange={changeDuration} />
        <PowerField value={powerMw} onChange={setPowerMw} />
        <CarbonPriceField value={carbonPrice} onChange={changeCarbonPrice} disabled={data !== undefined && !priced} />
        {deadline && end !== null ? (
          <DeadlineField
            value={deadline}
            forecastStart={new Date(hourStart(points, 0))}
            min={new Date(hourStart(points, 0) + durationHours * HOUR_MS)}
            max={new Date(end)}
            isCustom={customDeadline !== null}
            onChange={changeDeadline}
          />
        ) : (
          !forecast.error && <div className="h-[4.75rem] w-96 max-w-full animate-pulse rounded-lg bg-surface-2" aria-hidden />
        )}
      </div>

      {data?.stale && <StaleBanner generatedAt={data.generated_at} />}

      {body}
    </main>
  );
}
