import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { type ReactNode, Suspense } from "react";

import { Shell } from "./components/Shell";
import {
  SidebarStatus,
  SidebarStatusFallback,
  TopbarStatus,
  TopbarStatusFallback,
} from "./components/ShellStatus";
import "./globals.css";

const sans = Geist({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "HealthSave Observatory",
  description: "Your health data, interpreted — a local-first personal health console.",
};

// The layout awaits nothing: the chrome flushes immediately and the
// posture/sync status streams in via Suspense (see ShellStatus). This is half
// of the old first-byte waterfall; the other half was the page's series fan-out.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        {/* Apply the saved theme before paint so there's no light/dark flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('theme');document.documentElement.dataset.theme=(t==='light'||t==='dark')?t:'dark';}catch(e){document.documentElement.dataset.theme='dark';}})();",
          }}
        />
      </head>
      <body>
        <Shell
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
      </body>
    </html>
  );
}
