"use client";

import { ChartSpline, Table } from "lucide-react";
import { useMemo, useState } from "react";
import { CliCommand } from "@/components/cli-command";
import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { getApiClient } from "@/lib/api/client";
import { SYNTHETIC_SOURCE, type ForecastPoint, type Site } from "@/lib/api/types";
import { averagePrice, findBestWindows, forecastEnd, hourStart, indexOfTime, jobCostUsd, lastStartIndex, savedPerMwh } from "@/lib/carbon";
import { clamp } from "@/lib/chart";
import { compareSites, pickComparisonSites, placeFromSite, type SiteForecast } from "@/lib/compare";
import { buildCliCommand } from "@/lib/cli";
import { DEFAULT_JOB_HOURS, DEFAULT_KW, DEFAULT_REGION, HOUR_MS } from "@/lib/config";
import { formatDayTime, formatHours, formatPrice, formatRange, formatUsd } from "@/lib/format";
import { useMinuteClock } from "@/lib/hooks/use-clock";
import { useQuery } from "@/lib/hooks/use-query";
import { useSites } from "@/lib/hooks/use-sites";
import { findSite, siteLabel } from "@/lib/regions";
import { cn } from "@/lib/utils";
import { CHART_HEIGHT, ForecastChart } from "./forecast-chart";
import { ForecastTable } from "./forecast-table";
import { NowCard } from "./now-card";
import { SiteComparison } from "./site-comparison";
import { DeadlineField, fieldLabel, JobLengthPicker, PowerField, WindowList } from "./planner";
import { ErrorState, FreshnessBadge, SampleDataBadge, StaleBanner } from "./status";

type View = "chart" | "table";

/** Ignore differences under this many $/MWh when saying a window is cheaper; it's rounding noise. */
const CHEAPER_EPSILON = 0.5;

function SiteSelect({ sites, value, onChange }: { sites: Site[]; value: string; onChange: (id: string) => void }) {
  return (
    <label className="flex flex-col gap-2">
      <span className={fieldLabel}>Datacenter campus</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 max-w-72 rounded-lg border border-border bg-surface px-3 text-sm font-medium text-ink"
      >
        {sites.length === 0 && <option value={value}>Loading…</option>}
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {siteLabel(s, s.id)}
          </option>
        ))}
      </select>
    </label>
  );
}

function ViewToggle({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  const options = [
    { value: "chart" as const, label: "Chart", icon: ChartSpline },
    { value: "table" as const, label: "Table", icon: Table },
  ];
  return (
    <div className="flex rounded-lg border border-border p-0.5" role="group" aria-label="Show forecast as">
      {options.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={view === value}
          onClick={() => onChange(value)}
          className={cn(
            "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium",
            view === value ? "bg-surface-2 text-ink" : "text-muted hover:text-ink",
          )}
        >
          <Icon className="size-3.5" aria-hidden />
          {label}
        </button>
      ))}
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      <li className="flex items-center gap-1.5">
        <svg width="16" height="8" aria-hidden>
          <line x1="0" x2="16" y1="4" y2="4" stroke="var(--forecast)" strokeWidth="2" strokeLinecap="round" />
        </svg>
        Price ($/MWh)
      </li>
      <li className="flex items-center gap-1.5">
        <span className="size-3 rounded-sm bg-window/30" aria-hidden />
        Cheapest windows, numbered by rank
      </li>
      <li className="flex items-center gap-1.5">
        <span className="h-3 w-5 rounded bg-window" aria-hidden />
        Your job (drag to compare)
      </li>
    </ul>
  );
}

