import type { IntelMode } from "../../lib/api";

// Known cloud providers and tested LiteLLM routes. These are conveniences, not
// an allow-list: the Model field remains free-form so a newly released route can
// be used without waiting for an Observatory release.
export const CLOUD_PROVIDERS = [
  {
    id: "deepseek",
    label: "DeepSeek",
    model: "deepseek/deepseek-chat",
    models: ["deepseek/deepseek-chat", "deepseek/deepseek-reasoner"],
  },
  {
    id: "openai",
    label: "OpenAI",
    model: "openai/gpt-5.6-sol",
    models: [
      "openai/gpt-5.6-sol",
      "openai/gpt-5.6",
      "openai/gpt-5.4-mini",
      "openai/gpt-5.4",
      "openai/gpt-5.1",
    ],
  },
  {
    id: "zai",
    label: "Z.AI / GLM",
    model: "zai/glm-5.1",
    models: ["zai/glm-5.1", "zai/glm-5", "zai/glm-4.7", "zai/glm-4.5v"],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    model: "anthropic/claude-sonnet-4-6",
    models: ["anthropic/claude-sonnet-4-6", "anthropic/claude-opus-4-6"],
  },
  {
    id: "gemini",
    label: "Google Gemini",
    model: "gemini/gemini-2.5-flash",
    models: ["gemini/gemini-2.5-flash", "gemini/gemini-2.5-pro"],
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    model: "openrouter/z-ai/glm-5.1",
    models: [
      "openrouter/z-ai/glm-5.1",
      "openrouter/z-ai/glm-5",
      "openrouter/openai/gpt-5.2",
      "openrouter/openai/gpt-5-mini",
    ],
  },
] as const;

export function modelsForProvider(provider: string): readonly string[] {
  return CLOUD_PROVIDERS.find((candidate) => candidate.id === provider)?.models ?? [];
}

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
