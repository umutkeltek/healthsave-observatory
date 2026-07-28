import type { IntelMode } from "../../lib/api";

// Known cloud providers plus sensible default models. Users can still type a
// provider/model route manually; these just make common paths fast.
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
    blurb: "No narrator. Findings are computed on this host. Nothing leaves.",
  },
  {
    id: "local",
    title: "Local",
    blurb: "A model on your machine writes briefs. Nothing leaves the host.",
  },
  {
    id: "cloud",
    title: "Cloud",
    blurb: "Your provider key. Only redacted derived findings leave. Raw health data never does.",
  },
];

export function leavesCopy(mode: IntelMode, redact: boolean): string {
  if (mode === "off") {
    return "Nothing. With the narrator off, findings are computed locally and no prompt is assembled.";
  }

  if (mode === "local") {
    return "Nothing. A local model runs on your host, so prompts and findings stay inside the trust boundary.";
  }

  return redact
    ? "Only a redacted prompt built from derived findings is sent to your provider after consent."
    : "A prompt built from derived findings is sent to your provider after consent. Redaction is off, so identifiers are not scrubbed.";
}
