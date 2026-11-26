"use client";

import { useEffect, useEffectEvent, useState } from "react";

export interface QueryState<T> {
  /** Latest successful data. While a new request loads this is the previous request's data. */
  data: T | undefined;
  /** Error from the current request, if it failed. */
  error: Error | undefined;
  /** Nothing to show yet: the first request is in flight. */
  isLoading: boolean;
  /** Showing previous data while the current request loads. Dim it rather than blanking it. */
  isRefetching: boolean;
  /** When `data` arrived, in ms since epoch. */
  receivedAt: number | undefined;
  retry: () => void;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: Error;
  receivedAt?: number;
}

/**
 * Fetch data for a request and refetch whenever the request changes, aborting stale requests.
 *
 * @param request Plain JSON-serialisable parameters, or null to wait (e.g. on another query).
 *   Requests with the same JSON are treated as the same request.
 * @param fetcher Loads data for a request. Always called with the request that is current.
 */
export function useQuery<R, T>(
  request: R | null,
  fetcher: (request: R, signal: AbortSignal) => Promise<T>,
): QueryState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [attempt, setAttempt] = useState(0);
  const load = useEffectEvent(fetcher);

  const requestKey = request === null ? null : JSON.stringify(request);
  const key = requestKey === null ? null : `${attempt}:${requestKey}`;

  useEffect(() => {
    if (requestKey === null || key === null) return;
    const controller = new AbortController();
    load(JSON.parse(requestKey) as R, controller.signal).then(
      (data) => setSettled({ key, data, receivedAt: Date.now() }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setSettled({ key, error: error instanceof Error ? error : new Error(String(error)) });
      },
    );
    return () => controller.abort();
  }, [key, requestKey]);

  const isCurrent = key !== null && settled?.key === key;
  const hasData = settled?.data !== undefined;
  return {
    data: settled?.data,
    error: isCurrent ? settled.error : undefined,
    isLoading: key !== null && !isCurrent && !hasData,
    isRefetching: key !== null && !isCurrent && hasData,
    receivedAt: settled?.receivedAt,
    retry: () => setAttempt((n) => n + 1),
  };
}
