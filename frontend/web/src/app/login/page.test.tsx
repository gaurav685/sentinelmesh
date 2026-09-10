import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const { replace, login } = vi.hoisted(() => ({ replace: vi.fn(), login: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("next=/alerts"),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login }) }));

import LoginPage from "./page";

afterEach(() => vi.clearAllMocks());

describe("LoginPage", () => {
  it("submits credentials and redirects to the requested page", async () => {
    login.mockResolvedValue(undefined);
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Tenant"), "acme");
    await userEvent.type(screen.getByLabelText("Email"), "analyst@acme.test");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(login).toHaveBeenCalledWith("acme", "analyst@acme.test", "correct-horse-battery-staple");
    expect(replace).toHaveBeenCalledWith("/alerts");
  });

  it("shows a message on bad credentials and does not redirect", async () => {
    const { ApiError } = await import("@/lib/api");
    login.mockRejectedValue(new ApiError(401, "bad"));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Tenant"), "acme");
    await userEvent.type(screen.getByLabelText("Email"), "x@y.z");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid tenant, email or password.");
    expect(replace).not.toHaveBeenCalled();
  });
});
