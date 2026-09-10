import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SEVERITY_RANK, Severity } from "./Severity";

describe("Severity", () => {
  it("shows a text label and a shape, not colour alone", () => {
    render(<Severity value="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    // the shape glyph is aria-hidden so screen readers get the word only
    expect(screen.getByText("▲▲")).toHaveAttribute("aria-hidden", "true");
  });

  it("degrades an unknown value to a plain label", () => {
    render(<Severity value="weird" />);
    expect(screen.getByText("weird")).toBeInTheDocument();
  });

  it("ranks severities for sorting", () => {
    expect(SEVERITY_RANK["critical"]).toBeGreaterThan(SEVERITY_RANK["info"]!);
  });
});
