import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Self-contained server bundle for the Docker image (apps/web/Dockerfile).
  output: "standalone",
  devIndicators: false,
  allowedDevOrigins: ["127.0.0.1"],
  // View Transitions: crossfade between page navigations so the shell (sidebar,
  // topbar) stays stable and only the content pane morphs. Natively supported in
  // Next.js 16.2+; browsers that don't support it fall back to full navigation.
  experimental: {
    viewTransition: true,
  },
  turbopack: {
    root: appRoot,
  },
  // Dashboard reads the HealthSave Observatory v2 API. Server components fetch API_BASE
  // directly; this rewrite lets any client-side fetch hit same-origin /api/*.
  async rewrites() {
    const api = process.env.API_BASE ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
