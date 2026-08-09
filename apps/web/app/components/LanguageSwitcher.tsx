"use client";

import { LOCALE_OPTIONS, type Locale } from "../lib/i18n";
import { useI18n } from "./I18nProvider";

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, dict } = useI18n();
  return (
    <label className={`language-switcher ${compact ? "compact" : ""}`}>
      <span>{dict.chrome.language}</span>
      <select
        aria-label={dict.chrome.language}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {LOCALE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function StandaloneLanguageSwitcher({ locale }: { locale: Locale }) {
  const { setLocale, dict } = useI18n();
  return (
    <label className="language-switcher settings-language">
      <span>{dict.chrome.language}</span>
      <select
        aria-label={dict.chrome.language}
        defaultValue={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {LOCALE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
