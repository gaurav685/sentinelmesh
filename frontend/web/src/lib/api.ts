/**
 * The typed BFF client.
 *
 * Every response type comes from `@sentinelmesh/contracts` (generated from the
 * backend's JSON Schema) — this file never re-declares a backend shape.
 *
 * The session is an httpOnly cookie, so requests use `credentials: "include"`
 * and never touch a token in JS. Mutations carry the CSRF header. A non-2xx is
 * thrown as an `ApiError` carrying the backend's typed error body when present.
 */

import type {
  CursorPageDetection,
  CursorPageSecurityAlert,
  Detection,
  ErrorResponse,
  MeResponse,
  MitreHeatmap,
  SecurityAlert,
  SocSummary,
  ThreatScore,
  TimelineResponse,
} from "@sentinelmesh/contracts";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** A view can render an error state without pattern-matching on status codes. */
  get kind(): "unauthorized" | "forbidden" | "not_found" | "unavailable" | "error" {
    if (this.status === 401) return "unauthorized";
    if (this.status === 403) return "forbidden";
    if (this.status === 404) return "not_found";
    if (this.status === 503) return "unavailable";
    return "error";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  csrfToken?: string | null;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== null && v !== undefined) url.searchParams.set(k, String(v));
  }
  return url.pathname + url.search;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && opts.csrfToken) headers["x-csrf-token"] = opts.csrfToken;

  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    credentials: "include",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });

  if (res.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }

  if (!res.ok) {
    const err = payload as ErrorResponse | null;
    const body = err?.error;
    throw new ApiError(
      res.status,
      body?.message ?? `request failed (${res.status})`,
      body?.code,
      body?.request_id ?? undefined,
    );
  }
  return payload as T;
}

// ---- typed endpoint helpers -------------------------------------------------
export const api = {
  me: (signal?: AbortSignal) => apiFetch<MeResponse>("/auth/me", { signal }),

  login: async (tenantSlug: string, email: string, password: string) => {
    const res = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "include",
      body: JSON.stringify({ tenant_slug: tenantSlug, email, password }),
    });
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as ErrorResponse | null;
      throw new ApiError(res.status, body?.error?.message ?? "login failed", body?.error?.code);
    }
    return { csrfToken: res.headers.get("x-csrf-token") };
  },

  logout: (csrfToken: string | null) =>
    apiFetch<void>("/auth/logout", { method: "POST", csrfToken }),

  socSummary: (signal?: AbortSignal) => apiFetch<SocSummary>("/soc/summary", { signal }),

  detections: (
    query: { limit?: number; severity?: string; status?: string; before?: string } = {},
    signal?: AbortSignal,
  ) => apiFetch<CursorPageDetection>("/soc/detections", { query, signal }),

  detection: (id: string, signal?: AbortSignal) =>
    apiFetch<Detection>(`/soc/detections/${id}`, { signal }),

  alerts: (query: { limit?: number; status?: string } = {}, signal?: AbortSignal) =>
    apiFetch<CursorPageSecurityAlert>("/soc/alerts", { query, signal }),

  alert: (id: string, signal?: AbortSignal) =>
    apiFetch<SecurityAlert>(`/soc/alerts/${id}`, { signal }),

  risk: (query: { limit?: number } = {}, signal?: AbortSignal) =>
    apiFetch<ThreatScore[]>("/soc/risk", { query, signal }),

  mitreHeatmap: (signal?: AbortSignal) => apiFetch<MitreHeatmap>("/soc/mitre/heatmap", { signal }),

  timeline: (subjectId: string, query: { limit?: number } = {}, signal?: AbortSignal) =>
    apiFetch<TimelineResponse>(`/soc/timeline/${encodeURIComponent(subjectId)}`, { query, signal }),

  chains: (
    query: { status?: string; min_score?: number; limit?: number } = {},
    signal?: AbortSignal,
  ) => apiFetch<unknown>("/soc/chains", { query, signal }),

  chain: (id: string, signal?: AbortSignal) => apiFetch<unknown>(`/soc/chains/${id}`, { signal }),

  graphNeighbors: (
    query: { label: string; key: string; depth?: number },
    signal?: AbortSignal,
  ) => apiFetch<unknown>("/soc/graph/neighbors", { query, signal }),
};
