"use client";

/**
 * Client-side auth context.
 *
 * The session lives in an httpOnly cookie the browser sends automatically. This
 * context only holds what the UI needs to render — the current user, tenant and
 * permission set from `/api/v1/me` — and the in-memory CSRF token for
 * mutations. **It is not an authorization boundary**: every action is still
 * checked server-side by the BFF. `hasPermission` here only decides what to
 * show, never what is allowed.
 */

import type { MeResponse } from "@sentinelmesh/contracts";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, api } from "./api";

type Status = "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  status: Status;
  me: MeResponse | null;
  csrfToken: string | null;
  hasPermission: (code: string) => boolean;
  login: (tenantSlug: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.me();
      setMe(next);
      setStatus("authenticated");
    } catch (err) {
      if (err instanceof ApiError && err.kind === "unauthorized") {
        setMe(null);
        setStatus("unauthenticated");
        return;
      }
      throw err;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh().catch(() => setStatus("unauthenticated"));
    return () => controller.abort();
  }, [refresh]);

  const login = useCallback(
    async (tenantSlug: string, email: string, password: string) => {
      const { csrfToken: token } = await api.login(tenantSlug, email, password);
      setCsrfToken(token);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout(csrfToken);
    } finally {
      setMe(null);
      setCsrfToken(null);
      setStatus("unauthenticated");
    }
  }, [csrfToken]);

  const hasPermission = useCallback(
    (code: string) => ((me?.permissions ?? []) as readonly string[]).includes(code),
    [me],
  );

  const value = useMemo<AuthState>(
    () => ({ status, me, csrfToken, hasPermission, login, logout, refresh }),
    [status, me, csrfToken, hasPermission, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
