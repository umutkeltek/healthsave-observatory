import type { IntelMode } from "../../lib/api";

// Known cloud providers + a sensible default model. The user can still type any
// litellm route; these just make the common path one click.
export const CLOUD_PROVIDERS = [
  { id: "deepseek", label: "DeepSeek", model: "deepseek/deepseek-chat" },
  { id: "openai", label: "OpenAI", model: "openai/gpt-4o-mini" },
  { id: "anthropic", label: "Anthropic", model: "anthropic/claude-sonnet" },
  { id: "gemini", label: "Google Gemini", model: "gemini/gemini-2.5-flash" },
  { id: "openrouter", label: "OpenRouter", model: "openrouter/openai/gpt-oss-120b:free" },
] as const;

export const OLLAMA_DEFAULT_BASE = "http://ollama:11434";

export type FallbackDraft = { provider: string; model: string; apiKey: string };

export const MODE_CARDS: { id: IntelMode; title: string; blurb: string }[] = [
  {
    id: "off",
    title: "Off",
    blurb: "No narrator. Findings are computed on-device by the statistical engine. Nothing leaves.",
  },
  {
    id: "local",
    title: "Local",
    blurb: "A model on your own machine (Ollama) writes the briefs. Still nothing leaves the host.",
  },
  {
    id: "cloud",
    title: "Cloud",
    blurb: "Your own provider key. Only redacted, derived findings leave — never raw health data.",
  },
];

export function leavesCopy(mode: IntelMode, redact: boolean): string {
  if (mode === "off")
    return "Nothing. With the narrator off, findings are computed on-device and no prompt is ever assembled.";
  if (mode === "local")
    return "Nothing. A local model runs on your own host, so prompts and findings stay inside the trust boundary.";
  return redact
    ? "Only an assembled prompt of derived findings — with identifiers (emails, names, IDs) scrubbed first — is sent to your provider once you consent."
    : "An assembled prompt of derived findings is sent to your provider once you consent. Redaction is OFF, so identifiers are not scrubbed.";
}
