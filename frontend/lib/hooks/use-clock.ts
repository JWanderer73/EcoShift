"use client";

import { useSyncExternalStore } from "react";

const MINUTE_MS = 60_000;
/** Re-check twice a minute so displayed times are never more than ~30s behind. */
const TICK_MS = 30_000;

function subscribe(onTick: () => void) {
  const timer = setInterval(onTick, TICK_MS);
  return () => clearInterval(timer);
}

// Rounded to the minute so the snapshot only changes, and components only re-render, once a minute.
const getMinute = () => Math.floor(Date.now() / MINUTE_MS) * MINUTE_MS;
const getServerMinute = () => null;

/**
 * Current time, rounded down to the minute, in ms since epoch.
 * Null during server rendering and hydration, so time-dependent text never mismatches.
 */
export function useMinuteClock(): number | null {
  return useSyncExternalStore(subscribe, getMinute, getServerMinute);
}

const noopSubscribe = () => () => {};

/** False during server rendering and hydration, true after. For UI that depends on browser-only state. */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}
