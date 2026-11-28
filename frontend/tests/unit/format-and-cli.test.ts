// Runs in America/Los_Angeles (see vitest.config.ts), so local times below are Pacific.
import { describe, expect, it } from "vitest";
import type { ForecastResponse, WindowsResponse } from "@/lib/api/types";
import { buildCliCommand, formatCliJson, formatCliTable } from "@/lib/cli";
import { deadlinePresets } from "@/lib/deadline";
import {
  formatAge,
  formatCliTime,
  formatClock,
  formatDayTime,
  formatPrice,
  formatPriceShort,
  formatRange,
  formatUsd,
  formatZoneName,
  toDateTimeLocal,
  toOffsetIso,
} from "@/lib/format";

const THU_11AM = new Date("2026-10-22T11:00:00-07:00");

describe("time formatting", () => {
  it("drops zero minutes", () => {
    expect(formatClock(THU_11AM)).toBe("11 AM");
    expect(formatClock(new Date("2026-10-22T14:30:00-07:00"))).toBe("2:30 PM");
  });

  it("prefixes the weekday", () => {
    expect(formatDayTime(THU_11AM)).toBe("Thu 11 AM");
  });

  it("shows the day once for a same-day range", () => {
    expect(formatRange(THU_11AM, new Date("2026-10-22T15:00:00-07:00"))).toBe("Thu 11 AM – 3 PM");
  });

  it("shows both days when a range crosses midnight", () => {
    expect(formatRange(new Date("2026-10-22T22:00:00-07:00"), new Date("2026-10-23T02:00:00-07:00"))).toBe(
      "Thu 10 PM – Fri 2 AM",
    );
  });

  it("honours an explicit time zone", () => {
    expect(formatDayTime(THU_11AM, { timeZone: "America/New_York" })).toBe("Thu 2 PM");
  });

  it("uses 24-hour time and a zone name for CLI output", () => {
    expect(formatCliTime(new Date("2026-10-22T14:00:00-07:00"))).toBe("Thu 14:00");
    expect(formatCliTime(new Date("2026-10-23T00:00:00-07:00"))).toBe("Fri 00:00");
    expect(formatZoneName(THU_11AM)).toBe("PDT");
  });
});

describe("price formatting", () => {
  it("formats $/MWh with two decimals", () => {
    expect(formatPrice(38.4)).toBe("$38.40");
    expect(formatPrice(1234.5)).toBe("$1,234.50");
  });

  it("uses a real minus sign for negative prices", () => {
    expect(formatPrice(-12)).toBe("−$12.00");
    expect(formatUsd(-0.4)).toBe("−$0.40");
  });

  it("rounds axis labels to whole numbers", () => {
    expect(formatPriceShort(38.4)).toBe("38");
    expect(formatPriceShort(-12.6)).toBe("−13");
    expect(formatPriceShort(0)).toBe("0");
  });
});

describe("formatAge", () => {
  const now = Date.parse("2026-10-21T18:00:00Z");
  const ago = (minutes: number) => new Date(now - minutes * 60_000);

  it.each([
    [0, "just now"],
    [14, "14 min ago"],
    [185, "3 h ago"],
    [60 * 50, "2 days ago"],
  ])("%i minutes → %s", (minutes, expected) => {
    expect(formatAge(ago(minutes), now)).toBe(expected);
  });
});

describe("datetime values", () => {
  it("fills a datetime-local input in local time", () => {
    expect(toDateTimeLocal(THU_11AM)).toBe("2026-10-22T11:00");
  });

  it("adds the UTC offset for the CLI", () => {
    expect(toOffsetIso(THU_11AM)).toBe("2026-10-22T11:00-07:00");
  });
});

