import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import type { SiteOption } from "@/lib/compare";
import { formatDayTime, formatHours, formatIntensity, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ErrorState } from "./status";

const th = "px-3 py-2 font-medium";
/** Columns that drop out on phones so the table never scrolls sideways. */
const wide = "hidden sm:table-cell";

export interface SiteComparisonProps {
  /** Ranked options, best first; undefined while loading. */
  options: SiteOption[] | undefined;
  error: Error | undefined;
  onRetry: () => void;
  /** Code of the site the dashboard is showing. */
  current: string;
  durationHours: number;
  /** Average power draw of the job, in kW. */
  kw: number;
  carbonPrice?: number;
  deadline: Date;
  onSelect: (code: string) => void;
}

function Headline({ options, current }: { options: SiteOption[]; current: string }) {
  const [top] = options;
  const here = options.find((o) => o.region.code === current);
  if (!top?.best) return <>No campus has a window that fits this deadline.</>;
  if (top.region.code === current) return <>{top.region.shortName} is already the cheapest campus for this job.</>;
  const saved = here?.dollars != null && top.dollars !== null ? here.dollars - top.dollars : null;
  return (
    <>
      <strong className="font-semibold text-ink">{top.region.shortName}</strong> is the cheapest campus: start{" "}
      {formatDayTime(new Date(top.best.start))}
      {saved !== null && here ? (
        <>
          {" "}
          for <strong className="font-semibold text-ink">{formatUsd(saved)} less</strong> than {here.region.shortName}&apos;s best window.
        </>
      ) : (
        "."
      )}
    </>
  );
}

/** Difference from the site being viewed, in dollars. */
function versus(option: SiteOption, here: SiteOption | undefined): string {
  if (option.region.code === here?.region.code) return "Viewing";
  if (option.dollars === null || here?.dollars == null) return "—";
  const diff = here.dollars - option.dollars;
  if (Math.abs(diff) < 0.005) return "Same";
  return diff > 0 ? `${formatUsd(diff)} less` : `${formatUsd(-diff)} more`;
}

/** Every site's best window for the planned job, so people can choose where as well as when. */
export function SiteComparison({ options, error, onRetry, current, durationHours, kw, carbonPrice = 0, deadline, onSelect }: SiteComparisonProps) {
  const here = options?.find((o) => o.region.code === current);
  const hereName = here?.region.shortName ?? current;
  const showCarbon = options?.some((o) => o.best?.avgIntensity != null) ?? false;

  return (
    <Card className="min-w-0">
      <CardTitle id="compare-sites">Compare campuses</CardTitle>
      <CardDescription className="mb-3">
        Best {formatHours(durationHours)} window at each campus · {kw} kW · done by {formatDayTime(deadline)}
        {carbonPrice > 0 && <> · cost includes carbon at {formatUsd(carbonPrice)}/t</>}
      </CardDescription>

      {error ? (
        <ErrorState title="Couldn't compare sites" message={error.message} onRetry={onRetry} />
      ) : !options ? (
        <div className="h-72 animate-pulse rounded-xl bg-surface-2" role="status" aria-label="Loading sites" />
      ) : (
        <>
          <p className="mb-3 text-ink-2" aria-live="polite" data-testid="compare-headline">
            <Headline options={options} current={current} />
          </p>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm" aria-labelledby="compare-sites">
              <thead className="bg-surface text-left text-xs text-muted">
                <tr className="border-b border-border">
                  <th scope="col" className={th}>
                    Campus
                  </th>
                  <th scope="col" className={th}>
                    Best start
                  </th>
                  <th scope="col" className={`${th} text-right`}>
                    Job cost
                  </th>
                  <th scope="col" className={`${th} ${wide} text-right`}>
                    Power $/MWh
                  </th>
                  {showCarbon && (
                    <th scope="col" className={`${th} ${wide} text-right`}>
                      gCO₂/kWh
                    </th>
                  )}
                  <th scope="col" className={`${th} text-right`}>
                    vs {hereName}
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {options.map((option, i) => {
                  const viewing = option.region.code === current;
                  return (
                    <tr key={option.region.code} className={cn("border-b border-border last:border-0", viewing && "bg-window/10")}>
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        <button
                          type="button"
                          onClick={() => onSelect(option.region.code)}
                          aria-current={viewing ? "true" : undefined}
                          className="flex items-center gap-2 text-left font-medium text-ink hover:underline"
                        >
                          <span
                            className={cn(
                              "flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                              i === 0 && option.best ? "bg-window text-on-window" : "bg-surface-2 text-ink-2",
                            )}
                          >
                            {i + 1}
                          </span>
                          {option.region.shortName}
                          <span className="hidden text-xs font-normal text-muted sm:inline">{option.region.city}</span>
                        </button>
                      </th>
                      {option.error ? (
                        <td colSpan={showCarbon ? 5 : 4} className="px-3 py-2 text-muted">
                          Unavailable
                        </td>
                      ) : !option.best ? (
                        <td colSpan={showCarbon ? 5 : 4} className="px-3 py-2 text-muted">
                          No window fits the deadline
                        </td>
                      ) : (
                        <>
                          <td className="px-3 py-2 text-ink-2">{formatDayTime(new Date(option.best.start))}</td>
                          <td className="px-3 py-2 text-right font-medium text-ink">{option.dollars === null ? "—" : formatUsd(option.dollars)}</td>
                          <td className={`px-3 py-2 text-right text-ink-2 ${wide}`}>
                            {option.best.avgPrice === null ? "—" : formatUsd(option.best.avgPrice)}
                          </td>
                          {showCarbon && (
                            <td className={`px-3 py-2 text-right text-ink-2 ${wide}`}>
                              {option.best.avgIntensity === null ? "—" : formatIntensity(option.best.avgIntensity)}
                            </td>
                          )}
                          <td className={cn("px-3 py-2 text-right", viewing ? "text-muted" : "text-ink-2")}>{versus(option, here)}</td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">
            Wholesale day-ahead prices only, for a selection of campuses. Utility tariffs, PUE, and moving data between sites aren&apos;t included.
          </p>
        </>
      )}
    </Card>
  );
}
