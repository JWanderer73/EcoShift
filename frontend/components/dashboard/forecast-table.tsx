import type { CarbonWindow, ForecastPoint } from "@/lib/api/types";
import { indexOfTime } from "@/lib/carbon";
import { formatDayTime, formatIntensity } from "@/lib/format";
import { CHART_HEIGHT } from "./forecast-chart";

/** Every hour of the forecast as a table: the chart's accessible, no-hover twin. */
export function ForecastTable({
  points,
  windows,
  durationHours,
}: {
  points: ForecastPoint[];
  windows: CarbonWindow[];
  durationHours: number;
}) {
  const rankByHour = new Map<number, number>();
  for (const w of windows) {
    const start = indexOfTime(points, w.start);
    for (let i = start; start >= 0 && i < start + durationHours; i++) rankByHour.set(i, w.rank);
  }

  return (
    <div className="overflow-auto rounded-lg border border-border" style={{ height: CHART_HEIGHT }}>
      <table className="w-full text-sm">
        <caption className="sr-only">Hourly carbon intensity forecast and best windows</caption>
        <thead className="sticky top-0 bg-surface text-left text-xs text-muted">
          <tr className="border-b border-border">
            <th scope="col" className="px-3 py-2 font-medium">
              Hour starting
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              gCO₂/kWh
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Best window
            </th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {points.map((p, i) => (
            <tr key={p.start} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5 text-ink-2">{formatDayTime(new Date(p.start))}</td>
              <td className="px-3 py-1.5 text-right text-ink">{formatIntensity(p.intensity)}</td>
              <td className="px-3 py-1.5 text-ink-2">{rankByHour.has(i) ? `Window ${rankByHour.get(i)}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
