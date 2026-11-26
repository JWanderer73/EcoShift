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
 * Evenly spaced y-axis ticks that cover `min` to `max`, about `count` intervals apart. Zero is
 * always a tick, so negative values (e.g. negative power prices) get ticks below it.
 *
 * @param min Lowest value to cover; values above 0 are treated as 0.
 * @returns Ascending ticks; the first is the axis minimum and the last the maximum.
 */
export function yTicks(max: number, count: number, min = 0): number[] {
  const low = Math.min(0, min);
  if (max <= 0 && low === 0) return [0, 1];
  const step = niceStep((Math.max(max, 0) - low) / count);
  const first = Math.floor(low / step);
  const last = Math.max(1, Math.ceil(max / step));
  // Multiply rather than accumulate so ticks stay exact (no 0.30000000000000004).
  return Array.from({ length: last - first + 1 }, (_, i) => (first + i) * step + 0);
}
