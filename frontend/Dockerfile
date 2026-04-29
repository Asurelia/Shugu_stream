# ── Builder ────────────────────────────────────────────────────────────────
# next.config.js does not enable `output: "standalone"` — we copy the full
# .next + node_modules to keep the standard `npm start` launch path working
# without forcing a config change.
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache: only invalidated when lock changes).
COPY frontend/package.json frontend/package-lock.json /app/
RUN npm ci

# Copy source and build.
COPY frontend/ /app/
RUN npm run build

# ── Runtime ────────────────────────────────────────────────────────────────
FROM node:22-alpine

WORKDIR /app

# Drop root: node:22-alpine ships a built-in "node" user (uid 1000).
# We chown after copying so the process can write .next/cache if needed.
COPY --from=builder --chown=node:node /app/.next /app/.next
COPY --from=builder --chown=node:node /app/node_modules /app/node_modules
COPY --from=builder --chown=node:node /app/package.json /app/package.json
COPY --from=builder --chown=node:node /app/public /app/public

USER node

EXPOSE 3005

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD wget -qO- http://localhost:3005/ > /dev/null || exit 1

CMD ["npm", "start"]