function JobReadout({
  points,
  jobStart,
  durationHours,
  kw,
  bestAvg,
}: {
  points: ForecastPoint[];
  jobStart: number;
  durationHours: number;
  kw: number;
  bestAvg: number | null;
}) {
  const start = hourStart(points, jobStart);
  const avg = averagePrice(points, jobStart, durationHours);
  const nowAvg = averagePrice(points, 0, durationHours);
  const savedNow = jobCostUsd(savedPerMwh(nowAvg, avg), kw, durationHours);
  const vsNowText =
    jobStart === 0 ? "starting now" : savedNow >= 0 ? `${formatUsd(savedNow)} cheaper than starting now` : `${formatUsd(-savedNow)} dearer than starting now`;
  const missedUsd = bestAvg !== null && avg - bestAvg > CHEAPER_EPSILON ? jobCostUsd(avg - bestAvg, kw, durationHours) : null;

  return (
    <p className="mt-3 text-sm text-ink-2" aria-live="polite" data-testid="job-readout">
      <span className="font-medium text-ink">
        Your {formatHours(durationHours)} job: {formatRange(new Date(start), new Date(start + durationHours * HOUR_MS))}
      </span>{" "}
      · {formatUsd(jobCostUsd(avg, kw, durationHours))} (avg {formatPrice(avg)}/MWh) · {vsNowText}
      {missedUsd !== null && <> · the best window is {formatUsd(missedUsd)} cheaper</>}
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

/** Best window for the same job at a handful of campuses, so people can choose where as well as when. */
function ComparePanel({
  sites,
  region,
  durationHours,
  kw,
  deadline,
  onSelect,
}: {
  sites: Site[];
  region: string;
  durationHours: number;
  kw: number;
  deadline: Date;
  onSelect: (id: string) => void;
}) {
  const picks = useMemo(() => pickComparisonSites(sites, region), [sites, region]);
  const forecasts = useQuery(picks.length > 0 ? { ids: picks.map((s) => s.id) } : null, async (request, signal) =>
    Promise.all(
      request.ids.map(async (id): Promise<{ id: string; points?: ForecastPoint[]; error?: string }> => {
        try {
          return { id, points: (await getApiClient().getForecast(id, signal)).points };
        } catch (error) {
          if (signal.aborted) throw error;
          return { id, error: error instanceof Error ? error.message : "Couldn't load the forecast" };
        }
      }),
    ),
  );
  const options = useMemo(() => {
    if (!forecasts.data) return undefined;
    const byId = new Map(forecasts.data.map((f) => [f.id, f]));
    const entries: SiteForecast[] = picks.flatMap((site) => {
      const f = byId.get(site.id);
      return f ? [{ region: placeFromSite(site), points: f.points, error: f.error }] : [];
    });
    return compareSites(entries, durationHours, deadline, 0, kw / 1000);
  }, [forecasts.data, picks, durationHours, deadline, kw]);

  return (
    <SiteComparison
      options={options}
      error={forecasts.error}
      onRetry={forecasts.retry}
      current={region}
      durationHours={durationHours}
      kw={kw}
      deadline={deadline}
      onSelect={onSelect}
    />
  );
}

/** The dashboard: campus and freshness, the "right now" verdict, the forecast chart, and the job planner. */
export function Dashboard() {
  const sites = useSites();
  const [pickedRegion, setRegion] = useState(DEFAULT_REGION);
  // With the deployed API the sample default isn't a real campus, so use the first one it lists.
  const region = sites.length > 0 && !findSite(sites, pickedRegion) ? sites[0].id : pickedRegion;
  const [durationHours, setDurationHours] = useState(DEFAULT_JOB_HOURS);
  const [kw, setKw] = useState(DEFAULT_KW);
  /** Value from the deadline input (local wall-clock time); null means the end of the forecast. */
  const [deadlineInput, setDeadlineInput] = useState<string | null>(null);
  /** Where the user has dragged the job to; null means "follow the best window". */
  const [pickedStart, setPickedStart] = useState<number | null>(null);
  const [highlightedRank, setHighlightedRank] = useState<number | null>(null);
  const [view, setView] = useState<View>("chart");
  const now = useMinuteClock();

  const forecast = useQuery({ region }, (request, signal) => getApiClient().getForecast(request.region, signal));
  const data = forecast.data;
  const points = data?.points ?? [];
  const end = points.length ? forecastEnd(points) : null;
  const customDeadline = deadlineInput && !Number.isNaN(Date.parse(deadlineInput)) ? new Date(deadlineInput) : null;
  const deadline = end === null ? null : (customDeadline ?? new Date(end));

  const windowsQuery = useQuery(
    data?.region === region && deadline ? { region, durationHours, kw, deadline: deadline.toISOString() } : null,
    (request, signal) => getApiClient().getWindows(request, signal),
  );
  const windowsData = windowsQuery.data;
  // Only trust windows computed for what's on screen; older ones stay listed (dimmed) but off the chart.
  const windowsMatch = windowsData?.region === region && windowsData.job.duration_hours === durationHours && windowsData.job.kw === kw;
  const windows = windowsMatch ? windowsData.windows : [];

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
    const lastStart = lastStartIndex(points, durationHours, deadline);
    // Place the job on the API's best window; before that arrives, on the same calculation done locally.
    const best = windows[0] ?? findBestWindows(points, durationHours, deadline, 1, kw)[0];
    const defaultStart = best ? Math.max(indexOfTime(points, best.start), 0) : 0;
    const jobStart = lastStart < 0 ? null : clamp(pickedStart ?? defaultStart, 0, lastStart);
    const current = points[0];
    const regionName = siteLabel(findSite(sites, data.region), data.region);
    const firstHour = current.start;
    const nowHours = now === null ? null : clamp((now - hourStart(points, 0)) / HOUR_MS, 0, points.length);
    const deadlineHours = clamp((deadline.getTime() - hourStart(points, 0)) / HOUR_MS, 0, points.length);
    const refetching = forecast.isRefetching || windowsQuery.isRefetching;

    body = (
      <div className={cn("space-y-4 transition-opacity", refetching && "opacity-60")} aria-busy={refetching}>
        <NowCard
          regionName={regionName}
          current={current}
          durationHours={durationHours}
          best={windowsMatch ? windows[0] : undefined}
          baseline={windowsMatch ? windowsData.baseline : undefined}
          firstHour={firstHour}
        />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
          <Card className="min-w-0">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>Electricity price, next {Math.round(points.length / 24)} days</CardTitle>
                <CardDescription>$/MWh · {regionName} · times in your time zone</CardDescription>
              </div>
              <ViewToggle view={view} onChange={setView} />
            </div>
            <div className="mb-2">
              <Legend />
            </div>
            {view === "chart" ? (
              <ForecastChart
                points={points}
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
              <ForecastTable points={points} windows={windows} durationHours={durationHours} />
            )}
            {jobStart !== null && (
              <JobReadout
                points={points}
                jobStart={jobStart}
                durationHours={durationHours}
                kw={kw}
                bestAvg={windows[0]?.avg_price_usd_per_mwh ?? null}
              />
            )}
          </Card>

          <Card className="min-w-0 space-y-6">
            <section aria-labelledby="best-times">
              <CardTitle id="best-times">Best start times</CardTitle>
              <CardDescription className="mb-3">
                {formatHours(durationHours)} job · done by {formatDayTime(deadline)}
              </CardDescription>
              {windowsQuery.error ? (
                <ErrorState title="Couldn't rank start times" message={windowsQuery.error.message} onRetry={windowsQuery.retry} />
              ) : windowsData && (windowsMatch || windowsQuery.isRefetching) ? (
                windowsData.windows.length > 0 ? (
                  <WindowList
                    windows={windowsData.windows}
                    firstHour={firstHour}
                    jobStartTime={jobStart === null ? null : points[jobStart].start}
                    highlightedRank={highlightedRank}
                    onHighlight={setHighlightedRank}
                    onSelect={(w) => setPickedStart(indexOfTime(points, w.start))}
                  />
                ) : (
                  <p className="rounded-xl border border-border px-3 py-3 text-sm text-ink-2">
                    No {formatHours(durationHours)} window fits before the deadline. Pick a later time or a shorter job.
                  </p>
                )
              ) : (
                <div className="h-44 animate-pulse rounded-xl bg-surface-2" aria-hidden />
              )}
            </section>

            <section aria-labelledby="cli-heading">
              <h3 id="cli-heading" className="mb-2 text-sm font-medium text-ink">
                Same answer in your terminal
              </h3>
              <CliCommand command={buildCliCommand({ region, durationHours, kw, deadline: customDeadline })} />
              <p className="mt-1.5 text-xs text-muted">
                Add <code className="font-mono">--json</code> for coding agents.
              </p>
            </section>
          </Card>
        </div>

        <ComparePanel sites={sites} region={region} durationHours={durationHours} kw={kw} deadline={deadline} onSelect={changeRegion} />
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-4 px-4 py-6 sm:py-8">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Electricity price forecast</h1>
          <p className="text-sm text-muted">Find the cheapest time to run a heavy job.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {data && <FreshnessBadge generatedAt={data.generated_at} stale={data.stale} now={now} />}
          {data?.data_source === SYNTHETIC_SOURCE && <SampleDataBadge />}
        </div>
      </div>

      {/* Everything the answer depends on, above the answer. */}
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <SiteSelect sites={sites} value={region} onChange={changeRegion} />
        <JobLengthPicker value={durationHours} onChange={changeDuration} />
        <PowerField value={kw} onChange={setKw} />
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
