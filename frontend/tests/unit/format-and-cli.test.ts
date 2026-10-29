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
  formatRange,
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
  it("mirrors the planner's region, length and deadline", () => {
    expect(buildCliCommand({ region: "CISO", durationHours: 4, deadline: new Date("2026-10-23T18:00:00-07:00") })).toBe(
      "carbon windows --duration 4h --deadline 2026-10-23T18:00-07:00 --region CISO",
    );
  });

  it("leaves out the deadline when it's the end of the forecast, the CLI's default", () => {
    expect(buildCliCommand({ region: "PJM", durationHours: 2, deadline: null })).toBe("carbon windows --duration 2h --region PJM");
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
    region: "CISO",
    generated_at: hour(0),
    stale: false,
    data_source: "synthetic",
    points: [300, 200, 100, 150, 250, 300].map((intensity, h) => ({ start: hour(h), intensity })),
  };
  const response: WindowsResponse = {
    region: "CISO",
    generated_at: hour(0),
    stale: false,
    data_source: "synthetic",
    job: { duration_hours: 2, deadline: hour(6), deadline_clamped: false },
    baseline: { start: hour(0), end: hour(2), avg_intensity_g_per_kwh: 250 },
    windows: [
      { rank: 1, start: hour(2), end: hour(4), avg_intensity_g_per_kwh: 125, co2_saved_pct: 50 },
      { rank: 2, start: hour(4), end: hour(6), avg_intensity_g_per_kwh: 275, co2_saved_pct: -10 },
    ],
  };

  it("prints the same table as `carbon windows`", () => {
    expect(formatCliTable(response, forecast, Date.parse("2026-10-22T11:30:00-07:00"))).toBe(
      [
        "Synthetic data: made-up forecasts, not real grid data.",
        "Region CISO · forecast from Thu 11:00 · running now: 250 gCO₂/kWh",
        "",
        "Best: Thu 13:00–15:00 PDT (in 1h 30m) · 50% less CO₂ than running now",
        "",
        "Thu 11:00",
        "█▅▁▃▆█  100–300 gCO₂/kWh",
        "  1┘2┘",
        "┏━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓",
        "┃ Rank ┃ Start     ┃ End       ┃ Avg gCO₂/kWh ┃ CO₂ saved ┃",
        "┡━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━┩",
        "│ 1    │ Thu 13:00 │ Thu 15:00 │ 125          │ 50%       │",
        "│ 2    │ Thu 15:00 │ Thu 17:00 │ 275          │ -10%      │",
        "└──────┴───────────┴───────────┴──────────────┴───────────┘",
      ].join("\n"),
    );
  });

  it("prints the API response as indented JSON for agents", () => {
    expect(JSON.parse(formatCliJson(response))).toEqual(response);
    expect(formatCliJson(response)).toContain('\n  "region": "CISO"');
  });
});
