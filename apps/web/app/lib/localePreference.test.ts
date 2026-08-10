import { describe, expect, test } from "bun:test";

import { commitLocalePreference } from "./localePreference";

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
