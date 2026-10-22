import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMockClient } from "@/lib/api/client";
import { HOUR_MS } from "@/lib/config";

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
  it("answers in the CLI's JSON shape", async () => {
    const response = await settle(
      createMockClient().getWindows({ region: "CISO", durationHours: 4, deadline: new Date(NOW + 24 * HOUR_MS).toISOString() }),
    );
    expect(response.job).toEqual({ duration_hours: 4, deadline: new Date(NOW + 24 * HOUR_MS).toISOString(), deadline_clamped: false });
    expect(response.windows.map((w) => w.rank)).toEqual([1, 2, 3]);
    expect(response.baseline.avg_intensity_g_per_kwh).toBeGreaterThan(0);
    expect(response.data_source).toBe("synthetic");
  });

  it("clamps a deadline past the end of the forecast", async () => {
    const response = await settle(
      createMockClient().getWindows({ region: "CISO", durationHours: 4, deadline: new Date(NOW + 100 * HOUR_MS).toISOString() }),
    );
    expect(response.job.deadline_clamped).toBe(true);
    expect(Date.parse(response.job.deadline)).toBeLessThan(NOW + 49 * HOUR_MS);
  });

  it("fails on purpose in the error scenario", async () => {
    const request = createMockClient("error").getForecast("CISO");
    const assertion = expect(request).rejects.toThrow(/scenario=error/);
    await vi.runAllTimersAsync();
    await assertion;
  });

  it("serves a stale forecast in the stale scenario", async () => {
    const response = await settle(createMockClient("stale").getForecast("CISO"));
    expect(response.stale).toBe(true);
  });
});
