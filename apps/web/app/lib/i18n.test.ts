import { describe, expect, test } from "bun:test";

import {
  availableLocales,
  dictionaries,
  LOCALES,
  parseLocale,
  resolveAvailableLocale,
} from "./i18n";

function leafEntries(value: object, prefix = ""): Array<[string, string]> {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof child === "string" ? [[path, child]] : leafEntries(child, path);
  });
}

function placeholders(value: string): string[] {
  return [...value.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((match) => match[1]).sort();
}

describe("i18n", () => {
  test("parseLocale accepts only supported locales", () => {
    expect(parseLocale("fr")).toBe("fr");
    expect(parseLocale("zh-TW")).toBe("zh-TW");
    expect(parseLocale("pt-BR")).toBe("en");
    expect(parseLocale(undefined)).toBe("en");
  });

  test("unfinished locales stay behind an explicit preview gate", () => {
    expect(availableLocales(false)).toEqual(["en"]);
    expect(availableLocales(true)).toEqual(LOCALES);
    expect(resolveAvailableLocale("fr", false)).toBe("en");
    expect(resolveAvailableLocale("fr", true)).toBe("fr");
    expect(resolveAvailableLocale("pt-BR", true)).toBe("en");
  });

  test("all dictionaries cover every leaf and preserve placeholders", () => {
    const english = new Map(leafEntries(dictionaries.en));
    for (const locale of LOCALES) {
      const translated = new Map(leafEntries(dictionaries[locale]));
      expect([...translated.keys()].sort()).toEqual([...english.keys()].sort());
      for (const [path, englishValue] of english) {
        expect(placeholders(translated.get(path) ?? "")).toEqual(placeholders(englishValue));
      }
    }
  });
});
