import { describe, expect, test } from "bun:test";

import { dictionaries, LOCALES, parseLocale } from "./i18n";

describe("i18n", () => {
  test("parseLocale accepts only supported locales", () => {
    expect(parseLocale("fr")).toBe("fr");
    expect(parseLocale("zh-TW")).toBe("zh-TW");
    expect(parseLocale("pt-BR")).toBe("en");
    expect(parseLocale(undefined)).toBe("en");
  });

  test("all dictionaries cover the same top-level sections", () => {
    const sections = Object.keys(dictionaries.en).sort();
    for (const locale of LOCALES) {
      expect(Object.keys(dictionaries[locale]).sort()).toEqual(sections);
    }
  });
});
