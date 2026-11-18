import { describe, expect, it } from "vitest";
import { SYNTHETIC_SOURCE } from "@/lib/api/types";
import { FORECAST_HORIZON_HOURS, HOUR_MS } from "@/lib/config";
import { generateMockForecast, startOfHour } from "@/lib/mock/forecast";
import { REGIONS } from "@/lib/regions";

const NOW = Date.parse("2026-10-21T18:24:00-07:00");

describe("generateMockForecast", () => {
  it("returns consecutive hourly points starting at the current hour", () => {
    const { points } = generateMockForecast("CISO", NOW);
    expect(points).toHaveLength(FORECAST_HORIZON_HOURS);
    expect(Date.parse(points[0].start)).toBe(startOfHour(NOW));
    for (let i = 1; i < points.length; i++) {
      expect(Date.parse(points[i].start) - Date.parse(points[i - 1].start)).toBe(HOUR_MS);
    }
  });

  it("gives the same numbers for the same region and hour", () => {
    const later = NOW + 20 * 60 * 1000;
    expect(generateMockForecast("ERCO", later).points).toEqual(generateMockForecast("ERCO", NOW).points);
  });

  it("produces positive whole numbers for every region", () => {
    for (const { code } of REGIONS) {
      for (const { intensity } of generateMockForecast(code, NOW).points) {
        expect(Number.isInteger(intensity)).toBe(true);
        expect(intensity).toBeGreaterThan(0);
      }
    }
  });

  it("puts California's cleanest hour in daylight, where solar is", () => {
    const { points } = generateMockForecast("CISO", NOW);
    const cleanest = points.reduce((a, b) => (b.intensity < a.intensity ? b : a));
    const hour = new Date(cleanest.start).getHours(); // tests run in America/Los_Angeles
    expect(hour).toBeGreaterThanOrEqual(8);
    expect(hour).toBeLessThanOrEqual(16);
  });

  it("dates a fresh forecast within the last refresh cycle", () => {
    const { generated_at, stale } = generateMockForecast("CISO", NOW);
    const age = NOW - Date.parse(generated_at);
    expect(stale).toBe(false);
    expect(age).toBeGreaterThanOrEqual(0);
    expect(age).toBeLessThan(3 * HOUR_MS);
  });

  it("marks a stale forecast and dates it several refreshes back", () => {
    const { generated_at, stale } = generateMockForecast("CISO", NOW, true);
    expect(stale).toBe(true);
    expect(NOW - Date.parse(generated_at)).toBeGreaterThan(6 * HOUR_MS);
  });

  it("labels itself as synthetic", () => {
    expect(generateMockForecast("PJM", NOW).data_source).toBe(SYNTHETIC_SOURCE);
  });

  it("rejects unknown regions", () => {
    expect(() => generateMockForecast("NOPE", NOW)).toThrow();
  });
});
