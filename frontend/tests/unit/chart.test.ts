import { describe, expect, it } from "vitest";
import { clamp, yTicks, yTicksRange } from "@/lib/chart";

describe("yTicks", () => {
  it("covers the maximum with clean steps", () => {
    expect(yTicks(340, 4)).toEqual([0, 100, 200, 300, 400]);
  });

  it("uses 2.5 steps when they fit better", () => {
    expect(yTicks(95, 4)).toEqual([0, 25, 50, 75, 100]);
  });

  it("handles an all-zero series", () => {
    expect(yTicks(0, 4)).toEqual([0, 1]);
  });
});

describe("yTicksRange", () => {
  it("matches yTicks when nothing is negative", () => {
    expect(yTicksRange(0, 340, 4)).toEqual(yTicks(340, 4));
  });

  it("extends below zero and keeps zero as a tick", () => {
    const ticks = yTicksRange(-22, 60, 4);
    expect(ticks[0]).toBeLessThanOrEqual(-22);
    expect(ticks.at(-1)).toBeGreaterThanOrEqual(60);
    expect(ticks).toContain(0);
  });

  it("is ascending with even steps", () => {
    const ticks = yTicksRange(-30, 45, 4);
    const steps = ticks.slice(1).map((t, i) => t - ticks[i]);
    expect(new Set(steps).size).toBe(1);
    expect(steps[0]).toBeGreaterThan(0);
  });
});

describe("clamp", () => {
  it("keeps values inside the range", () => {
    expect(clamp(-2, 0, 10)).toBe(0);
    expect(clamp(12, 0, 10)).toBe(10);
    expect(clamp(4, 0, 10)).toBe(4);
  });
});
