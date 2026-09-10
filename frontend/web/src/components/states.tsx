"use client";

import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

/** Loading, error and empty states — every data view uses these three so the
 * experience is consistent and never a blank screen. */

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="state state--empty">
      <p className="state__title">{title}</p>
      {hint ? <p className="state__hint">{hint}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: Error;
  onRetry?: () => void;
}) {
  const isApi = error instanceof ApiError;
  const message =
    isApi && error.kind === "forbidden"
      ? "You do not have permission to view this."
      : isApi && error.kind === "unavailable"
        ? "A backend service is temporarily unavailable."
        : error.message || "Something went wrong.";
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">Could not load this view</p>
      <p className="state__hint">{message}</p>
      {isApi && error.requestId ? (
        <p className="state__meta">request id: {error.requestId}</p>
      ) : null}
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
