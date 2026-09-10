import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LiveBadge } from "./LiveBadge";

describe("LiveBadge", () => {
  it("reports the last refresh time and the poll interval", () => {
    render(<LiveBadge updatedAt={new Date()} refreshMs={20_000} />);
    expect(screen.getByRole("status")).toHaveTextContent("Updated just now");
    expect(screen.getByRole("status")).toHaveTextContent("auto-refresh 20s");
  });

  it("does not claim a live stream — it says updated / auto-refresh, not 'live'", () => {
    render(<LiveBadge updatedAt={new Date()} refreshMs={30_000} />);
    expect(screen.getByRole("status").textContent?.toLowerCase()).not.toContain("streaming");
  });

  it("invokes onRefresh when the button is pressed", async () => {
    const onRefresh = vi.fn();
    render(<LiveBadge updatedAt={null} refreshMs={20_000} onRefresh={onRefresh} />);
    await userEvent.click(screen.getByRole("button", { name: "Refresh now" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});
