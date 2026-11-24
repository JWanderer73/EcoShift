"use client";

import { getApiClient } from "@/lib/api/client";
import type { Site } from "@/lib/api/types";
import { useQuery } from "@/lib/hooks/use-query";

const NONE: Site[] = [];

/** The sites (datacenter campuses) the API serves. Empty until the list arrives. */
export function useSites(): Site[] {
  return useQuery({ sites: true }, (_request, signal) => getApiClient().getSites(signal)).data ?? NONE;
}
