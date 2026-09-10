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
    vi.stubGlobal(
      "fetch",
      mockFetch(() => ({
        status: 200,
        body: {
          user: { email: "analyst@acme.test" },
          tenant: { name: "Acme" },
          roles: ["analyst"],
          permissions: ["detections:read"],
        },
      })),
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
