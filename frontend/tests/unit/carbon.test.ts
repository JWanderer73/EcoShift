import { describe, expect, it } from "vitest";
import type { ForecastPoint } from "@/lib/api/types";
import { averagePrice, findBestWindows, forecastEnd, indexOfTime, jobCostUsd, lastStartIndex, savedPerMwh, verdictFor } from "@/lib/carbon";
import { HOUR_MS } from "@/lib/config";

const START = Date.parse("2026-10-21T18:00:00Z");

function forecast(values: number[]): ForecastPoint[] {
  return values.map((price, i) => ({ start: new Date(START + i * HOUR_MS).toISOString(), price }));
}

function hoursFromStart(hours: number): Date {
  return new Date(START + hours * HOUR_MS);
}

function startIndexes(points: ForecastPoint[], windows: { start: string }[]): number[] {
  return windows.map((w) => indexOfTime(points, w.start));
}

describe("averagePrice", () => {
  it("averages the hours the job covers", () => {
    expect(averagePrice(forecast([100, 200, 300, 400]), 1, 2)).toBe(250);
  });

  it("rejects a job that runs past the forecast", () => {
    expect(() => averagePrice(forecast([100, 200]), 1, 2)).toThrow(RangeError);
  });
});

describe("savedPerMwh", () => {
  it("is positive when the window is cheaper than the baseline", () => {
    expect(savedPerMwh(40, 15)).toBe(25);
  });

  it("is negative when the window is dearer", () => {
    expect(savedPerMwh(20, 30)).toBe(-10);
  });

  it("handles prices below zero", () => {
    expect(savedPerMwh(30, -10)).toBe(40);
  });
});

describe("jobCostUsd", () => {
  it("is price x kWh / 1000", () => {
    expect(jobCostUsd(40, 8, 4)).toBeCloseTo(1.28, 10);
  });

  it("is negative when prices are, meaning the job is paid to run", () => {
    expect(jobCostUsd(-10, 8, 4)).toBeCloseTo(-0.32, 10);
  });
});

describe("lastStartIndex", () => {
  it("ends the job inside the forecast when the deadline is later", () => {
    expect(lastStartIndex(forecast([1, 1, 1, 1, 1]), 2, hoursFromStart(100))).toBe(3);
  });

  it("only counts whole hours before the deadline", () => {
    expect(lastStartIndex(forecast([1, 1, 1, 1, 1, 1, 1, 1]), 2, hoursFromStart(5.5))).toBe(3);
  });

  it("is negative when the job can't finish in time", () => {
    expect(lastStartIndex(forecast([1, 1, 1, 1]), 3, hoursFromStart(2))).toBeLessThan(0);
  });
});

describe("findBestWindows", () => {
  const points = forecast([300, 300, 100, 100, 300, 300, 50, 50]);

  it("ranks the cheapest non-overlapping windows first", () => {
    const windows = findBestWindows(points, 2, hoursFromStart(8), 3);
    // Hour 5 (avg 175) overlaps the best window and hours 1 and 3 overlap the second, so the
    // third pick falls to the next distinct option. Hours 0 and 4 tie; the earlier one wins.
    expect(startIndexes(points, windows)).toEqual([6, 2, 0]);
  });

  it("reports averages, job cost and dollars saved against starting now", () => {
    // Starting now averages 300 $/MWh; the best window averages 50. At 8 kW for 2 h that is 16 kWh.
    const [best] = findBestWindows(points, 2, hoursFromStart(8), 1);
    expect(best).toEqual({
      rank: 1,
      start: points[6].start,
      end: new Date(START + 8 * HOUR_MS).toISOString(),
      avg_price_usd_per_mwh: 50,
      cost_usd: 0.8,
      saved_usd: 4,
      saved_usd_per_mwh: 250,
    });
  });

  it("uses the power draw it is given", () => {
    const [best] = findBestWindows(points, 2, hoursFromStart(8), 1, 100);
    expect(best.cost_usd).toBe(10);
    expect(best.saved_usd).toBe(50);
  });

  it("can pick a window with negative prices and prices it below zero", () => {
    const negative = forecast([30, 30, -20, -10, 30, 30]);
    const [best] = findBestWindows(negative, 2, hoursFromStart(6), 1);
    expect(best.start).toBe(negative[2].start);
    expect(best.avg_price_usd_per_mwh).toBe(-15);
    expect(best.cost_usd).toBe(-0.24);
    expect(best.saved_usd).toBe(0.72);
  });

  it("numbers the ranks from 1", () => {
    expect(findBestWindows(points, 2, hoursFromStart(8), 3).map((w) => w.rank)).toEqual([1, 2, 3]);
  });

  it("never returns a window that ends after the deadline", () => {
    const windows = findBestWindows(points, 2, hoursFromStart(6), 3);
    expect(startIndexes(points, windows)[0]).toBe(2);
    for (const w of windows) expect(Date.parse(w.end)).toBeLessThanOrEqual(START + 6 * HOUR_MS);
  });

  it("never returns overlapping windows", () => {
    const valley = forecast([5, 4, 3, 2, 1, 2, 3, 4, 5, 6]);
    const windows = findBestWindows(valley, 3, hoursFromStart(10), 3);
    const starts = startIndexes(valley, windows).sort((a, b) => a - b);
    for (let i = 1; i < starts.length; i++) expect(starts[i] - starts[i - 1]).toBeGreaterThanOrEqual(3);
  });

  it("returns nothing when the deadline is too soon", () => {
    expect(findBestWindows(points, 4, hoursFromStart(3), 3)).toEqual([]);
  });

  it("returns fewer windows when fewer fit", () => {
    expect(findBestWindows(points, 4, hoursFromStart(8), 3)).toHaveLength(2);
  });
});

describe("forecastEnd", () => {
  it("is the end of the last hour", () => {
    expect(forecastEnd(forecast([1, 1, 1]))).toBe(START + 3 * HOUR_MS);
  });
});

describe("verdictFor", () => {
  it("says wait when the saving is large", () => {
    expect(verdictFor(25)).toBe("wait");
  });

  it("flags a small gain in between", () => {
    expect(verdictFor(7)).toBe("small-gain");
  });

  it("says run now when waiting barely helps", () => {
    expect(verdictFor(2)).toBe("run-now");
  });

  it("says run now when waiting would cost more", () => {
    expect(verdictFor(-8)).toBe("run-now");
  });
});
