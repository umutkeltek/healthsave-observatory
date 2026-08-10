import type { Metadata } from "next";
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

export const metadata: Metadata = {
  title: "HealthSave Observatory",
  description: "Your health data, interpreted - a local-first personal health console.",
};

// The layout awaits no backend reads: the chrome flushes immediately and the
// posture/sync status streams in via Suspense (see ShellStatus). The density
// cookie read is local and instant - it decides Essentials vs Observatory nav.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const [density, locale] = await Promise.all([getDensity(), getLocale()]);
  const availableLocales = getAvailableLocales();
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
      </body>
    </html>
  );
}
