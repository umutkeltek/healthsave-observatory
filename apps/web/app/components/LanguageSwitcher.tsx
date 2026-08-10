"use client";

import { useEffect, useId, useState } from "react";

import { LOCALE_OPTIONS, type Locale } from "../lib/i18n";
import { useI18n } from "./I18nProvider";

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, dict, availableLocales, localePending } = useI18n();
  const [localeError, setLocaleError] = useState<string | null>(null);
  const errorId = useId();
  const options = LOCALE_OPTIONS.filter((option) => availableLocales.includes(option.value));

  useEffect(() => {
    if (localePending) setLocaleError(null);
  }, [localePending]);

  if (options.length <= 1) return null;

  return (
    <label className={`language-switcher ${compact ? "compact" : ""}`}>
      <span className="language-label">{dict.chrome.language}</span>
      <select
        aria-label={dict.chrome.language}
        aria-busy={localePending}
        aria-describedby={localeError ? errorId : undefined}
        disabled={localePending}
        value={locale}
        onChange={async (event) => {
          setLocaleError(null);
          setLocaleError(await setLocale(event.target.value as Locale));
        }}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {localeError ? (
        <span id={errorId} role="status" aria-live="polite" className="language-error">
          {localeError}
        </span>
      ) : null}
    </label>
  );
}
