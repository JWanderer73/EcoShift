import { SYNTHETIC_SOURCE, type ForecastResponse, type WindowsResponse } from "@/lib/api/types";
import { DEFAULT_KW, HOUR_MS } from "@/lib/config";
import { formatCliTime, formatUsd, formatZoneName, toOffsetIso, type ZoneOption } from "@/lib/format";

export interface CliCommandOptions {
  region: string;
  durationHours: number;
  /** Average power draw in kW; the flag is left out at the CLI's default. */
  kw?: number;
  /** Null means the end of the forecast, which is the CLI's default, so the flag is left out. */
  deadline: Date | null;
}

/**
 * The `carbon-windows best` command that asks the CLI the same question as the dashboard's planner.
 * The deadline carries its UTC offset so the command means the same thing on any machine.
 */
export function buildCliCommand({ region, durationHours, kw, deadline }: CliCommandOptions): string {
  const deadlineFlag = deadline ? ` --deadline ${toOffsetIso(deadline)}` : "";
  const kwFlag = kw && kw !== DEFAULT_KW ? ` --kw ${kw}` : "";
  return `carbon-windows best --duration ${durationHours}${deadlineFlag}${kwFlag} --location ${region}`;
}

// A terminal-style rendering of the planner's answer for the landing page: summary line, hourly
// price chart and ranked windows. It illustrates the CLI; the real output is `carbon-windows best`.

const BARS = "▁▂▃▄▅▆▇█";
const AXIS_LABEL_EVERY_HOURS = 12;

/** Round like Python's round() and f"{x:.0f}": exact halves go to the even neighbour. */
function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const rest = value - floor;
  return rest > 0.5 || (rest === 0.5 && floor % 2 !== 0) ? floor + 1 : floor;
}

function wholeNumber(value: number): string {
  return String(roundHalfEven(value));
}

function fraction(value: number, lowest: number, highest: number): number {
  return highest > lowest ? (value - lowest) / (highest - lowest) : 0;
}

/** "now", "in 25m", "in 3h" or "in 21h 25m". */
function formatRelative(moment: number, now: number): string {
  const total = Math.round((moment - now) / 60_000);
  if (total <= 0) return "now";
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (!hours) return `in ${minutes}m`;
  return minutes ? `in ${hours}h ${minutes}m` : `in ${hours}h`;
}

/** "Wed 17:00–19:00 PDT", or "Wed 23:00–Thu 02:00 PDT" across midnight. */
function formatSpan(startIso: string, endIso: string, zone: ZoneOption): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const [startDay] = formatCliTime(start, zone).split(" ");
  const [endDay, endClock] = formatCliTime(end, zone).split(" ");
  const sameDay = startDay === endDay && end.getTime() - start.getTime() < 24 * HOUR_MS;
  return `${formatCliTime(start, zone)}–${sameDay ? endClock : `${endDay} ${endClock}`} ${formatZoneName(start, zone)}`;
}

function headline(response: WindowsResponse, now: number, zone: ZoneOption): string {
  const best = response.windows[0];
  if (!best) return "No window fits before the deadline.";
  const when = formatSpan(best.start, best.end, zone);
  if (Date.parse(best.start) === Date.parse(response.baseline.start)) {
    return `Best: run now (${when}). Nothing cheaper before the deadline.`;
  }
  return `Best: ${when} (${formatRelative(Date.parse(best.start), now)}) · saves ${formatUsd(best.saved_usd)} vs running now`;
}

/** Time labels every 12 hours, one bar per hour, and a marker like └─1─┘ under each window. */
function chart(forecast: ForecastResponse, response: WindowsResponse, zone: ZoneOption): string[] {
  const { points } = forecast;
  const values = points.map((p) => p.price);
  const lowest = Math.min(...values);
  const highest = Math.max(...values);

  const axis: string[] = Array(points.length).fill(" ");
  for (let i = 0; i < points.length; i += AXIS_LABEL_EVERY_HOURS) {
    const label = formatCliTime(new Date(points[i].start), zone);
    axis.splice(i, label.length, ...label);
  }

  const bars = values.map((v) => BARS[roundHalfEven(fraction(v, lowest, highest) * (BARS.length - 1))]).join("");

  const column = new Map(points.map((p, i) => [Date.parse(p.start), i]));
  const width = response.job.duration_hours;
  const markers: string[] = Array(points.length).fill(" ");
  for (const window of response.windows) {
    const first = column.get(Date.parse(window.start));
    if (first === undefined) continue;
    const cells: string[] = Array(width).fill("─");
    if (width > 1) {
      cells[0] = "└";
      cells[width - 1] = "┘";
    }
    const label = String(window.rank);
    if (label.length <= width) cells.splice(Math.floor((width - label.length) / 2), label.length, ...label);
    const shown = cells.slice(0, points.length - first);
    markers.splice(first, shown.length, ...shown);
  }

  return [
    axis.join("").trimEnd(),
    `${bars}  ${wholeNumber(lowest)}–${wholeNumber(highest)} $/MWh`,
    markers.join("").trimEnd(),
  ];
}

/** A table boxed like Rich's default style, with a heavy header. */
function table(headers: string[], rows: string[][]): string[] {
  const widths = headers.map((h, c) => Math.max(h.length, ...rows.map((r) => r[c].length)));
  const rule = (left: string, fill: string, mid: string, right: string) =>
    left + widths.map((w) => fill.repeat(w + 2)).join(mid) + right;
  const row = (cells: string[], edge: string) => edge + cells.map((cell, c) => ` ${cell.padEnd(widths[c])} `).join(edge) + edge;
  return [
    rule("┏", "━", "┳", "┓"),
    row(headers, "┃"),
    rule("┡", "━", "╇", "┩"),
    ...rows.map((r) => row(r, "│")),
    rule("└", "─", "┴", "┘"),
  ];
}

/**
 * What the CLI prints for people: warnings, a summary line, the headline, an hourly
 * chart, and the ranked windows.
 *
 * @param now Current time in ms since epoch, for "in 20h" in the headline.
 */
export function formatCliTable(response: WindowsResponse, forecast: ForecastResponse, now: number, zone: ZoneOption = {}): string {
  const lines: string[] = [];
  if (response.data_source === SYNTHETIC_SOURCE) lines.push("Synthetic data: made-up prices, not real CAISO data.");
  if (response.stale) lines.push("Stale forecast: the API couldn't refresh it recently.");
  lines.push(
    `Site ${response.region} · forecast from ${formatCliTime(new Date(response.generated_at), zone)} · ` +
      `running now: ${wholeNumber(response.baseline.avg_price_usd_per_mwh)} $/MWh (${formatUsd(response.baseline.cost_usd)})`,
    "",
    headline(response, now, zone),
    "",
    ...chart(forecast, response, zone),
    ...table(
      ["Rank", "Start", "End", "Avg $/MWh", "Cost", "Saved"],
      response.windows.map((w) => [
        String(w.rank),
        formatCliTime(new Date(w.start), zone),
        formatCliTime(new Date(w.end), zone),
        wholeNumber(w.avg_price_usd_per_mwh),
        formatUsd(w.cost_usd),
        formatUsd(w.saved_usd),
      ]),
    ),
  );
  return lines.join("\n");
}

/** What `carbon-windows best --json` prints for coding agents: the API response, indented. */
export function formatCliJson(response: WindowsResponse): string {
  return JSON.stringify(response, null, 2);
}
