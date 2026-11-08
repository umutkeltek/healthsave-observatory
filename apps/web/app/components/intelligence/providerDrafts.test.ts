import { describe, expect, test } from "bun:test";

import type { ConnectionView } from "../../lib/api";
import { connectionInputFor, initialDrafts, primaryFor, withModel, withProvider } from "./providerDrafts";

function saved(provider: string, model: string, base_url: string | null): ConnectionView {
  return {
    id: 1,
    provider,
    display_name: null,
    base_url,
    destination: provider === "ollama" ? "local" : "cloud",
    enabled: true,
    key_last4: null,
    last_test_status: null,
    last_test_at: null,
    model,
  };
}

const NO_EXTRAS = { apiKey: "", temperature: "", maxTokens: "", advanced: false };

describe("provider drafts per mode", () => {
  // The bug: one baseUrl and one model for both modes. The Base URL field is
  // only shown for Local, yet a local URL was sent with the cloud provider,
  // and switching to Cloud kept the local model name.
  test("a local base URL never reaches a cloud provider", () => {
    const local = saved("ollama", "llama3.1:8b", "http://192.168.1.5:11434");
    const drafts = withProvider(initialDrafts(local), "deepseek", local);
    const cloud = primaryFor("cloud", drafts, NO_EXTRAS);
    expect(cloud.provider).toBe("deepseek");
    expect(cloud.base_url).toBeUndefined();
    expect(connectionInputFor("cloud", drafts, "").base_url).toBeNull();
  });

  test("switching to cloud does not carry the local model over", () => {
    const local = saved("ollama", "llama3.1:8b", null);
    const cloud = primaryFor("cloud", initialDrafts(local), NO_EXTRAS);
    expect(cloud.model).toBe("deepseek/deepseek-chat");
  });

  test("each mode keeps its own model", () => {
    let drafts = initialDrafts(null);
    drafts = withModel(drafts, "local", "qwen2.5:7b");
    drafts = withModel(drafts, "cloud", "openai/gpt-4o");
    expect(primaryFor("local", drafts, NO_EXTRAS).model).toBe("qwen2.5:7b");
    expect(primaryFor("cloud", drafts, NO_EXTRAS).model).toBe("openai/gpt-4o");
  });

  test("cloud-only fields are not sent for a local model", () => {
    const extras = { apiKey: "sk-123", temperature: "0.3", maxTokens: "500", advanced: true };
    const local = primaryFor("local", withModel(initialDrafts(null), "local", "llama3.1:8b"), extras);
    expect(local).toEqual({ provider: "ollama", model: "llama3.1:8b", base_url: "http://ollama:11434" });
    const cloud = primaryFor("cloud", initialDrafts(null), extras);
    expect(cloud).toMatchObject({ api_key: "sk-123", temperature: 0.3, max_tokens: 500 });
  });

  test("a saved cloud base URL stays with its own provider only", () => {
    const openai = saved("openai", "openai/gpt-4o-mini", "https://proxy.example/v1");
    const drafts = initialDrafts(openai);
    expect(primaryFor("cloud", drafts, NO_EXTRAS).base_url).toBe("https://proxy.example/v1");
    const switched = withProvider(drafts, "gemini", openai);
    expect(primaryFor("cloud", switched, NO_EXTRAS).base_url).toBeUndefined();
    expect(primaryFor("cloud", withProvider(switched, "openai", openai), NO_EXTRAS).base_url).toBe(
      "https://proxy.example/v1",
    );
  });
});
