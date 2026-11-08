// A deployment with no LLM narrator (provider "disabled"/empty) performs zero
// egress - it is the *most* private posture, not "cloud". The egress classifier
// only knows ollama→local / everything-else→cloud, so a narrator-off host would
// be bucketed as cloud; callers special-case it so the UI never mislabels a
// no-egress host as a cloud one.
//
// Lives outside api.ts so client components can use it without pulling the
// server-only API client (which reads request cookies) into the browser bundle.
export function isNarratorOff(provider: string | null | undefined): boolean {
  const p = (provider ?? "").trim().toLowerCase();
  return p === "" || p === "disabled" || p === "none";
}

// The narrator as far as this page knows. A privacy read that failed is
// "unknown": never reported as off (or on).
export type NarratorState = "on" | "off" | "unknown";

export function narratorState(privacy: { provider: string | null } | null | undefined): NarratorState {
  if (!privacy) return "unknown";
  return isNarratorOff(privacy.provider) ? "off" : "on";
}
