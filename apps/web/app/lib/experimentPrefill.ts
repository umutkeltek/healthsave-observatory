// Read-only prefill for /experiments, driven by a finding card's promotable
// experiment candidate. The finding card links "next question -> propose
// experiment" to /experiments?lever=..&outcome=..; the experiments page decodes
// that here and offers the existing StartExperimentButton pre-aimed at the pair.
// No new write path: the commit still flows through startExperimentAction.

import type { CardExperimentCandidate } from "./api";

export type ExperimentPrefill = {
  lever: string;
  outcome: string;
  protocol: string | null;
  requiredDays: number | null;
};

// Build the /experiments link from a card's experiment candidate. Returns null
// unless both metric ids the experiment needs (lever + outcome) are present.
export function experimentHref(
  candidate: Pick<
    CardExperimentCandidate,
    "lever" | "outcome" | "suggested_protocol" | "required_days"
  > | null,
): string | null {
  if (!candidate?.lever || !candidate?.outcome) return null;
  const params = new URLSearchParams();
  params.set("lever", candidate.lever);
  params.set("outcome", candidate.outcome);
  if (candidate.suggested_protocol) params.set("protocol", candidate.suggested_protocol);
  if (candidate.required_days != null) params.set("days", String(candidate.required_days));
  return `/experiments?${params.toString()}`;
}

function firstValue(value: string | string[] | undefined): string | null {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : null;
}

// Decode the experiments page's search params back into a prefill, or null when
// no valid lever+outcome pair was passed. Round-trips experimentHref().
export function parseExperimentPrefill(
  searchParams: Record<string, string | string[] | undefined>,
): ExperimentPrefill | null {
  const lever = firstValue(searchParams.lever);
  const outcome = firstValue(searchParams.outcome);
  if (!lever || !outcome) return null;
  const days = Number(firstValue(searchParams.days));
  return {
    lever,
    outcome,
    protocol: firstValue(searchParams.protocol),
    requiredDays: Number.isFinite(days) && days > 0 ? days : null,
  };
}
