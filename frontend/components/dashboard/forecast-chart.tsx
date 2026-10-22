"use client";

import { useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import type { CarbonWindow, ForecastPoint } from "@/lib/api/types";
import { averageIntensity, hourStart, indexOfTime } from "@/lib/carbon";
import { clamp, yTicks } from "@/lib/chart";
import { HOUR_MS } from "@/lib/config";
import { formatClock, formatDayTime, formatHours, formatIntensity, formatRange, formatWeekday } from "@/lib/format";
import { useElementWidth } from "@/lib/hooks/use-element-width";

const MARGIN_TOP = 26;
const MARGIN_LEFT = 44;
const MARGIN_RIGHT = 12;
const PLOT_HEIGHT = 220;
const TRACK_GAP = 10;
const TRACK_HEIGHT = 30;
const AXIS_BAND = 26;
/** Total height, including the job track and x-axis labels, so nothing gets clipped. */
export const CHART_HEIGHT = MARGIN_TOP + PLOT_HEIGHT + TRACK_GAP + TRACK_HEIGHT + AXIS_BAND;

const Y_TICK_COUNT = 4;
/** Below this plot width, label every 12 hours instead of every 6 so labels don't collide. */
const NARROW_PLOT_PX = 420;
/** Job block widths at which it gets a full label ("‹ 4h job ›") or a short one ("4h"). */
const FULL_JOB_LABEL_PX = 76;
const SHORT_JOB_LABEL_PX = 26;
/** Keyboard step for PageUp/PageDown on the job block. */
const PAGE_STEP_HOURS = 6;
/** Headroom above the highest point so the line never touches the top edge. */
const Y_HEADROOM = 1.05;
const TOOLTIP_WIDTH = 168;
/** Hours of room the "avg 123" label needs to the right of the job before it flips to the left. */
const AVG_LABEL_HOURS = 4;

export interface ForecastChartProps {
  points: ForecastPoint[];
  windows: CarbonWindow[];
  durationHours: number;
  /** Hour index the job starts at, or null when no start fits before the deadline. */
  jobStart: number | null;
  /** Latest valid start index (from the deadline). */
  lastStart: number;
  /** Hours from the first point to the deadline. */
  deadlineHours: number;
  /** Hours from the first point to now, for the "Now" marker. */
  nowHours: number | null;
  highlightedRank: number | null;
  onJobStartChange: (start: number) => void;
  onHighlightRank: (rank: number | null) => void;
}

/**
 * 48-hour carbon intensity line with the best windows shaded and the user's job as a block
 * they can drag (or move with arrow keys) to compare start times.
 */
export function ForecastChart({
  points,
  windows,
  durationHours,
  jobStart,
  lastStart,
  deadlineHours,
  nowHours,
  highlightedRank,
  onJobStartChange,
  onHighlightRank,
}: ForecastChartProps) {
  const [containerRef, width] = useElementWidth<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  /** Hours between the pointer and the job's start while dragging; null when not dragging. */
  const [dragOffset, setDragOffset] = useState<number | null>(null);
  const [jobFocused, setJobFocused] = useState(false);

  const hours = points.length;
  const plotWidth = Math.max(0, width - MARGIN_LEFT - MARGIN_RIGHT);
  const plotBottom = MARGIN_TOP + PLOT_HEIGHT;
  const trackTop = plotBottom + TRACK_GAP;
  const ticks = yTicks(Math.max(...points.map((p) => p.intensity)) * Y_HEADROOM, Y_TICK_COUNT);
  const yMax = ticks[ticks.length - 1];

  const x = (hour: number) => MARGIN_LEFT + (hour / hours) * plotWidth;
  const y = (intensity: number) => plotBottom - (intensity / yMax) * PLOT_HEIGHT;

  const spans = windows
    .map((w) => ({ rank: w.rank, start: indexOfTime(points, w.start) }))
    .filter((s) => s.start >= 0);
  const rankAt = (hour: number) => spans.find((s) => hour >= s.start && hour < s.start + durationHours)?.rank ?? null;

  function pointerHour(event: { clientX: number }): number {
    const left = svgRef.current?.getBoundingClientRect().left ?? 0;
    return ((event.clientX - left - MARGIN_LEFT) / plotWidth) * hours;
  }

  function moveJob(start: number) {
    const next = clamp(start, 0, lastStart);
    if (next !== jobStart) onJobStartChange(next);
  }

  function showHour(hour: number | null) {
    setHover(hour);
    const rank = hour === null ? null : rankAt(hour);
    if (rank !== highlightedRank) onHighlightRank(rank);
  }

  // Plot: crosshair on hover, click to move the job there.
  function onPlotPointer(event: PointerEvent<SVGRectElement>) {
    if (dragOffset === null) showHour(clamp(Math.floor(pointerHour(event)), 0, hours - 1));
  }

  function onPlotClick(event: MouseEvent<SVGRectElement>) {
    if (jobStart !== null) moveJob(Math.round(pointerHour(event) - durationHours / 2));
  }

  function onPlotKey(event: KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    showHour(clamp((hover ?? -1) + step, 0, hours - 1));
  }

  // Job track: grab the block to drag it, or press anywhere on the track to jump it there.
  function onTrackDown(event: PointerEvent<SVGRectElement>) {
    if (jobStart === null) return;
    const hour = pointerHour(event);
    let start = jobStart;
    if (hour < jobStart || hour > jobStart + durationHours) {
      start = clamp(Math.round(hour - durationHours / 2), 0, lastStart);
      moveJob(start);
    }
    setDragOffset(hour - start);
    showHour(null);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onTrackMove(event: PointerEvent<SVGRectElement>) {
    if (dragOffset !== null) moveJob(Math.round(pointerHour(event) - dragOffset));
  }

  function onTrackUp(event: PointerEvent<SVGRectElement>) {
    setDragOffset(null);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function onJobKey(event: KeyboardEvent) {
    if (jobStart === null) return;
    const moves: Record<string, number> = {
      ArrowLeft: jobStart - 1,
      ArrowDown: jobStart - 1,
      ArrowRight: jobStart + 1,
      ArrowUp: jobStart + 1,
      PageDown: jobStart - PAGE_STEP_HOURS,
      PageUp: jobStart + PAGE_STEP_HOURS,
      Home: 0,
      End: lastStart,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    moveJob(moves[event.key]);
  }

  const linePath = points.map((p, i) => `${i ? "L" : "M"}${x(i + 0.5)},${y(p.intensity)}`).join("");
  const areaPath = `${linePath}L${x(hours - 0.5)},${plotBottom}L${x(0.5)},${plotBottom}Z`;
  const xTickEvery = plotWidth < NARROW_PLOT_PX ? 12 : 6;
  const xTicks = Array.from({ length: hours + 1 }, (_, i) => i).filter((i) => {
    const time = i < hours ? hourStart(points, i) : hourStart(points, hours - 1) + HOUR_MS;
    return new Date(time).getHours() % xTickEvery === 0;
  });

  const jobAvg = jobStart === null ? null : averageIntensity(points, jobStart, durationHours);
  const jobWidth = jobStart === null ? 0 : x(jobStart + durationHours) - x(jobStart);
  const jobRange =
    jobStart === null
      ? ""
      : formatRange(new Date(hourStart(points, jobStart)), new Date(hourStart(points, jobStart) + durationHours * HOUR_MS));
  const hoverPoint = hover === null ? null : points[hover];
  const hoverRank = hover === null ? null : rankAt(hover);
  const tooltipLeft =
    hover === null ? 0 : x(hover + 0.5) + 12 + TOOLTIP_WIDTH > width ? x(hover + 0.5) - 12 - TOOLTIP_WIDTH : x(hover + 0.5) + 12;

  return (
    <div ref={containerRef} className="relative w-full select-none" style={{ height: CHART_HEIGHT }}>
      {width > 0 && (
        <svg
          ref={svgRef}
          width={width}
          height={CHART_HEIGHT}
          className={dragOffset !== null ? "cursor-grabbing" : undefined}
          role="group"
          aria-label="Carbon intensity forecast with the best windows and your job"
        >
          {/* Gridlines and y-axis */}
          {ticks.map((t) => (
            <g key={t}>
              <line
                x1={MARGIN_LEFT}
                x2={width - MARGIN_RIGHT}
                y1={y(t)}
                y2={y(t)}
                stroke={t === 0 ? "var(--axis)" : "var(--grid)"}
                strokeWidth={1}
              />
              <text x={MARGIN_LEFT - 8} y={y(t)} textAnchor="end" dominantBaseline="middle" className="fill-muted text-[11px] tabular-nums">
                {formatIntensity(t)}
              </text>
            </g>
          ))}

          {/* Past the deadline: shaded through the plot and track */}
          {deadlineHours < hours && (
            <g>
              <rect
                x={x(deadlineHours)}
                y={MARGIN_TOP}
                width={x(hours) - x(deadlineHours)}
                height={trackTop + TRACK_HEIGHT - MARGIN_TOP}
                fill="var(--surface-2)"
              />
              <line x1={x(deadlineHours)} x2={x(deadlineHours)} y1={MARGIN_TOP} y2={trackTop + TRACK_HEIGHT} stroke="var(--axis)" />
              <text
                x={x(deadlineHours) + (deadlineHours > hours * 0.8 ? -4 : 4)}
                y={MARGIN_TOP + 12}
                textAnchor={deadlineHours > hours * 0.8 ? "end" : "start"}
                className="fill-muted text-[11px]"
              >
                Deadline
              </text>
            </g>
          )}

          {/* Best windows */}
          {spans.map(({ rank, start }) => {
            const active = rank === highlightedRank;
            return (
              <g key={rank}>
                <rect
                  x={x(start)}
                  y={MARGIN_TOP}
                  width={x(start + durationHours) - x(start)}
                  height={PLOT_HEIGHT}
                  fill="var(--window)"
                  fillOpacity={active ? 0.34 : 0.16}
                />
                <text
                  x={x(start + durationHours / 2)}
                  y={MARGIN_TOP - 9}
                  textAnchor="middle"
                  className={active ? "fill-ink text-[12px] font-semibold" : "fill-ink-2 text-[11px] font-medium"}
                >
                  {rank}
                </text>
              </g>
            );
          })}

          {/* Your job, across the plot */}
          {jobStart !== null && jobAvg !== null && (
            <g>
              <rect
                x={x(jobStart)}
                y={MARGIN_TOP}
                width={x(jobStart + durationHours) - x(jobStart)}
                height={PLOT_HEIGHT}
                fill="var(--ink)"
                fillOpacity={0.05}
              />
              <line
                x1={x(jobStart)}
                x2={x(jobStart + durationHours)}
                y1={y(jobAvg)}
                y2={y(jobAvg)}
                stroke="var(--ink-2)"
                strokeWidth={2}
                strokeLinecap="round"
              />
            </g>
          )}

          {/* Forecast */}
          <path d={areaPath} fill="var(--forecast)" fillOpacity={0.1} />
          <path d={linePath} fill="none" stroke="var(--forecast)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {jobStart !== null && jobAvg !== null && (
            <text
              // Label sits right of the job, or left of it when the job is near the right edge.
              x={jobStart + durationHours > hours - AVG_LABEL_HOURS ? x(jobStart) - 4 : x(jobStart + durationHours) + 4}
              y={y(jobAvg)}
              dominantBaseline="middle"
              textAnchor={jobStart + durationHours > hours - AVG_LABEL_HOURS ? "end" : "start"}
              className="fill-ink-2 text-[11px] font-medium tabular-nums"
              stroke="var(--surface)"
              strokeWidth={3}
              paintOrder="stroke"
            >
              avg {formatIntensity(jobAvg)}
            </text>
          )}

          {/* Now */}
          {nowHours !== null && (
            <g>
              <line x1={x(nowHours)} x2={x(nowHours)} y1={MARGIN_TOP} y2={plotBottom} stroke="var(--ink-2)" />
              <text x={x(nowHours) + 4} y={MARGIN_TOP + 12} className="fill-ink-2 text-[11px] font-medium">
                Now
              </text>
            </g>
          )}

          {/* Crosshair */}
          {hoverPoint && hover !== null && (
            <g pointerEvents="none">
              <line x1={x(hover + 0.5)} x2={x(hover + 0.5)} y1={MARGIN_TOP} y2={plotBottom} stroke="var(--ink-2)" />
              <circle
                cx={x(hover + 0.5)}
                cy={y(hoverPoint.intensity)}
                r={4}
                fill="var(--forecast)"
                stroke="var(--surface)"
                strokeWidth={2}
              />
            </g>
          )}

          {/* Plot hit area: wider than the line so the pointer only has to be near an hour */}
          <rect
            x={MARGIN_LEFT}
            y={MARGIN_TOP}
            width={plotWidth}
            height={PLOT_HEIGHT}
            fill="transparent"
            className="cursor-crosshair outline-none"
            style={{ touchAction: "pan-y" }}
            tabIndex={0}
            aria-label="Hourly forecast. Use the left and right arrow keys to read each hour, or switch to the table."
            onPointerMove={onPlotPointer}
            onPointerDown={onPlotPointer}
            onPointerLeave={() => showHour(null)}
            onClick={onPlotClick}
            onKeyDown={onPlotKey}
            onFocus={() => showHour(hover ?? 0)}
            onBlur={() => showHour(null)}
          />

          {/* Job track */}
          <rect
            x={MARGIN_LEFT}
            y={trackTop}
            width={plotWidth}
            height={TRACK_HEIGHT}
            rx={6}
            fill="var(--surface-2)"
            fillOpacity={0.6}
          />
          {jobStart !== null && (
            <g
              role="slider"
              tabIndex={0}
              aria-label="Job start time"
              aria-valuemin={0}
              aria-valuemax={lastStart}
              aria-valuenow={jobStart}
              aria-valuetext={`${jobRange}, average ${formatIntensity(jobAvg ?? 0)} grams CO2 per kilowatt-hour`}
              className="outline-none"
              onKeyDown={onJobKey}
              onFocus={() => setJobFocused(true)}
              onBlur={() => setJobFocused(false)}
            >
              {jobFocused && (
                <rect
                  x={x(jobStart) - 2}
                  y={trackTop - 1}
                  width={x(jobStart + durationHours) - x(jobStart) + 4}
                  height={TRACK_HEIGHT + 2}
                  rx={8}
                  fill="none"
                  stroke="var(--forecast)"
                  strokeWidth={2}
                />
              )}
              <rect
                x={x(jobStart) + 1}
                y={trackTop + 3}
                width={Math.max(2, x(jobStart + durationHours) - x(jobStart) - 2)}
                height={TRACK_HEIGHT - 6}
                rx={5}
                fill="var(--window)"
              />
              {jobWidth >= SHORT_JOB_LABEL_PX && (
                <text
                  x={x(jobStart + durationHours / 2)}
                  y={trackTop + TRACK_HEIGHT / 2}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="var(--on-window)"
                  className="text-[12px] font-semibold"
                >
                  {jobWidth >= FULL_JOB_LABEL_PX ? `‹ ${formatHours(durationHours)} job ›` : formatHours(durationHours)}
                </text>
              )}
            </g>
          )}
          <rect
            x={MARGIN_LEFT}
            y={trackTop}
            width={plotWidth}
            height={TRACK_HEIGHT}
            fill="transparent"
            className={dragOffset !== null ? "cursor-grabbing" : "cursor-grab"}
            style={{ touchAction: "none" }}
            aria-hidden="true"
            onPointerDown={onTrackDown}
            onPointerMove={onTrackMove}
            onPointerUp={onTrackUp}
            onPointerCancel={onTrackUp}
          />

          {/* X axis */}
          {xTicks.map((i) => {
            const time = new Date(i < hours ? hourStart(points, i) : hourStart(points, hours - 1) + HOUR_MS);
            const midnight = time.getHours() === 0;
            return (
              <g key={i}>
                <line x1={x(i)} x2={x(i)} y1={plotBottom} y2={plotBottom + 4} stroke="var(--axis)" />
                <text
                  x={x(i)}
                  y={trackTop + TRACK_HEIGHT + 17}
                  textAnchor="middle"
                  className={midnight ? "fill-ink-2 text-[11px] font-semibold" : "fill-muted text-[11px] tabular-nums"}
                >
                  {midnight ? formatWeekday(time) : formatClock(time)}
                </text>
              </g>
            );
          })}
        </svg>
      )}

      {hoverPoint && hover !== null && dragOffset === null && (
        <div
          className="pointer-events-none absolute rounded-lg border border-border bg-surface px-3 py-2 shadow-sm"
          style={{ left: tooltipLeft, top: MARGIN_TOP, width: TOOLTIP_WIDTH }}
          role="status"
        >
          <div className="text-sm">
            <span className="font-semibold text-ink tabular-nums">{formatIntensity(hoverPoint.intensity)}</span>{" "}
            <span className="text-xs text-muted">gCO₂/kWh</span>
          </div>
          <div className="text-xs text-ink-2">{formatDayTime(new Date(hoverPoint.start))}</div>
          {hoverRank !== null && (
            <div className="mt-1 flex items-center gap-1.5 text-xs text-ink-2">
              <span className="inline-block h-2.5 w-2.5 rounded-sm bg-window" aria-hidden />
              In best window {hoverRank}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
