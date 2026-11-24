import { CircleCheck, Hourglass, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { Baseline, ForecastPoint, PriceWindow } from "@/lib/api/types";
import { verdictFor, type Verdict } from "@/lib/carbon";
import { formatDayTime, formatHours, formatPrice, formatRange, formatUsd } from "@/lib/format";

const VERDICTS: Record<Verdict, { label: string; icon: typeof Info; iconClass: string }> = {
  wait: { label: "Wait if you can", icon: Hourglass, iconClass: "text-warning" },
  "small-gain": { label: "Small gain from waiting", icon: Info, iconClass: "text-ink-2" },
  "run-now": { label: "Good time to run", icon: CircleCheck, iconClass: "text-good" },
};

export interface NowCardProps {
  regionName: string;
  /** Price this hour. */
  current: ForecastPoint;
  durationHours: number;
  /** Best window for the planned job, or undefined when none fits the deadline. */
  best: PriceWindow | undefined;
  /** The same job started now, which the best window's savings are measured against. */
  baseline: Baseline | undefined;
  /** Start of the forecast's first hour, to tell whether the best window is "now". */
  firstHour: string;
}

function Advice({ best, durationHours, firstHour }: Pick<NowCardProps, "best" | "durationHours" | "firstHour">) {
  if (!best) return <>No {formatHours(durationHours)} window fits before your deadline.</>;
  if (best.start === firstHour) return <>Starting now is the cheapest option for a {formatHours(durationHours)} job.</>;
  return (
    <>
      The cheapest {formatHours(durationHours)} window starts <strong className="font-semibold">{formatDayTime(new Date(best.start))}</strong>{" "}
      and costs <strong className="font-semibold">{formatUsd(best.saved_usd)} less</strong> than starting now.
    </>
  );
}

/** A job's average price, its cost and when it runs, so the saving can be checked at a glance. */
function JobAverage({ label, start, end, avg, cost }: { label: string; start: string; end: string; avg: number; cost: number }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-lg font-semibold">{formatUsd(cost)}</dd>
      <dd className="text-ink-2 tabular-nums">avg {formatPrice(avg)}/MWh</dd>
      <dd className="text-ink-2">{formatRange(new Date(start), new Date(end))}</dd>
    </div>
  );
}

/** The headline: what power costs this hour, and whether to run now or wait. */
export function NowCard({ regionName, current, durationHours, best, baseline, firstHour }: NowCardProps) {
  const verdict = VERDICTS[verdictFor(best?.saved_usd_per_mwh ?? 0)];
  const Icon = verdict.icon;
  return (
    <Card className="grid gap-6 md:grid-cols-[1fr_auto] md:items-end">
      <div>
        <p className="text-sm text-muted">Right now in {regionName}</p>
        <p className="mt-1 flex items-baseline gap-2">
          <span className="text-5xl font-semibold tracking-tight sm:text-6xl" data-testid="now-price">
            {formatPrice(current.price)}
          </span>
          <span className="text-sm text-muted">/MWh{current.kind ? ` · ${current.kind}` : ""}</span>
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
          <JobAverage label="Start now" start={baseline.start} end={baseline.end} avg={baseline.avg_price_usd_per_mwh} cost={baseline.cost_usd} />
          <JobAverage label="Best window" start={best.start} end={best.end} avg={best.avg_price_usd_per_mwh} cost={best.cost_usd} />
        </dl>
      )}
    </Card>
  );
}
