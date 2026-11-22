import type { ForecastPoint } from "@/lib/api/types";
import { hourlyCost, type JobWindow } from "@/lib/cost";
import { formatDayTime, formatIntensity, formatUsd } from "@/lib/format";
import { CHART_HEIGHT } from "./forecast-chart";

const th = "px-3 py-2 font-medium";
const num = "px-3 py-1.5 text-right";

/** Every hour of the forecast as a table: the chart's accessible, no-hover twin. */
export function ForecastTable({
  points,
  windows,
  durationHours,
  carbonPrice,
  priced,
}: {
  points: ForecastPoint[];
  windows: JobWindow[];
  durationHours: number;
  carbonPrice: number;
  priced: boolean;
}) {
  const rankByHour = new Map<number, number>();
  for (const w of windows) {
    for (let i = w.startIndex; i < w.startIndex + durationHours; i++) rankByHour.set(i, w.rank);
  }

  return (
    <div className="overflow-auto rounded-lg border border-border" style={{ height: CHART_HEIGHT }}>
      <table className="w-full text-sm">
        <caption className="sr-only">Hourly price, carbon intensity, and cost forecast, with the best windows</caption>
        <thead className="sticky top-0 bg-surface text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th scope="col" className={th}>
              Hour starting
            </th>
            {priced && (
              <th scope="col" className={`${th} text-right`}>
                Price $/MWh
              </th>
            )}
            <th scope="col" className={`${th} text-right`}>
              gCO₂/kWh
            </th>
            {priced && (
              <th scope="col" className={`${th} text-right`}>
                Cost $/MWh
              </th>
            )}
            <th scope="col" className={th}>
              Best window
            </th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {points.map((p, i) => (
            <tr key={p.start} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5 text-ink-2">{formatDayTime(new Date(p.start))}</td>
              {priced && <td className={`${num} text-ink-2`}>{formatUsd(p.price ?? 0)}</td>}
              <td className={`${num} text-ink-2`}>{formatIntensity(p.intensity)}</td>
              {priced && <td className={`${num} font-medium text-ink`}>{formatUsd(hourlyCost(p, carbonPrice))}</td>}
              <td className="px-3 py-1.5 text-ink-2">{rankByHour.has(i) ? `Window ${rankByHour.get(i)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
