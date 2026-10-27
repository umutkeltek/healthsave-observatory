import type { Metadata } from "next";
import { headers } from "next/headers";
import { type ReactNode, Suspense } from "react";

import { CommandPalette } from "./components/CommandPalette";
import { I18nProvider } from "./components/I18nProvider";
import { PaletteHost } from "./components/PaletteHost";
import { Shell } from "./components/Shell";
import {
  SidebarStatus,
  SidebarStatusFallback,
  TopbarStatus,
  TopbarStatusFallback,
} from "./components/ShellStatus";
import "./globals.css";
import { getAvailableLocales, getLocale } from "./lib/i18n.server";
import { getDensity } from "./lib/prefs";
import { BARE_LAYOUT_HEADER } from "./lib/webAuth";

export const metadata: Metadata = {
  title: "HealthSave Observatory",
  description: "Your health data, interpreted - a local-first personal health console.",
};

// The layout awaits no backend reads: the chrome flushes immediately and the
// posture/sync status streams in via Suspense (see ShellStatus). The density
// cookie read is local and instant - it decides Essentials vs Observatory nav.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const [density, locale, requestHeaders] = await Promise.all([getDensity(), getLocale(), headers()]);
  const availableLocales = getAvailableLocales();
  // /login renders without the shell: its status widgets read health data, and
  // the visitor is not signed in yet. Only the proxy sets this header.
  const bare = requestHeaders.get(BARE_LAYOUT_HEADER) === "1";
  return (
    <html lang={locale} suppressHydrationWarning>
      <head>
        {/* Apply the saved theme before paint so there's no light/dark flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
 "(function(){try{var t=localStorage.getItem('theme');document.documentElement.dataset.theme=(t==='light'||t==='dark')?t:'light';}catch(e){document.documentElement.dataset.theme='light';}})();",
          }}
        />
      </head>
      <body>
        {bare ? (
          <I18nProvider locale={locale} availableLocales={availableLocales}>
            {children}
          </I18nProvider>
        ) : (
          <I18nProvider locale={locale} availableLocales={availableLocales}>
            <Shell
              density={density}
              sidebarStatus={
                <Suspense fallback={<SidebarStatusFallback />}>
                  <SidebarStatus />
                </Suspense>
              }
              topbarStatus={
                <Suspense fallback={<TopbarStatusFallback />}>
                  <TopbarStatus />
                </Suspense>
              }
            >
              {children}
            </Shell>
            {/* Command palette: pages-only while the catalog streams in. */}
            <Suspense fallback={<CommandPalette metrics={[]} />}>
              <PaletteHost />
            </Suspense>
          </I18nProvider>
        )}
      </body>
    </html>
  );
}
