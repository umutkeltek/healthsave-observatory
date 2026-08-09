"use client";

import { createContext, type ReactNode, useContext, useState, useTransition } from "react";

import { setLocaleAction } from "../lib/actions";
import { getDictionary, type Dictionary, type Locale } from "../lib/i18n";

type I18nContextValue = {
  locale: Locale;
  dict: Dictionary;
  setLocale: (locale: Locale) => void;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: ReactNode;
}) {
  const [localLocale, setLocalLocale] = useState<Locale>(locale);
  const [, startTransition] = useTransition();

  const setLocale = (next: Locale) => {
    setLocalLocale(next);
    document.documentElement.lang = next;
    startTransition(() => setLocaleAction(next).then(() => undefined));
  };

  return (
    <I18nContext.Provider
      value={{
        locale: localLocale,
        dict: getDictionary(localLocale),
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
