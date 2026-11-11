FROM node:24-slim AS web

# Public build-time values only (they end up in the browser bundle anyway).
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_DEMO_EMAIL
ARG VITE_DEMO_PASSWORD
ARG VITE_VAPID_PUBLIC_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_DEMO_EMAIL=$VITE_DEMO_EMAIL \
    VITE_DEMO_PASSWORD=$VITE_DEMO_PASSWORD \
    VITE_VAPID_PUBLIC_KEY=$VITE_VAPID_PUBLIC_KEY

WORKDIR /web

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

RUN useradd --create-home --uid 1000 user && mkdir /app && chown user:user /app

# No uv cache in the image; the venv is built by the runtime user so no chown layer duplicates it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/user

WORKDIR /app
USER user

COPY --chown=user:user pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY --chown=user:user src/ ./src/
RUN uv sync --frozen --no-dev

COPY --from=web --chown=user:user /web/dist ./web/dist

# demo-server binds all interfaces by default and reads the port from $PORT (Cloud Run sets it).
# --no-sync: the venv is final at build time; skip the re-install check on every cold start.
ENV SOLOWATCH_WEB_DIST=/app/web/dist \
    PORT=8080

EXPOSE 8080

CMD ["uv", "run", "--frozen", "--no-dev", "--no-sync", "solowatch", "demo-server"]
