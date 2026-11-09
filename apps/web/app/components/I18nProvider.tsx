"use client";

import { useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from "react";

import { setLocaleAction } from "../lib/actions";
import { runAction } from "../lib/session";
import { getDictionary, type Dictionary, type Locale } from "../lib/i18n";
import { adoptBroadcastLocale, commitLocalePreference, LOCALE_CHANNEL } from "../lib/localePreference";

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
  const router = useRouter();
  const [localLocale, setLocalLocale] = useState<Locale>(locale);
  const [localePending, setLocalePending] = useState(false);
  const inFlight = useRef(false);
  const shown = useRef(localLocale);
  shown.current = localLocale;

  // The server's locale moved (another tab switched, then this one rendered
  // again): follow it unless this tab is committing its own switch.
  const [serverLocale, setServerLocale] = useState<Locale>(locale);
  if (locale !== serverLocale) {
    setServerLocale(locale);
    if (!inFlight.current) setLocalLocale(locale);
  }

  // Another tab committed a switch: show it here at once and re-render the
  // server copy, as that tab did.
  const offered = availableLocales.join(",");
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(LOCALE_CHANNEL);
    channel.onmessage = (event: MessageEvent) => {
      if (inFlight.current) return;
      const next = adoptBroadcastLocale(shown.current, event.data, offered.split(",") as Locale[]);
      if (!next) return;
      setLocalLocale(next);
      document.documentElement.lang = next;
      router.refresh();
    };
    return () => channel.close();
  }, [router, offered]);

  const setLocale = async (next: Locale): Promise<string | null> => {
    if (inFlight.current || next === localLocale) return null;
    if (!availableLocales.includes(next)) return "That language is not available in this build.";
    inFlight.current = true;
    setLocalePending(true);

    const result = await commitLocalePreference(localLocale, next, (locale) => runAction(() => setLocaleAction(locale)));
    if (result.locale !== localLocale) {
      setLocalLocale(result.locale);
      document.documentElement.lang = result.locale;
      if (typeof BroadcastChannel !== "undefined") {
        const channel = new BroadcastChannel(LOCALE_CHANNEL);
        channel.postMessage(result.locale);
        channel.close();
      }
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
