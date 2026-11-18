import { describe, expect, it } from "vitest";
import { clamp, yTicks } from "@/lib/chart";

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

describe("clamp", () => {
  it("keeps values inside the range", () => {
    expect(clamp(-2, 0, 10)).toBe(0);
    expect(clamp(12, 0, 10)).toBe(10);
    expect(clamp(4, 0, 10)).toBe(4);
  });
});
