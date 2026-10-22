import { describe, expect, it } from "vitest";
import type { ForecastPoint } from "@/lib/api/types";
import { averageIntensity, findBestWindows, forecastEnd, indexOfTime, lastStartIndex, savedPct, verdictFor } from "@/lib/carbon";
import { HOUR_MS } from "@/lib/config";

const START = Date.parse("2026-10-21T18:00:00Z");

function forecast(values: number[]): ForecastPoint[] {
  return values.map((intensity, i) => ({ start: new Date(START + i * HOUR_MS).toISOString(), intensity }));
}

function hoursFromStart(hours: number): Date {
  return new Date(START + hours * HOUR_MS);
}

function startIndexes(points: ForecastPoint[], windows: { start: string }[]): number[] {
  return windows.map((w) => indexOfTime(points, w.start));
}

describe("averageIntensity", () => {
  it("averages the hours the job covers", () => {
    expect(averageIntensity(forecast([100, 200, 300, 400]), 1, 2)).toBe(250);
  });

  it("rejects a job that runs past the forecast", () => {
    expect(() => averageIntensity(forecast([100, 200]), 1, 2)).toThrow(RangeError);
  });
});

describe("savedPct", () => {
  it("is positive when the window is cleaner than the baseline", () => {
    expect(savedPct(300, 75)).toBe(75);
  });

  it("is negative when the window is dirtier", () => {
    expect(savedPct(200, 300)).toBe(-50);
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

  it("ranks the cleanest non-overlapping windows first", () => {
    const windows = findBestWindows(points, 2, hoursFromStart(8), 3);
    // Hour 5 (avg 175) overlaps the best window and hours 1 and 3 overlap the second, so the
    // third pick falls to the next distinct option. Hours 0 and 4 tie; the earlier one wins.
    expect(startIndexes(points, windows)).toEqual([6, 2, 0]);
  });

  it("reports averages and savings against starting now, to one decimal", () => {
    const [best] = findBestWindows(points, 2, hoursFromStart(8), 1);
    expect(best).toEqual({
      rank: 1,
      start: points[6].start,
      end: new Date(START + 8 * HOUR_MS).toISOString(),
      avg_intensity_g_per_kwh: 50,
      co2_saved_pct: 83.3,
    });
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
  it("says wait when the savings are large", () => {
    expect(verdictFor(59)).toBe("wait");
  });

  it("flags a small gain in between", () => {
    expect(verdictFor(10)).toBe("small-gain");
  });

  it("says run now when waiting barely helps", () => {
    expect(verdictFor(2)).toBe("run-now");
  });
});
