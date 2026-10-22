// Runs in America/Los_Angeles (see vitest.config.ts), so local times below are Pacific.
import { describe, expect, it } from "vitest";
import { buildCliCommand } from "@/lib/cli";
import { formatAge, formatClock, formatDayTime, formatRange, toDateTimeLocal, toOffsetIso } from "@/lib/format";

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
