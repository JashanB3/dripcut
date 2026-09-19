# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS node-runtime

ARG BGUTIL_VERSION=2.0.0

# Build the documented on-demand bgutil provider once at image build time.  The
# runtime invokes its script locally; it never opens a public listening port.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git \
    && git clone --depth 1 --branch "${BGUTIL_VERSION}" \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/dripcut/bgutil \
    && cd /opt/dripcut/bgutil/server \
    && npm ci \
    && npx tsc \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5 \
    DRIPCUT_HOME=/var/lib/dripcut \
    DRIPCUT_OUTPUT=/var/lib/dripcut/output \
    DRIPCUT_TEMP=/tmp/dripcut \
    DRIPCUT_ENV=production \
    DRIPCUT_AUTH_PROVIDER=supabase \
    DRIPCUT_TENANT_PROVIDER=supabase \
    DRIPCUT_AUTH_REQUIRED=1 \
    DRIPCUT_COOKIE_SECURE=1 \
    DRIPCUT_MAX_WORKERS=1 \
    DRIPCUT_MAX_CONCURRENT_VIDEO_JOBS=1 \
    DRIPCUT_FFMPEG_THREADS=1 \
    DRIPCUT_FFMPEG_NICE=10 \
    DRIPCUT_FFMPEG_PRESET=veryfast \
    DRIPCUT_MAX_OUTPUT_FPS=30 \
    DRIPCUT_MAX_UPLOAD_MB=512 \
    DRIPCUT_MAX_VIDEO_DURATION_SECONDS=600 \
    DRIPCUT_MIN_FREE_DISK_MB=1536 \
    DRIPCUT_MAX_ACTIVE_JOBS_PER_USER=5 \
    DRIPCUT_FFMPEG_TIMEOUT_SECONDS=1800 \
    DRIPCUT_RENDER_PROFILE=720p \
    DRIPCUT_MVP_PROFILE=1 \
    DRIPCUT_CREATE_ZIP=0 \
    DRIPCUT_ENABLE_AI_ANALYSIS=0 \
    DRIPCUT_ENABLE_AI_THUMBNAILS=0 \
    DRIPCUT_ENABLE_AUTO_CAPTIONS=0 \
    DRIPCUT_ENABLE_INSTAGRAM=0 \
    DRIPCUT_TRANSCRIPTION_PROVIDER=groq

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        ffmpeg \
        libgomp1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp EJS requires Node 22+, but not npm or frontend dependencies at runtime.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /opt/dripcut/bgutil/server /opt/dripcut/bgutil/server

WORKDIR /app

COPY pyproject.toml requirements-server.txt README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade setuptools wheel \
    && python -m pip install --requirement requirements-server.txt \
    && python -m pip install --no-deps . \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin dripcut \
    && mkdir -p /var/lib/dripcut \
    && chown -R dripcut:dripcut /var/lib/dripcut

USER dripcut

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '10000') + '/api/health', timeout=4).read()"

CMD ["sh", "-c", "exec uvicorn dripcut.api.app:create_app --factory --host 0.0.0.0 --port \"${PORT:-10000}\""]
