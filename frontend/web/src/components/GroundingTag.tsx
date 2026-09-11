import type { GroundingKind } from "@sentinelmesh/contracts";

const LABEL: Record<string, string> = {
  evidence: "Evidence",
  inference: "Inference",
  prediction: "Prediction",
  synthetic: "Synthetic",
};

/**
 * Every generated statement in a report or narrative is tagged with one of
 * four grounding tiers (Constitution §3) — never left implicit. `synthetic`
 * means the underlying chain is simulation-sourced, not a real incident.
 */
export function GroundingTag({ tier }: { tier: GroundingKind | string }) {
  const label = LABEL[tier] ?? String(tier);
  return <span className={`tier-badge tier-badge--${tier}`}>{label}</span>;
}
