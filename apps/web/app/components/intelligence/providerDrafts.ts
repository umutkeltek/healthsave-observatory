// Each narrator mode keeps its own provider fields. Only the selected mode's
// fields are shown, and only they are sent: a local base URL never reaches a
// cloud provider, a local model never becomes a cloud model, and the
// cloud-only API key and advanced knobs never ride along with a local model.

import type { ConnectionInputPayload, ConnectionView, PrimaryInputPayload } from "../../lib/api";
import { CLOUD_PROVIDERS, OLLAMA_DEFAULT_BASE } from "./constants";

export type ProviderDrafts = {
  local: { model: string; baseUrl: string };
  // Cloud has no Base URL field: baseUrl is only a saved cloud connection's
  // own value, kept while that same provider is selected.
  cloud: { provider: string; model: string; baseUrl: string };
};

export type CloudExtras = { apiKey: string; temperature: string; maxTokens: string; advanced: boolean };

const LOCAL_PROVIDER = "ollama";

function presetModel(provider: string): string | null {
  return CLOUD_PROVIDERS.find((p) => p.id === provider)?.model ?? null;
}

/** Drafts seeded from the saved primary connection, filed under its own mode. */
export function initialDrafts(saved: ConnectionView | null): ProviderDrafts {
  const local = saved?.provider === LOCAL_PROVIDER ? saved : null;
  const cloud = saved && saved.provider !== LOCAL_PROVIDER ? saved : null;
  const provider = cloud?.provider ?? CLOUD_PROVIDERS[0].id;
  return {
    local: { model: local?.model ?? "", baseUrl: local?.base_url ?? "" },
    cloud: {
      provider,
      model: cloud?.model ?? presetModel(provider) ?? "",
      baseUrl: cloud?.base_url ?? "",
    },
  };
}

/** Pick a cloud provider: its preset model, and a base URL only if it is the saved one's. */
export function withProvider(drafts: ProviderDrafts, provider: string, saved: ConnectionView | null): ProviderDrafts {
  const savedHere = saved && saved.provider === provider && provider !== LOCAL_PROVIDER ? saved : null;
  return {
    ...drafts,
    cloud: {
      provider,
      model: presetModel(provider) ?? drafts.cloud.model,
      baseUrl: savedHere?.base_url ?? "",
    },
  };
}

export function withModel(drafts: ProviderDrafts, mode: "local" | "cloud", model: string): ProviderDrafts {
  return mode === "local"
    ? { ...drafts, local: { ...drafts.local, model } }
    : { ...drafts, cloud: { ...drafts.cloud, model } };
}

export function withLocalBaseUrl(drafts: ProviderDrafts, baseUrl: string): ProviderDrafts {
  return { ...drafts, local: { ...drafts.local, baseUrl } };
}

export function primaryFor(mode: "local" | "cloud", drafts: ProviderDrafts, extras: CloudExtras): PrimaryInputPayload {
  if (mode === "local") {
    return {
      provider: LOCAL_PROVIDER,
      model: drafts.local.model.trim(),
      base_url: drafts.local.baseUrl.trim() || OLLAMA_DEFAULT_BASE,
    };
  }
  const primary: PrimaryInputPayload = { provider: drafts.cloud.provider, model: drafts.cloud.model.trim() };
  if (drafts.cloud.baseUrl.trim()) primary.base_url = drafts.cloud.baseUrl.trim();
  if (extras.apiKey.trim()) primary.api_key = extras.apiKey.trim();
  if (extras.advanced && extras.temperature.trim()) primary.temperature = Number(extras.temperature);
  if (extras.advanced && extras.maxTokens.trim()) primary.max_tokens = Number(extras.maxTokens);
  return primary;
}

/** The connection the test probe uses: the CURRENT (possibly unsaved) visible fields. */
export function connectionInputFor(
  mode: "local" | "cloud",
  drafts: ProviderDrafts,
  apiKey: string,
): ConnectionInputPayload {
  return mode === "local"
    ? {
        provider: LOCAL_PROVIDER,
        model: drafts.local.model.trim(),
        base_url: drafts.local.baseUrl.trim() || OLLAMA_DEFAULT_BASE,
        api_key: null,
      }
    : {
        provider: drafts.cloud.provider,
        model: drafts.cloud.model.trim(),
        base_url: drafts.cloud.baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
      };
}
