import { CircleAlert, FlaskConical, RefreshCw, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatAge, formatDayTime } from "@/lib/format";

/** How old the forecast is, from the API's `generated_at` and `stale` fields. */
export function FreshnessBadge({ generatedAt, stale, now }: { generatedAt: string; stale: boolean; now: number | null }) {
  const age = now === null ? "recently" : formatAge(new Date(generatedAt), now);
  if (stale) {
    return (
      <Badge>
        <TriangleAlert className="text-warning" aria-hidden />
        Stale · updated {age}
      </Badge>
    );
  }
  return (
    <Badge>
      <span className="size-2 rounded-full bg-good" aria-hidden />
      Updated {age}
    </Badge>
  );
}

/** Shown whenever the API says the numbers are synthetic, so a demo never passes them off as real. */
export function SampleDataBadge() {
  return (
    <Badge title="Generated numbers, not a real forecast. Replaced by live data once the EcoShift API is deployed.">
      <FlaskConical aria-hidden />
      Sample data
    </Badge>
  );
}

export function StaleBanner({ generatedAt }: { generatedAt: string }) {
  return (
    <div role="status" className="flex items-start gap-3 rounded-xl border border-warning/50 bg-warning/10 px-4 py-3 text-sm">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
      <p>
        <span className="font-semibold">This forecast is out of date.</span> The pipeline last refreshed it{" "}
        {formatDayTime(new Date(generatedAt))}, so you&apos;re seeing the last good forecast. Later hours may be less accurate.
      </p>
    </div>
  );
}

export function ErrorState({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-xl border border-critical/40 bg-critical/5 p-4 text-sm">
      <div className="flex items-start gap-3">
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden />
        <div>
          <p className="font-semibold">{title}</p>
          <p className="text-ink-2">{message}</p>
        </div>
      </div>
      <Button size="sm" onClick={onRetry}>
        <RefreshCw aria-hidden />
        Try again
      </Button>
    </div>
  );
}
