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
FROM python:3.15-alpine@sha256:0f9552bb28711333da16915ec146f5e6bb44a7fdac9ced15dc17c2e0206346dd
# ffprobe (from ffmpeg) reads durations; tini forwards signals; tzdata for local times;
# adb (android-tools) wakes the Shield and starts Kodi when the reader asks for something that needs it;
# bsdtar (libarchive-tools, BSD licence) opens rar, 7z and tar downloads for the automatic pick-up (archives.py).
RUN apk add --no-cache ffmpeg tini tzdata android-tools libarchive-tools
WORKDIR /app
COPY requirements.lock pyproject.toml README.md LICENSE ./
COPY src ./src
# The exact packages first (requirements.lock), then muthur itself without letting pip pick others.
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && rm -rf /root/.cache
COPY --from=web /web/dist ./web/dist

# TINI_SUBREAPER: in the relay (the host's PID namespace) tini isn't PID 1; as a subreaper it still reaps (tini's README).
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    MUTHUR_WEB=/app/web/dist MUTHUR_CONFIG=/config TINI_SUBREAPER=1
# Never root; compose.yaml sets the user (PUID/PGID from .env) that owns the folders.
USER 1000:1000
EXPOSE 8580
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD wget -qO- http://127.0.0.1:8580/api/health >/dev/null || exit 1
ENTRYPOINT ["/sbin/tini", "--"]
# One process, one worker (ARCHITECTURE.md §3, guardrails).
CMD ["uvicorn", "muthur.web:get_app", "--factory", "--host", "0.0.0.0", "--port", "8580", "--workers", "1", "--no-access-log"]
