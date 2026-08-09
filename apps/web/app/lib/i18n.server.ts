import { cookies } from "next/headers";

import { LOCALE_COOKIE, parseLocale, type Locale } from "./i18n";

export async function getLocale(): Promise<Locale> {
  const jar = await cookies();
  return parseLocale(jar.get(LOCALE_COOKIE)?.value);
}
