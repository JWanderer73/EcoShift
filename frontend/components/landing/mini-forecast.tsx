"use client";

import type { ForecastPoint } from "@/lib/api/types";
import { indexOfTime } from "@/lib/carbon";
import { useElementWidth } from "@/lib/hooks/use-element-width";

const HEIGHT = 96;
const PAD_Y = 6;

/**
 * Sparkline of the forecast with the best window shaded. Decorative: the card around it states
 * the numbers in text, so it's hidden from screen readers and has no hover layer.
 */
export function MiniForecast({ points, bestStart, durationHours }: { points: ForecastPoint[]; bestStart?: string; durationHours: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const max = Math.max(...points.map((p) => p.intensity));
  const x = (hour: number) => (hour / points.length) * width;
  const y = (value: number) => HEIGHT - PAD_Y - (value / max) * (HEIGHT - PAD_Y * 2);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i + 0.5)},${y(p.intensity)}`).join("");
  const band = bestStart ? indexOfTime(points, bestStart) : -1;

  return (
    <div ref={ref} className="w-full" style={{ height: HEIGHT }} aria-hidden>
      {width > 0 && (
        <svg width={width} height={HEIGHT}>
          {band >= 0 && (
            <rect x={x(band)} y={0} width={x(band + durationHours) - x(band)} height={HEIGHT} rx={4} fill="var(--window)" fillOpacity={0.22} />
          )}
          <path d={`${line}L${x(points.length - 0.5)},${HEIGHT}L${x(0.5)},${HEIGHT}Z`} fill="var(--forecast)" fillOpacity={0.1} />
          <path d={line} fill="none" stroke="var(--forecast)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={x(0.5)} cy={y(points[0].intensity)} r={4} fill="var(--forecast)" stroke="var(--surface)" strokeWidth={2} />
        </svg>
      )}
    </div>
  );
}
