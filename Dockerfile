# syntax=docker/dockerfile:1

# ---- The web UI --------------------------------------------------------------
# Base images pinned by digest: every build of a commit gets the same layers; Dependabot proposes new digests.
FROM node:26-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- The app -------------------------------------------------------------------
FROM python:3.12-alpine@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d
# ffprobe (from ffmpeg) reads durations; tini forwards signals; tzdata for local times;
# adb (android-tools) wakes the Shield and starts Kodi when the reader asks for something that needs it.
RUN apk add --no-cache ffmpeg tini tzdata android-tools
WORKDIR /app
COPY requirements.lock pyproject.toml README.md LICENSE ./
COPY src ./src
# The exact packages first (requirements.lock), then muthur itself without letting pip pick others.
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && rm -rf /root/.cache
COPY --from=web /web/dist ./web/dist

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MUTHUR_WEB=/app/web/dist MUTHUR_CONFIG=/config
# Never root; compose.yaml sets the user (PUID/PGID from .env) that owns the folders.
USER 1000:1000
EXPOSE 8580
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD wget -qO- http://127.0.0.1:8580/api/health >/dev/null || exit 1
ENTRYPOINT ["/sbin/tini", "--"]
# One process, one worker (ARCHITECTURE.md §3, guardrails).
CMD ["uvicorn", "muthur.web:get_app", "--factory", "--host", "0.0.0.0", "--port", "8580", "--workers", "1", "--no-access-log"]
