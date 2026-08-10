"use client";

import { createContext, type ReactNode, useContext, useRef, useState } from "react";

import { setLocaleAction } from "../lib/actions";
import { getDictionary, type Dictionary, type Locale } from "../lib/i18n";
import { commitLocalePreference } from "../lib/localePreference";

type I18nContextValue = {
  locale: Locale;
  dict: Dictionary;
  availableLocales: readonly Locale[];
  localePending: boolean;
  setLocale: (locale: Locale) => Promise<string | null>;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  locale,
  availableLocales,
  children,
}: {
  locale: Locale;
  availableLocales: readonly Locale[];
  children: ReactNode;
}) {
  const [localLocale, setLocalLocale] = useState<Locale>(locale);
  const [localePending, setLocalePending] = useState(false);
  const inFlight = useRef(false);

  const setLocale = async (next: Locale): Promise<string | null> => {
    if (inFlight.current || next === localLocale) return null;
    if (!availableLocales.includes(next)) return "That language is not available in this build.";
    inFlight.current = true;
    setLocalePending(true);

    const result = await commitLocalePreference(localLocale, next, setLocaleAction);
    if (result.locale !== localLocale) {
      setLocalLocale(result.locale);
      document.documentElement.lang = result.locale;
    }
    setLocalePending(false);
    inFlight.current = false;
    return result.error;
  };

  return (
    <I18nContext.Provider
      value={{
        locale: localLocale,
        dict: getDictionary(localLocale),
        availableLocales,
        localePending,
        setLocale,
      }}
    >
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}
