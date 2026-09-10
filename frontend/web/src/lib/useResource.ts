"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface Resource<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  /** Wall-clock time of the last successful load, or null before the first. */
  updatedAt: Date | null;
  reload: () => void;
}

export interface ResourceOptions {
  /**
   * Poll interval in milliseconds. The gateway exposes no push channel for
   * Kafka-borne detections/chains, so "real time" is an honest client poll and
   * the UI shows when it last refreshed. Omit or pass 0 to disable.
   */
  refreshMs?: number;
}

/**
 * Fetch-on-mount with abort, error capture, a manual `reload` and an optional
 * poll. Deliberately tiny — no cache, no dedupe. `deps` re-runs the fetch (e.g.
 * a route param or a filter changed). A failed poll surfaces the error but keeps
 * the last good data on screen rather than blanking the view.
 */
export function useResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[] = [],
  opts: ResourceOptions = {},
): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const hasData = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    if (!hasData.current) setLoading(true);
    fetcherRef
      .current(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setData(next);
        setError(null);
        setUpdatedAt(new Date());
        hasData.current = true;
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        if (!hasData.current) setData(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  const refreshMs = opts.refreshMs ?? 0;
  useEffect(() => {
    if (refreshMs <= 0) return;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, reload]);

  return { data, error, loading, updatedAt, reload };
}
