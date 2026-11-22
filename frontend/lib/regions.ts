/** EIA-930 balancing authority a site's power comes from; it sets the site's carbon intensity. */
export type BalancingAuthority = "CISO" | "BANC" | "LDWP";

/** A California data center. Its price comes from the pricing node nearest it. */
export interface Region {
  /** Site code the API takes, e.g. "coresite-sv7". */
  code: string;
  /** Facility name, e.g. "CoreSite SV7". */
  name: string;
  /** Short label for tight spaces; the facility name. */
  shortName: string;
  city: string;
  address: string;
  /** Utility that delivers the power. */
  utility: string;
  balancingAuthority: BalancingAuthority;
}

/** Display names for the balancing authorities, used to group the site picker. */
export const BALANCING_AUTHORITIES: Record<BalancingAuthority, string> = {
  CISO: "CAISO",
  BANC: "Sacramento (BANC)",
  LDWP: "Los Angeles (LADWP)",
};

// Same codes as SITES in src/forecast.py. Addresses and utilities from the operators' pages and
// datacentermap/baxtel listings (checked Nov 2026). The CAISO sites share CISO's carbon but price
// at different nodes; NTT CA1 and CoreSite LA1 are in their own balancing authorities.
export const REGIONS: Region[] = [
  {
    code: "coresite-sv7",
    name: "CoreSite SV7",
    shortName: "CoreSite SV7",
    city: "Santa Clara",
    address: "3020 Coronado Dr, Santa Clara",
    utility: "Silicon Valley Power",
    balancingAuthority: "CISO",
  },
  {
    code: "equinix-sv1",
    name: "Equinix SV1",
    shortName: "Equinix SV1",
    city: "San Jose",
    address: "11 Great Oaks Blvd, San Jose",
    utility: "PG&E",
    balancingAuthority: "CISO",
  },
  {
    code: "he-fremont2",
    name: "Hurricane Electric Fremont 2",
    shortName: "HE Fremont 2",
    city: "Fremont",
    address: "48233 Warm Springs Blvd, Fremont",
    utility: "PG&E",
    balancingAuthority: "CISO",
  },
  {
    code: "equinix-la4",
    name: "Equinix LA4",
    shortName: "Equinix LA4",
    city: "El Segundo",
    address: "445 N Douglas St, El Segundo",
    utility: "SCE",
    balancingAuthority: "CISO",
  },
  {
    code: "databank-san2",
    name: "DataBank SAN2",
    shortName: "DataBank SAN2",
    city: "San Diego",
    address: "9606 Aero Dr, San Diego",
    utility: "SDG&E",
    balancingAuthority: "CISO",
  },
  {
    code: "ntt-ca1",
    name: "NTT Sacramento CA1",
    shortName: "NTT CA1",
    city: "Sacramento",
    address: "1200 Striker Ave, Sacramento",
    utility: "SMUD",
    balancingAuthority: "BANC",
  },
  {
    code: "coresite-la1",
    name: "CoreSite LA1 (One Wilshire)",
    shortName: "CoreSite LA1",
    city: "Los Angeles",
    address: "624 S Grand Ave, Los Angeles",
    utility: "LADWP",
    balancingAuthority: "LDWP",
  },
];

/** Look up a site by code. */
export function findRegion(code: string): Region | undefined {
  return REGIONS.find((r) => r.code === code);
}
