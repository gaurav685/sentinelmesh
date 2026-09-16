import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth";

function mockFetch(handler: (url: string, init?: RequestInit) => { status: number; body: unknown }) {
  return vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    const { status, body } = handler(url, init);
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: () => null },
      json: async () => body,
    } as unknown as Response;
  });
}

function Probe() {
  const { status, me, hasPermission } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="email">{me?.user.email ?? "-"}</span>
      <span data-testid="can-read">{String(hasPermission("detections:read"))}</span>
    </div>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("AuthProvider", () => {
  it("hydrates from /me and exposes the permission set", async () => {
    // Asserting the real path here is what would have caught the real bug
    // this test's mock previously let through silently: the client called
    // `/auth/me`, a route that does not exist (the real one is `/api/v1/me`,
    // on a differently-prefixed router) -- found only by actually logging
    // in through a browser, not by this test, since its handler ignored
    // `url` entirely and returned success regardless of what was fetched.
    vi.stubGlobal(
      "fetch",
      mockFetch((url) => {
        expect(url).toBe("/api/v1/me");
        return {
          status: 200,
          body: {
            user: { email: "analyst@acme.test" },
            tenant: { name: "Acme" },
            roles: ["analyst"],
            permissions: ["detections:read"],
          },
        };
      }),
    );
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("email")).toHaveTextContent("analyst@acme.test");
    expect(screen.getByTestId("can-read")).toHaveTextContent("true");
  });

  it("goes unauthenticated when /me returns 401", async () => {
    vi.stubGlobal("fetch", mockFetch(() => ({ status: 401, body: { error: { code: "unauthenticated" } } })));
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("can-read")).toHaveTextContent("false");
  });
});
