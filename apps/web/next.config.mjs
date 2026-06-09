/** @type {import('next').NextConfig} */
const nextConfig = {
  // Self-contained server bundle for the Docker image (apps/web/Dockerfile).
  output: "standalone",
  // Dashboard reads the HealthSave Observatory v2 API. Server components fetch API_BASE
  // directly; this rewrite lets any client-side fetch hit same-origin /api/*.
  async rewrites() {
    const api = process.env.API_BASE ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
