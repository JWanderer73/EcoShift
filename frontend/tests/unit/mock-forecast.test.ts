import { describe, expect, it } from "vitest";
import { SYNTHETIC_SOURCE } from "@/lib/api/types";
import { FORECAST_HORIZON_HOURS, HOUR_MS } from "@/lib/config";
import { generateMockForecast, startOfHour } from "@/lib/mock/forecast";
import { SAMPLE_SITES } from "@/lib/regions";

const NOW = Date.parse("2026-10-21T18:24:00-07:00");
const SITE = SAMPLE_SITES[0].id;

describe("generateMockForecast", () => {
  it("returns consecutive hourly points starting at the current hour", () => {
    const { points } = generateMockForecast(SITE, NOW);
    expect(points).toHaveLength(FORECAST_HORIZON_HOURS);
    expect(Date.parse(points[0].start)).toBe(startOfHour(NOW));
    for (let i = 1; i < points.length; i++) {
      expect(Date.parse(points[i].start) - Date.parse(points[i - 1].start)).toBe(HOUR_MS);
    }
  });

  it("gives the same numbers for the same site and hour", () => {
    const later = NOW + 20 * 60 * 1000;
    expect(generateMockForecast(SAMPLE_SITES[1].id, later).points).toEqual(generateMockForecast(SAMPLE_SITES[1].id, NOW).points);
  });

  it("produces finite prices in a plausible range for every site, negatives allowed", () => {
    for (const { id } of SAMPLE_SITES) {
      for (const { price } of generateMockForecast(id, NOW).points) {
        expect(Number.isFinite(price)).toBe(true);
        expect(price).toBeGreaterThanOrEqual(-25);
        expect(price).toBeLessThan(200);
      }
    }
  });

  it("puts the cheapest hour in daylight, where solar is", () => {
    const { points } = generateMockForecast(SITE, NOW);
    const cheapest = points.reduce((a, b) => (b.price < a.price ? b : a));
    const hour = new Date(cheapest.start).getHours(); // tests run in America/Los_Angeles
    expect(hour).toBeGreaterThanOrEqual(8);
    expect(hour).toBeLessThanOrEqual(16);
  });

  it("marks the first day or so as published and the rest as forecast", () => {
    const { points } = generateMockForecast(SITE, NOW);
    expect(points[0].kind).toBe("published");
    expect(points.at(-1)?.kind).toBe("forecast");
    const firstForecast = points.findIndex((p) => p.kind === "forecast");
    expect(points.slice(firstForecast).every((p) => p.kind === "forecast")).toBe(true);
  });

  it("dates a fresh forecast within the last daily refresh", () => {
    const { generated_at, stale } = generateMockForecast(SITE, NOW);
    const age = NOW - Date.parse(generated_at);
    expect(stale).toBe(false);
    expect(age).toBeGreaterThanOrEqual(0);
    expect(age).toBeLessThan(24 * HOUR_MS);
  });

  it("marks a stale forecast and dates it several refreshes back", () => {
    const { generated_at, stale } = generateMockForecast(SITE, NOW, true);
    expect(stale).toBe(true);
    expect(NOW - Date.parse(generated_at)).toBeGreaterThan(36 * HOUR_MS);
  });

  it("labels itself as synthetic", () => {
    expect(generateMockForecast(SITE, NOW).data_source).toBe(SYNTHETIC_SOURCE);
  });

  it("rejects unknown sites", () => {
    expect(() => generateMockForecast("NOPE", NOW)).toThrow();
  });
});
