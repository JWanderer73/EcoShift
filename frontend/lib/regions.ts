/** A datacenter campus. With the deployed API the list comes from `/v1/sites`; these are the sample-data ones. */
import type { Site } from "@/lib/api/types";

export const SAMPLE_SITES: Site[] = [
  { id: "fresno-305-west-napa-avenue", name: "305 West Napa Avenue", city: "Fresno" },
  { id: "san-jose-sample-campus", name: "Sample campus", city: "San Jose" },
  { id: "los-angeles-sample-campus", name: "Sample campus", city: "Los Angeles" },
];

/** "City, name" for menus and headings, e.g. "Fresno, 305 West Napa Avenue". */
export function siteLabel(site: Site | undefined, fallback: string): string {
  if (!site) return fallback;
  return site.city ? `${site.city}, ${site.name}` : site.name;
}

/** Look up a site by id. */
export function findSite(sites: Site[], id: string): Site | undefined {
  return sites.find((s) => s.id === id);
}