describe("buildCliCommand", () => {
  it("mirrors the planner's campus, length and deadline", () => {
    expect(buildCliCommand({ region: "fresno-1", durationHours: 4, deadline: new Date("2026-10-23T18:00:00-07:00") })).toBe(
      "carbon-windows best --duration 4 --deadline 2026-10-23T18:00-07:00 --location fresno-1",
    );
  });

  it("leaves out the deadline when it's the end of the forecast, the CLI's default", () => {
    expect(buildCliCommand({ region: "fresno-1", durationHours: 2, deadline: null })).toBe("carbon-windows best --duration 2 --location fresno-1");
    expect(buildCliCommand({ region: "fresno-1", durationHours: 2, kw: 40, deadline: null })).toBe(
      "carbon-windows best --duration 2 --kw 40 --location fresno-1",
    );
  });
});

describe("deadlinePresets", () => {
  it("offers midnight tonight and 9 AM tomorrow, local time", () => {
    const presets = deadlinePresets(new Date("2026-10-22T14:00:00-07:00"));
    expect(presets.map((p) => [p.label, toDateTimeLocal(p.time)])).toEqual([
      ["Midnight", "2026-10-23T00:00"],
      ["Tomorrow 9 AM", "2026-10-23T09:00"],
    ]);
  });

  it("keeps wall-clock times across a DST change", () => {
    // Clocks fall back at 2 AM on Sun Nov 1, 2026 in Los Angeles.
    const [, morning] = deadlinePresets(new Date("2026-10-31T20:00:00-07:00"));
    expect(toOffsetIso(morning.time)).toBe("2026-11-01T09:00-08:00");
  });
});

describe("CLI output", () => {
  // Six hours from Thu 11 AM; a 2h job's best window is 1–3 PM.
  const start = Date.parse("2026-10-22T11:00:00-07:00");
  const hour = (h: number) => new Date(start + h * 3_600_000).toISOString();
  const forecast: ForecastResponse = {
    region: "fresno-1",
    generated_at: hour(0),
    stale: false,
    data_source: "synthetic",
    points: [30, 20, 10, 15, 25, 30].map((price, h) => ({ start: hour(h), price })),
  };
  const response: WindowsResponse = {
    region: "fresno-1",
    generated_at: hour(0),
    stale: false,
    data_source: "synthetic",
    job: { duration_hours: 2, kw: 8, deadline: hour(6), deadline_clamped: false },
    baseline: { start: hour(0), end: hour(2), avg_price_usd_per_mwh: 25, cost_usd: 0.4 },
    windows: [
      { rank: 1, start: hour(2), end: hour(4), avg_price_usd_per_mwh: 12.5, cost_usd: 0.2, saved_usd: 0.2, saved_usd_per_mwh: 12.5 },
      { rank: 2, start: hour(4), end: hour(6), avg_price_usd_per_mwh: 27.5, cost_usd: 0.44, saved_usd: -0.04, saved_usd_per_mwh: -2.5 },
    ],
  };

  it("prints the summary, price chart and ranked windows", () => {
    expect(formatCliTable(response, forecast, Date.parse("2026-10-22T11:30:00-07:00"))).toBe(
      [
        "Synthetic data: made-up prices, not real CAISO data.",
        "Site fresno-1 · forecast from Thu 11:00 · running now: 25 $/MWh ($0.40)",
        "",
        "Best: Thu 13:00–15:00 PDT (in 1h 30m) · saves $0.20 vs running now",
        "",
        "Thu 11:00",
        "█▅▁▃▆█  10–30 $/MWh",
        "  1┘2┘",
        "┏━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┓",
        "┃ Rank ┃ Start     ┃ End       ┃ Avg $/MWh ┃ Cost  ┃ Saved  ┃",
        "┡━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━┩",
        "│ 1    │ Thu 13:00 │ Thu 15:00 │ 12        │ $0.20 │ $0.20  │",
        "│ 2    │ Thu 15:00 │ Thu 17:00 │ 28        │ $0.44 │ −$0.04 │",
        "└──────┴───────────┴───────────┴───────────┴───────┴────────┘",
      ].join("\n"),
    );
  });

  it("prints the API response as indented JSON for agents", () => {
    expect(JSON.parse(formatCliJson(response))).toEqual(response);
    expect(formatCliJson(response)).toContain('\n  "region": "fresno-1"');
  });
});
