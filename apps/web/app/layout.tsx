import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import "./globals.css";
import { agoLabel, safePrivacy, safeReadiness } from "./lib/load";

const sans = Geist({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "HealthSave · datahub",
  description: "Your health data, interpreted — a local-first personal health console.",
};

// The shell fetches the egress posture + freshness for the sidebar/topbar status.
// Best-effort: defaults keep the chrome sensible when the backend is unreachable.
export default async function RootLayout({ children }: { children: ReactNode }) {
  const [privacy, readiness] = await Promise.all([safePrivacy(), safeReadiness()]);
  const provider = privacy?.provider ?? "ollama";
  const isLocal = privacy?.is_local ?? true;
  const synced = agoLabel(readiness?.last_ingested_at ?? readiness?.last_observation_at ?? null);

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
        <div className="app">
          <Sidebar provider={provider} isLocal={isLocal} synced={synced} />
          <div className="app-main">
            <Topbar provider={provider} isLocal={isLocal} synced={synced} />
            <main className="content">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
