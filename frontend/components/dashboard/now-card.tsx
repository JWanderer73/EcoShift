import { CircleCheck, Hourglass, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { ForecastPoint } from "@/lib/api/types";
import { verdictFor, type Verdict } from "@/lib/carbon";
import { dollarsSaved, jobDollars, type JobStats, type JobWindow } from "@/lib/cost";
import { formatDayTime, formatHours, formatIntensity, formatPct, formatRange, formatUsd } from "@/lib/format";

const VERDICTS: Record<Verdict, { label: string; icon: typeof Info; iconClass: string }> = {
  wait: { label: "Wait if you can", icon: Hourglass, iconClass: "text-warning" },
  "small-gain": { label: "Small gain from waiting", icon: Info, iconClass: "text-ink-2" },
  "run-now": { label: "Good time to run", icon: CircleCheck, iconClass: "text-good" },
};

export interface NowCardProps {
  regionName: string;
  /** Where the site is and who powers it, e.g. "3020 Coronado Dr, Santa Clara · Silicon Valley Power". */
  location?: string;
  /** This hour's price and intensity. */
  current: ForecastPoint;
  durationHours: number;
  powerMw: number;
  carbonPrice: number;
  /** Best window for the planned job, or undefined when none fits the deadline. */
  best: JobWindow | undefined;
  /** The same job started now, which the best window is measured against. */
  baseline: JobStats;
}

function co2Phrase(pct: number) {
  if (Math.round(pct) === 0) return "about the same CO₂";
  return `${formatPct(pct)} ${pct > 0 ? "less" : "more"} CO₂`;
}

function Advice({ best, baseline, durationHours, powerMw, carbonPrice }: Omit<NowCardProps, "regionName" | "location" | "current">) {
  const job = formatHours(durationHours);
  if (!best) return <>No {job} window fits before your deadline.</>;
  const saved = dollarsSaved(baseline, best, powerMw, durationHours);
  if (best.startIndex === 0) {
    return saved === null ? <>Starting now is the cleanest option for a {job} job.</> : <>Starting now is the best option for a {job} job.</>;
  }
  return (
    <>
      The best {job} window starts <strong className="font-semibold">{formatDayTime(new Date(best.start))}</strong>
      {saved === null ? (
        <>
          {" "}
          and uses <strong className="font-semibold">{co2Phrase(best.co2SavedPct)}</strong> than starting now.
        </>
      ) : (
        <>
          : <strong className="font-semibold">{formatUsd(saved)} cheaper</strong> with {co2Phrase(best.co2SavedPct)} than starting now
          {carbonPrice > 0 && <> (carbon at {formatUsd(carbonPrice)}/t)</>}.
        </>
      )}
    </>
  );
}

/** What a job costs (or emits, without prices) and when it runs, so the comparison can be checked at a glance. */
function JobSummary({ label, job, powerMw, durationHours }: { label: string; job: JobStats; powerMw: number; durationHours: number }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">
        {job.avgCost === null ? <>avg {formatIntensity(job.avgIntensity)}</> : formatUsd(jobDollars(job.avgCost, powerMw, durationHours))}
      </dd>
      <dd className="text-ink-2">{formatRange(new Date(job.start), new Date(job.end))}</dd>
    </div>
  );
}

/** The headline: what power costs and how dirty it is this hour, and whether to run now or wait. */
export function NowCard({ regionName, location, current, durationHours, powerMw, carbonPrice, best, baseline }: NowCardProps) {
  const verdict = VERDICTS[verdictFor(best ? (best.costSavedPct ?? best.co2SavedPct) : 0)];
  const Icon = verdict.icon;
  const priced = current.price !== undefined;
  return (
    <Card className="grid gap-6 md:grid-cols-[1fr_auto] md:items-end">
      <div>
        <p className="text-sm text-muted">
          Right now at <span className="font-medium text-ink-2">{regionName}</span>
          {location && <span className="block text-xs">{location}</span>}
        </p>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-2">
          <span className="text-5xl font-semibold tracking-tight tabular-nums sm:text-6xl" data-testid="now-value">
            {priced ? formatUsd(current.price ?? 0) : formatIntensity(current.intensity)}
          </span>
          <span className="text-sm text-muted">{priced ? "/MWh" : "gCO₂/kWh"}</span>
          {priced && (
            <span className="text-sm text-ink-2 tabular-nums">
              · {formatIntensity(current.intensity)} gCO₂/kWh
            </span>
          )}
        </p>
        <p className="mt-3 flex items-center gap-2 font-semibold">
          <Icon className={`size-5 ${verdict.iconClass}`} aria-hidden />
          {best ? verdict.label : "Deadline too soon"}
        </p>
        <p className="mt-1 max-w-xl text-ink-2" aria-live="polite">
          <Advice best={best} baseline={baseline} durationHours={durationHours} powerMw={powerMw} carbonPrice={carbonPrice} />
        </p>
      </div>
      {best && (
        <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:text-right">
          <JobSummary label="Start now" job={baseline} powerMw={powerMw} durationHours={durationHours} />
          <JobSummary label="Best window" job={best} powerMw={powerMw} durationHours={durationHours} />
        </dl>
      )}
    </Card>
  );
}
