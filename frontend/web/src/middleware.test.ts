import { describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => {
  class NextResponse {
    static redirect(url: URL) {
      return { type: "redirect", location: url.toString() };
    }
    static next() {
      return { type: "next" };
    }
  }
  return { NextResponse };
});

import { middleware } from "./middleware";

function req(path: string, hasSession: boolean) {
  const nextUrl = new URL(`http://localhost:3000${path}`);
  return {
    nextUrl: Object.assign(nextUrl, { clone: () => new URL(nextUrl.toString()) }),
    cookies: { has: (name: string) => hasSession && name === "sm_session" },
  } as never;
}

describe("route guard middleware", () => {
  it("redirects a cookie-less browser to /login with a next param", () => {
    const r = middleware(req("/alerts", false)) as { type: string; location: string };
    expect(r.type).toBe("redirect");
    expect(r.location).toContain("/login");
    expect(r.location).toContain("next=%2Falerts");
  });

  it("redirects an authenticated browser away from /login", () => {
    const r = middleware(req("/login", true)) as { type: string; location: string };
    expect(r.type).toBe("redirect");
    expect(r.location).toMatch(/\/$/);
  });

  it("lets an authenticated request through", () => {
    expect(middleware(req("/", true))).toEqual({ type: "next" });
  });

  it("lets an unauthenticated request reach a public path", () => {
    expect(middleware(req("/login", false))).toEqual({ type: "next" });
  });
});
