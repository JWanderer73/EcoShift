import { CircleCheck, Hourglass, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { Baseline, CarbonWindow, ForecastPoint } from "@/lib/api/types";
import { verdictFor, type Verdict } from "@/lib/carbon";
import { formatDayTime, formatHours, formatIntensity, formatPct, formatRange } from "@/lib/format";

const VERDICTS: Record<Verdict, { label: string; icon: typeof Info; iconClass: string }> = {
  wait: { label: "Wait if you can", icon: Hourglass, iconClass: "text-warning" },
  "small-gain": { label: "Small gain from waiting", icon: Info, iconClass: "text-ink-2" },
  "run-now": { label: "Good time to run", icon: CircleCheck, iconClass: "text-good" },
};

export interface NowCardProps {
  regionName: string;
  /** Intensity this hour. */
  current: ForecastPoint;
  durationHours: number;
  /** Best window for the planned job, or undefined when none fits the deadline. */
  best: CarbonWindow | undefined;
  /** The same job started now, which the best window's savings are measured against. */
  baseline: Baseline | undefined;
  /** Start of the forecast's first hour, to tell whether the best window is "now". */
  firstHour: string;
}

function Advice({ best, durationHours, firstHour }: Pick<NowCardProps, "best" | "durationHours" | "firstHour">) {
  if (!best) return <>No {formatHours(durationHours)} window fits before your deadline.</>;
  if (best.start === firstHour) return <>Starting now is the cleanest option for a {formatHours(durationHours)} job.</>;
  return (
    <>
      The cleanest {formatHours(durationHours)} window starts <strong className="font-semibold">{formatDayTime(new Date(best.start))}</strong>{" "}
      and uses <strong className="font-semibold">{formatPct(best.co2_saved_pct)} less CO₂</strong> than starting now.
    </>
  );
}

/** A job's average intensity and when it runs, so the % saved can be checked at a glance. */
function JobAverage({ label, start, end, avg }: { label: string; start: string; end: string; avg: number }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-lg font-semibold">avg {formatIntensity(avg)}</dd>
      <dd className="text-ink-2">{formatRange(new Date(start), new Date(end))}</dd>
    </div>
  );
}

/** The headline: how dirty the grid is this hour, and whether to run now or wait. */
export function NowCard({ regionName, current, durationHours, best, baseline, firstHour }: NowCardProps) {
  const verdict = VERDICTS[verdictFor(best?.co2_saved_pct ?? 0)];
  const Icon = verdict.icon;
  return (
    <Card className="grid gap-6 md:grid-cols-[1fr_auto] md:items-end">
      <div>
        <p className="text-sm text-muted">Right now in {regionName}</p>
        <p className="mt-1 flex items-baseline gap-2">
          <span className="text-5xl font-semibold tracking-tight sm:text-6xl" data-testid="now-intensity">
            {formatIntensity(current.intensity)}
          </span>
          <span className="text-sm text-muted">gCO₂/kWh</span>
        </p>
        <p className="mt-3 flex items-center gap-2 font-semibold">
          <Icon className={`size-5 ${verdict.iconClass}`} aria-hidden />
          {best ? verdict.label : "Deadline too soon"}
        </p>
        <p className="mt-1 max-w-xl text-ink-2" aria-live="polite">
          <Advice best={best} durationHours={durationHours} firstHour={firstHour} />
        </p>
      </div>
      {best && baseline && (
        <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm md:text-right">
          <JobAverage label="Start now" start={baseline.start} end={baseline.end} avg={baseline.avg_intensity_g_per_kwh} />
          <JobAverage label="Best window" start={best.start} end={best.end} avg={best.avg_intensity_g_per_kwh} />
        </dl>
      )}
    </Card>
  );
}
