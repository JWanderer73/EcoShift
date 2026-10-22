/** A grid balancing authority, identified by its EIA-930 code. */
export interface Region {
  code: string;
  name: string;
  /** Short label for tight spaces, e.g. "California". */
  shortName: string;
}

// Same regions the CLI supports (see the carbon CLI design spec), so "Copy as CLI command"
// always produces a command that works. The final list is still open with the data team.
export const REGIONS: Region[] = [
  { code: "CISO", name: "California ISO", shortName: "California" },
  { code: "ERCO", name: "ERCOT", shortName: "Texas" },
  { code: "PJM", name: "PJM Interconnection", shortName: "Mid-Atlantic" },
];

/** Look up a region by EIA code. */
export function findRegion(code: string): Region | undefined {
  return REGIONS.find((r) => r.code === code);
}
