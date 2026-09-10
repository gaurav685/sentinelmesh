import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { EmptyState, ErrorState, Loading } from "./states";

describe("state components", () => {
  it("Loading announces politely", () => {
    render(<Loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
  });

  it("EmptyState renders a title and hint", () => {
    render(<EmptyState title="Nothing here" hint="try later" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("try later")).toBeInTheDocument();
  });

  it("ErrorState translates a forbidden ApiError into a permission message", () => {
    render(<ErrorState error={new ApiError(403, "raw")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("do not have permission");
  });

  it("ErrorState translates a 503 into an availability message and can retry", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new ApiError(503, "raw")} onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("temporarily unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
