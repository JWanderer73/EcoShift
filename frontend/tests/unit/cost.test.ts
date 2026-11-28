import { describe, expect, it } from "vitest";
import type { ForecastPoint } from "@/lib/api/types";
import { HOUR_MS } from "@/lib/config";
import { dollarsSaved, findCheapestWindows, hasPrices, hourlyCost, jobDollars, jobStats } from "@/lib/cost";

const START = Date.parse("2026-10-21T00:00:00Z");

function forecast(rows: [price: number | undefined, intensity: number][]): ForecastPoint[] {
  return rows.map(([price, intensity], i) => ({ start: new Date(START + i * HOUR_MS).toISOString(), intensity, price }));
}

const hoursFromStart = (h: number) => new Date(START + h * HOUR_MS);

describe("hourlyCost", () => {
  it("adds carbon at $/t to the $/MWh price", () => {
    // 400 gCO₂/kWh = 0.4 t/MWh; at $100/t that's $40/MWh on top of $50.
    expect(hourlyCost({ start: "", price: 50, intensity: 400 }, 100)).toBe(90);
  });

  it("is the price alone when carbon is free", () => {
    expect(hourlyCost({ start: "", price: -12, intensity: 400 }, 0)).toBe(-12);
  });
});

describe("findCheapestWindows", () => {
  // Hour 2 is cheap but dirty; hour 4 is a little pricier but clean.
  const points = forecast([
    [80, 300],
    [80, 300],
    [20, 800],
    [80, 300],
    [40, 50],
    [80, 300],
  ]);

  it("ranks by price alone at a $0 carbon price", () => {
    const [best] = findCheapestWindows(points, 1, hoursFromStart(6), 1, 0);
    expect(best.startIndex).toBe(2);
  });

  it("moves to cleaner hours as the carbon price rises", () => {
    const [best] = findCheapestWindows(points, 1, hoursFromStart(6), 1, 100);
    // Hour 2: 20 + 80 = $100/MWh. Hour 4: 40 + 5 = $45/MWh.
    expect(best.startIndex).toBe(4);
    expect(best.avgCost).toBe(45);
    expect(best.co2SavedPct).toBeCloseTo((250 / 300) * 100);
  });

  it("falls back to carbon when the forecast has no prices", () => {
    const unpriced = forecast([
      [undefined, 300],
      [undefined, 100],
      [undefined, 200],
    ]);
    expect(hasPrices(unpriced)).toBe(false);
    const [best] = findCheapestWindows(unpriced, 1, hoursFromStart(3), 1, 0);
    expect(best.startIndex).toBe(1);
    expect(best.avgCost).toBeNull();
    expect(best.costSavedPct).toBeNull();
  });

  it("returns nothing when the deadline is too soon", () => {
    expect(findCheapestWindows(points, 4, hoursFromStart(3), 3, 50)).toEqual([]);
  });
});

describe("dollars", () => {
  it("scales $/MWh by power and hours", () => {
    expect(jobDollars(50, 2, 4)).toBe(400);
  });

  it("measures savings against the baseline job", () => {
    const points = forecast([
      [100, 0],
      [60, 0],
    ]);
    const now = jobStats(points, 0, 1, 0);
    const later = jobStats(points, 1, 1, 0);
    expect(dollarsSaved(now, later, 10, 1)).toBe(400);
    expect(dollarsSaved(later, now, 10, 1)).toBe(-400);
  });
});
