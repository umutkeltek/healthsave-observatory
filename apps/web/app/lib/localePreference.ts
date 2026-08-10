import type { Locale } from "./i18n";

type LocaleWriteResult = { ok: boolean; error?: string };
type LocaleWriter = (locale: Locale) => Promise<LocaleWriteResult>;

export async function commitLocalePreference(
  committedLocale: Locale,
  requestedLocale: Locale,
  write: LocaleWriter,
): Promise<{ locale: Locale; error: string | null }> {
  try {
    const result = await write(requestedLocale);
    return result.ok
      ? { locale: requestedLocale, error: null }
      : { locale: committedLocale, error: result.error ?? "Could not switch the language." };
  } catch {
    return { locale: committedLocale, error: "Could not switch the language." };
  }
}
