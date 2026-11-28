import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockClient } from "@/lib/api/client";
import { HOUR_MS } from "@/lib/config";
import { SAMPLE_SITES } from "@/lib/regions";

const SITE = SAMPLE_SITES[0].id;

const NOW = Date.parse("2026-10-21T18:24:00-07:00");

beforeEach(() => {
  vi.useFakeTimers({ now: NOW });
});

afterEach(() => {
  vi.useRealTimers();
});

async function settle<T>(promise: Promise<T>): Promise<T> {
  await vi.runAllTimersAsync();
  return promise;
}

describe("mock client", () => {
  it("answers in the shape of the real API", async () => {
    const response = await settle(
      createMockClient().getWindows({ region: SITE, durationHours: 4, deadline: new Date(NOW + 24 * HOUR_MS).toISOString() }),
    );
    expect(response.job).toEqual({ duration_hours: 4, kw: 8, deadline: new Date(NOW + 24 * HOUR_MS).toISOString(), deadline_clamped: false });
    expect(response.windows.map((w) => w.rank)).toEqual([1, 2, 3]);
    expect(Number.isFinite(response.baseline.avg_price_usd_per_mwh)).toBe(true);
    expect(response.baseline.cost_usd).toBeCloseTo((response.baseline.avg_price_usd_per_mwh * 8 * 4) / 1000, 1);
    expect(response.data_source).toBe("synthetic");
  });

  it("clamps a deadline past the end of the forecast", async () => {
    const response = await settle(
      createMockClient().getWindows({ region: SITE, durationHours: 4, deadline: new Date(NOW + 200 * HOUR_MS).toISOString() }),
    );
    expect(response.job.deadline_clamped).toBe(true);
    expect(Date.parse(response.job.deadline)).toBeLessThan(NOW + 121 * HOUR_MS);
  });

  it("fails on purpose in the error scenario", async () => {
    const request = createMockClient("error").getForecast(SITE);
    const assertion = expect(request).rejects.toThrow(/scenario=error/);
    await vi.runAllTimersAsync();
    await assertion;
  });

  it("serves a stale forecast in the stale scenario", async () => {
    const response = await settle(createMockClient("stale").getForecast(SITE));
    expect(response.stale).toBe(true);
  });
});

describe("mock sites", () => {
  it("lists the sample campuses", async () => {
    const sites = await createMockClient().getSites();
    expect(sites.map((s) => s.id)).toContain(SITE);
  });
});
