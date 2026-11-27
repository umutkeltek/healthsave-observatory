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

// Tabs tell each other about a committed language switch on this channel
// (components/I18nProvider.tsx); the message is the new locale.
export const LOCALE_CHANNEL = "healthsave-locale";

/** The locale this tab should switch to after another tab committed `message`, or null. */
export function adoptBroadcastLocale(
  current: Locale,
  message: unknown,
  available: readonly Locale[],
): Locale | null {
  if (typeof message !== "string" || message === current) return null;
  return available.includes(message as Locale) ? (message as Locale) : null;
}
