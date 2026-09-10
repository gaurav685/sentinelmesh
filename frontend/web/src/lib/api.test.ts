import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "./api";

function mockFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const res = {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k: string) => headers[k.toLowerCase()] ?? null },
    json: async () => body,
  };
  return vi.fn().mockResolvedValue(res as unknown as Response);
}

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("returns the parsed body on 200", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { open_alerts: 3 }));
    await expect(apiFetch<{ open_alerts: number }>("/soc/summary")).resolves.toEqual({
      open_alerts: 3,
    });
  });

  it("returns undefined on 204", async () => {
    vi.stubGlobal("fetch", mockFetch(204, null));
    await expect(apiFetch("/auth/logout", { method: "POST" })).resolves.toBeUndefined();
  });

  it("throws an ApiError carrying the backend error body", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(403, { error: { code: "forbidden", message: "nope", request_id: "req-1" } }),
    );
    const err = await apiFetch("/soc/detections").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.kind).toBe("forbidden");
    expect(err.message).toBe("nope");
    expect(err.requestId).toBe("req-1");
  });

  it("maps status codes to a UI-friendly kind", async () => {
    for (const [status, kind] of [
      [401, "unauthorized"],
      [404, "not_found"],
      [503, "unavailable"],
      [500, "error"],
    ] as const) {
      vi.stubGlobal("fetch", mockFetch(status, {}));
      const err = await apiFetch("/x").catch((e) => e as ApiError);
      expect(err.kind).toBe(kind);
    }
  });

  it("serialises query params and drops null/undefined", async () => {
    const fetchMock = mockFetch(200, {});
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/soc/detections", { query: { limit: 10, severity: undefined, status: "new" } });
    const url = fetchMock.mock.calls[0]![0] as string;
    expect(url).toContain("limit=10");
    expect(url).toContain("status=new");
    expect(url).not.toContain("severity");
  });

  it("adds the CSRF header only on mutations", async () => {
    const fetchMock = mockFetch(200, {});
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/x", { method: "POST", body: { a: 1 }, csrfToken: "tok" });
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["x-csrf-token"]).toBe("tok");
    expect(init.credentials).toBe("include");
  });
});
