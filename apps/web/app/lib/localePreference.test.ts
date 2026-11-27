import { describe, expect, test } from "bun:test";

import { adoptBroadcastLocale, commitLocalePreference } from "./localePreference";

describe("commitLocalePreference", () => {
  test("adopts the requested locale only after persistence succeeds", async () => {
    const result = await commitLocalePreference("en", "fr", async () => ({ ok: true }));

    expect(result).toEqual({ locale: "fr", error: null });
  });

  test("keeps the committed locale and exposes a persistence failure", async () => {
    const result = await commitLocalePreference("en", "fr", async () => ({
      ok: false,
      error: "Cookie unavailable",
    }));

    expect(result).toEqual({ locale: "en", error: "Cookie unavailable" });
  });

  test("keeps the committed locale when the server action rejects", async () => {
    const result = await commitLocalePreference("en", "fr", async () => {
      throw new Error("network down");
    });

    expect(result).toEqual({ locale: "en", error: "Could not switch the language." });
  });
});

// The bug (audit web #22): a language switched in one tab never reached the
// other open tabs; they kept the old language until a reload.
describe("adoptBroadcastLocale", () => {
  const available = ["en", "es", "ja"] as const;

  test("another tab's committed language is adopted here", () => {
    expect(adoptBroadcastLocale("en", "ja", available)).toBe("ja");
  });

  test("the language already shown changes nothing", () => {
    expect(adoptBroadcastLocale("ja", "ja", available)).toBeNull();
  });

  test("a language this build does not offer, or a malformed message, is ignored", () => {
    expect(adoptBroadcastLocale("en", "fr", available)).toBeNull();
    expect(adoptBroadcastLocale("en", { locale: "ja" }, available)).toBeNull();
    expect(adoptBroadcastLocale("en", null, available)).toBeNull();
  });
});
