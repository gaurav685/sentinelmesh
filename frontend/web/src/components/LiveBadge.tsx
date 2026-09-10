"use client";

import { useEffect, useState } from "react";

function ago(from: Date, now: number): string {
  const s = Math.max(0, Math.round((now - from.getTime()) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  return `${m}m ago`;
}

/**
 * Shows when a polled view last refreshed. The gateway has no push channel for
 * Kafka-borne events, so this is an honest "last polled" indicator, not a claim
 * of live streaming.
 */
export function LiveBadge({
  updatedAt,
  refreshMs,
  onRefresh,
}: {
  updatedAt: Date | null;
  refreshMs: number;
  onRefresh?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="live-badge" role="status" aria-live="off">
      <span className="live-badge__dot" aria-hidden />
      <span>
        Updated {updatedAt ? ago(updatedAt, now) : "…"}
        <span className="state__meta"> · auto-refresh {Math.round(refreshMs / 1000)}s</span>
      </span>
      {onRefresh ? (
        <button type="button" className="btn btn--ghost" onClick={onRefresh}>
          Refresh now
        </button>
      ) : null}
    </span>
  );
}
