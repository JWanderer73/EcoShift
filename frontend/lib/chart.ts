/** Clamp `value` into [min, max]. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Round a raw step up to 1, 2, 2.5 or 5 times a power of ten, so axis labels are clean. */
function niceStep(raw: number): number {
  const power = 10 ** Math.floor(Math.log10(raw));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

/**
 * Evenly spaced y-axis ticks from 0 that cover `max`, about `count` intervals apart.
 *
 * @returns Ascending ticks; the last is the axis maximum.
 */
export function yTicks(max: number, count: number): number[] {
  if (max <= 0) return [0, 1];
  const step = niceStep(max / count);
  const intervals = Math.ceil(max / step);
  return Array.from({ length: intervals + 1 }, (_, i) => i * step);
}

/**
 * Evenly spaced y-axis ticks covering [min, max] and always including 0, for data that can go
 * negative (day-ahead prices do). With no negative values this is the same as `yTicks`.
 *
 * @returns Ascending ticks; the first is the axis minimum and the last the axis maximum.
 */
export function yTicksRange(min: number, max: number, count: number): number[] {
  if (min >= 0) return yTicks(max, count);
  const span = Math.max(max, 0) - min;
  const step = niceStep(span / count);
  const lowest = Math.floor(min / step);
  const highest = Math.max(Math.ceil(max / step), 1);
  return Array.from({ length: highest - lowest + 1 }, (_, i) => (lowest + i) * step);
}
