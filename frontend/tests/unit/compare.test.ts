import { describe, expect, it } from "vitest";
import type { ForecastPoint } from "@/lib/api/types";
import { compareSites, pickComparisonSites, type Place } from "@/lib/compare";
import { HOUR_MS } from "@/lib/config";

const START = Date.parse("2026-10-21T00:00:00Z");
const deadline = new Date(START + 4 * HOUR_MS);

function forecast(prices: (number | undefined)[], intensity = 100): ForecastPoint[] {
  return prices.map((price, i) => ({ start: new Date(START + i * HOUR_MS).toISOString(), intensity, price: price as number }));
}

const site = (code: string): Place => ({ code, shortName: code, city: "" });

describe("compareSites", () => {
  it("ranks sites by their best window's job cost", () => {
    const options = compareSites(
      [
        { region: site("coresite-sv7"), points: forecast([60, 50, 70, 80]) },
        { region: site("ntt-ca1"), points: forecast([30, 20, 40, 40]) },
        { region: site("databank-san2"), points: forecast([90, 90, 90, 90]) },
      ],
      1,
      deadline,
      0,
      2,
    );
    expect(options.map((o) => o.region.code)).toEqual(["ntt-ca1", "coresite-sv7", "databank-san2"]);
    expect(options[0].best?.startIndex).toBe(1);
    expect(options[0].dollars).toBe(40); // $20/MWh × 2 MW × 1h
  });

  it("counts carbon at the given price", () => {
    const options = compareSites(
      [
        { region: site("ntt-ca1"), points: forecast([40, 40, 40, 40], 100) },
        { region: site("coresite-la1"), points: forecast([30, 30, 30, 30], 800) },
      ],
      1,
      deadline,
      100,
      1,
    );
    // NTT CA1: 40 + 100 × 0.1 = $50. CoreSite LA1: 30 + 100 × 0.8 = $110.
    expect(options.map((o) => o.region.code)).toEqual(["ntt-ca1", "coresite-la1"]);
  });

  it("puts sites without prices, without a window, and that failed last, in that order", () => {
    const options = compareSites(
      [
        { region: site("coresite-la1"), error: "API returned 404" },
        { region: site("databank-san2"), points: forecast([10, 10]) },
        { region: site("equinix-la4"), points: forecast([undefined, undefined, undefined, undefined]) },
        { region: site("ntt-ca1"), points: forecast([50, 50, 50, 50]) },
      ],
      3,
      deadline,
      0,
      1,
    );
    expect(options.map((o) => o.region.code)).toEqual(["ntt-ca1", "equinix-la4", "databank-san2", "coresite-la1"]);
    expect(options[1].dollars).toBeNull();
    expect(options[2].best).toBeNull();
    expect(options[3].error).toBe("API returned 404");
  });
});

describe("pickComparisonSites", () => {
  const campus = (id: string, city: string) => ({ id, name: id, city });
  const sites = [
    campus("fresno-1", "Fresno"),
    campus("santa-clara-1", "Santa Clara"),
    campus("santa-clara-2", "Santa Clara"),
    campus("san-jose-1", "San Jose"),
    campus("oakland-1", "Oakland"),
  ];

  it("starts with the campus on screen and takes one per city", () => {
    const picked = pickComparisonSites(sites, "santa-clara-2").map((s) => s.id);
    expect(picked).toEqual(["santa-clara-2", "san-jose-1", "fresno-1", "oakland-1"]);
  });

  it("stops at the limit", () => {
    expect(pickComparisonSites(sites, "fresno-1", 2)).toHaveLength(2);
  });

  it("still returns campuses when the current one is unknown", () => {
    expect(pickComparisonSites(sites, "nope").length).toBeGreaterThan(0);
  });
});
