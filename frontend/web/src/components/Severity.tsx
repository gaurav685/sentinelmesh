import type { Severity as SeverityValue } from "@sentinelmesh/contracts";

const META: Record<
  string,
  { label: string; symbol: string; className: string }
> = {
  critical: { label: "Critical", symbol: "▲▲", className: "sev sev--critical" },
  high: { label: "High", symbol: "▲", className: "sev sev--high" },
  medium: { label: "Medium", symbol: "●", className: "sev sev--medium" },
  low: { label: "Low", symbol: "○", className: "sev sev--low" },
  info: { label: "Info", symbol: "·", className: "sev sev--info" },
};

/**
 * Severity is shown as colour **and** text **and** a shape — never colour alone
 * (WCAG 1.4.1). An unknown value degrades to a plain label.
 */
export function Severity({ value }: { value: SeverityValue | string }) {
  const meta = META[value] ?? {
    label: String(value),
    symbol: "?",
    className: "sev sev--info",
  };
  return (
    <span className={meta.className}>
      <span aria-hidden>{meta.symbol}</span> {meta.label}
    </span>
  );
}

export const SEVERITY_RANK: Record<string, number> = {
  critical: 5,
  high: 4,
  medium: 3,
  low: 2,
  info: 1,
};
