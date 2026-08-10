import "server-only";

import { cookies } from "next/headers";

import {
  availableLocales,
  LOCALE_COOKIE,
  resolveAvailableLocale,
  type Locale,
} from "./i18n";

function previewLocalesEnabled(): boolean {
  return process.env.HEALTHSAVE_EXPERIMENTAL_LOCALES === "1";
}

export function getAvailableLocales(): readonly Locale[] {
  return availableLocales(previewLocalesEnabled());
}

export async function getLocale(): Promise<Locale> {
  const jar = await cookies();
  return resolveAvailableLocale(jar.get(LOCALE_COOKIE)?.value, previewLocalesEnabled());
}
