import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import { createCarbonV1Client, toForecast, toSites, toWindows } from "@/lib/api/carbon-v1";

const v1Windows = {
  location: "fresno-305-west-napa-avenue",
  generated_at: "2026-11-17T20:00:00Z",
  data_source: "caiso-day-ahead",
  stale: false,
  request: { duration_hours: 4, max_delay_hours: 10, kw: 8 },
  run_now_avg: 40,
  run_now_cost_usd: 1.28,
  best: { start: "2026-11-18T01:00:00Z", end: "2026-11-18T05:00:00Z", wait_minutes: 300, avg: 10, cost_usd: 0.32, savings_usd: 0.96 },
  alternatives: [
    { start: "2026-11-18T03:00:00Z", end: "2026-11-18T07:00:00Z", wait_minutes: 420, avg: 25, cost_usd: 0.8, savings_usd: 0.48 },
  ],
  warnings: [] as string[],
};

describe("carbon-v1 adapter", () => {
  it("maps forecast rows to hourly points and passes the data source and kind through", () => {
    const out = toForecast("fresno", {
      location: "fresno",
      generated_at: "g",
      data_source: "caiso-day-ahead",
      stale: true,
      rows: [
        { ts: "2026-11-17T20:00:00Z", price: 25.5, kind: "published" },
        { ts: "2026-11-17T21:00:00Z", price: -4, kind: "forecast" },
      ],
    });
    expect(out).toMatchObject({ region: "fresno", stale: true, data_source: "caiso-day-ahead" });
    expect(out.points).toEqual([
      { start: "2026-11-17T20:00:00Z", price: 25.5, kind: "published" },
      { start: "2026-11-17T21:00:00Z", price: -4, kind: "forecast" },
    ]);
  });

  it("labels synthetic data as synthetic rather than as a live model", () => {
    const out = toForecast("x", { location: "x", generated_at: "g", data_source: "synthetic", stale: false, rows: [] });
    expect(out.data_source).toBe("synthetic");
  });

  it("maps the campus list", () => {
    expect(toSites({ sites: [{ location: "a", name: "305 West Napa Avenue", city: "Fresno" }] })).toEqual([
      { id: "a", name: "305 West Napa Avenue", city: "Fresno" },
    ]);
  });

  it("keeps the shared campus request when one caller cancels", async () => {
    const payload = { sites: [{ location: "fresno", name: "Test campus", city: "Fresno" }] };
    const fetchSites = vi.fn().mockResolvedValue(Response.json(payload));
    vi.stubGlobal("fetch", fetchSites);
    try {
      const client = createCarbonV1Client("");
      const controller = new AbortController();
      const canceled = client.getSites(controller.signal);
      const active = client.getSites();
      controller.abort();
      await expect(canceled).rejects.toThrow();
      await expect(active).resolves.toEqual(toSites(payload));
      expect(fetchSites).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("ranks best first, then alternatives, and derives the run-now baseline", () => {
    const out = toWindows("x", "2026-11-18T12:00:00Z", v1Windows);
    expect(out.windows.map((w) => [w.rank, w.avg_price_usd_per_mwh, w.cost_usd, w.saved_usd, w.saved_usd_per_mwh])).toEqual([
      [1, 10, 0.32, 0.96, 30],
      [2, 25, 0.8, 0.48, 15],
    ]);
    expect(out.baseline).toEqual({
      start: "2026-11-17T20:00:00.000Z",
      end: "2026-11-18T00:00:00.000Z",
      avg_price_usd_per_mwh: 40,
      cost_usd: 1.28,
    });
    expect(out.job).toEqual({ duration_hours: 4, kw: 8, deadline: "2026-11-18T12:00:00.000Z", deadline_clamped: false });
    expect(out.data_source).toBe("caiso-day-ahead");
  });

  it("reports a clamped deadline as the end of the last possible window", () => {
    const out = toWindows("x", "2026-12-01T00:00:00Z", { ...v1Windows, warnings: ["wait_clamped_to_horizon"] });
    expect(out.job.deadline_clamped).toBe(true);
    expect(out.job.deadline).toBe("2026-11-18T10:00:00.000Z");
  });
});

// The API's own example responses (generated from the real code by scripts/make_fixtures.py), so a
// contract change on the backend breaks this test instead of the dashboard.
const FIXTURES = fileURLToPath(new URL("../../../fixtures/", import.meta.url));
const haveFixtures = existsSync(`${FIXTURES}windows_ok.json`);

describe.skipIf(!haveFixtures)("carbon-v1 adapter against the API's example responses", () => {
  const read = (name: string) => JSON.parse(readFileSync(`${FIXTURES}${name}`, "utf8"));

  it("maps a real forecast response", () => {
    const out = toForecast("demo", read("forecast_ok.json"));
    expect(out.points.length).toBeGreaterThan(0);
    for (const p of out.points) {
      expect(Number.isFinite(p.price)).toBe(true);
      expect(Number.isNaN(Date.parse(p.start))).toBe(false);
    }
    expect(["synthetic", "caiso-day-ahead"]).toContain(out.data_source);
  });

  it("maps a real windows response, with dollars and a baseline", () => {
    const api = read("windows_ok.json");
    const out = toWindows("demo", "2099-01-01T00:00:00Z", api);
    expect(out.windows[0].cost_usd).toBe(api.best.cost_usd);
    expect(out.windows[0].saved_usd).toBe(api.best.savings_usd);
    expect(out.baseline.cost_usd).toBe(api.run_now_cost_usd);
    expect(out.job.kw).toBe(api.request.kw);
    expect(Date.parse(out.baseline.start)).toBeLessThanOrEqual(Date.parse(out.windows[0].start));
  });
});
