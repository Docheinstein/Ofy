# syntax=docker/dockerfile:1

# ---- frontend build -------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- runtime --------------------------------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    OFFLINER_DATA_DIR=/data \
    OFFLINER_LIBRARY_DIR=/music \
    OFFLINER_STATIC_DIR=/app/static \
    OFFLINER_PORT=8080

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

# Deno is the JavaScript runtime yt-dlp uses to solve YouTube player challenges.
COPY --from=denoland/deno:bin-2.5.6 /deno /usr/local/bin/deno
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist /app/static

ENV PATH="/app/backend/.venv/bin:$PATH"
VOLUME ["/data", "/music"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://localhost:8080/api/health || exit 1
CMD ["python", "-m", "offliner"]
