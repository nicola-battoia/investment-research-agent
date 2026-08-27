# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv

# VITE arguments are public browser configuration, so the secret-name check is a false positive.

# Build the Vite SPA with the same Node and pnpm major versions used locally.
FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@11.18.0 --activate

COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

COPY . .

# Vite embeds these browser-safe values in the generated JavaScript bundle.
ARG VITE_API_BASE_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

RUN test -n "$VITE_API_BASE_URL" \
    && test -n "$VITE_SUPABASE_URL" \
    && test -n "$VITE_SUPABASE_ANON_KEY" \
    && pnpm build

# Serve only the generated static files in production.
FROM caddy:2.11.4-alpine AS runtime

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=builder /app/dist /srv
