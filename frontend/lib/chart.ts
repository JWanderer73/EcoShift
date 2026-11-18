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
