// Display formatting. Times render in the viewer's own time zone unless `timeZone` is passed
// (tests pin it so results don't depend on the machine).

import { HOUR_MS } from "@/lib/config";

export interface ZoneOption {
  timeZone?: string;
}

function parts(time: Date, options: Intl.DateTimeFormatOptions, { timeZone }: ZoneOption) {
  const formatted = new Intl.DateTimeFormat("en-US", { ...options, timeZone }).formatToParts(time);
  return Object.fromEntries(formatted.map((p) => [p.type, p.value]));
}

/** Clock time like "11 AM" or "2:30 PM"; minutes only when they aren't zero. */
export function formatClock(time: Date, zone: ZoneOption = {}): string {
  const { hour, minute, dayPeriod } = parts(time, { hour: "numeric", minute: "2-digit", hour12: true }, zone);
  return minute === "00" ? `${hour} ${dayPeriod}` : `${hour}:${minute} ${dayPeriod}`;
}

/** Short weekday, e.g. "Thu". */
export function formatWeekday(time: Date, zone: ZoneOption = {}): string {
  return parts(time, { weekday: "short" }, zone).weekday;
}

/** Day and time like "Thu 11 AM". */
export function formatDayTime(time: Date, zone: ZoneOption = {}): string {
  return `${formatWeekday(time, zone)} ${formatClock(time, zone)}`;
}

/** A start–end range like "Thu 11 AM – 3 PM", or "Thu 10 PM – Fri 2 AM" across midnight. */
export function formatRange(start: Date, end: Date, zone: ZoneOption = {}): string {
  const sameDay = formatWeekday(start, zone) === formatWeekday(end, zone) && end.getTime() - start.getTime() < 24 * HOUR_MS;
  return `${formatDayTime(start, zone)} – ${sameDay ? formatClock(end, zone) : formatDayTime(end, zone)}`;
}

/** Weekday and 24-hour time like "Thu 14:00", the format the carbon CLI prints. */
export function formatCliTime(time: Date, zone: ZoneOption = {}): string {
  const { weekday, hour, minute } = parts(time, { weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, zone);
  return `${weekday} ${hour}:${minute}`;
}

/** Short time zone name like "PDT". */
export function formatZoneName(time: Date, zone: ZoneOption = {}): string {
  return parts(time, { timeZoneName: "short" }, zone).timeZoneName;
}

/** Elapsed time like "just now", "14 min ago", "3 h ago", or "2 days ago". */
export function formatAge(since: Date, now: number): string {
  const minutes = Math.max(0, Math.floor((now - since.getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} days ago`;
}

/** Whole-number intensity with thousands separators, e.g. "1,204". */
export function formatIntensity(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

/** Absolute percent, e.g. 59 → "59%". The caller words the direction ("less"/"more"). */
export function formatPct(value: number): string {
  return `${Math.abs(Math.round(value))}%`;
}

/** Hours as a short duration, e.g. 4 → "4h". */
export function formatHours(hours: number): string {
  return `${hours}h`;
}

/**
 * Local wall-clock value for an `<input type="datetime-local">`, e.g. "2026-10-23T18:00".
 * Uses the viewer's time zone, which is what the input displays.
 */
export function toDateTimeLocal(time: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${time.getFullYear()}-${pad(time.getMonth() + 1)}-${pad(time.getDate())}T${pad(time.getHours())}:${pad(time.getMinutes())}`;
}

/** ISO 8601 with the viewer's UTC offset, e.g. "2026-10-23T18:00-07:00". Unambiguous for the CLI. */
export function toOffsetIso(time: Date): string {
  const offset = -time.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${toDateTimeLocal(time)}${sign}${pad(offset / 60)}:${pad(offset % 60)}`;
}
