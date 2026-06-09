# syntax=docker/dockerfile:1
# HealthSave Observatory web — Next.js 15 standalone build, served by Node.
# Build context is apps/web (see docker-compose.yml `web` service).

FROM oven/bun:1 AS build
WORKDIR /app
# Install deps first for layer caching, then build the standalone server.
COPY package.json ./
RUN bun install
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN bun run build

FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=4173 \
    HOSTNAME=0.0.0.0
RUN useradd --create-home --uid 10001 appuser
# Next standalone output: a minimal server.js + traced node_modules + static.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER appuser
EXPOSE 4173
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:4173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
