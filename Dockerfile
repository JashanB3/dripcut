# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DRIPCUT_HOME=/var/lib/dripcut \
    DRIPCUT_OUTPUT=/var/lib/dripcut/output \
    DRIPCUT_MAX_WORKERS=1 \
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

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade setuptools wheel \
    && python -m pip install . \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin dripcut \
    && mkdir -p /var/lib/dripcut \
    && chown -R dripcut:dripcut /var/lib/dripcut

USER dripcut

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '10000') + '/api/health', timeout=4).read()"

CMD ["sh", "-c", "exec uvicorn dripcut.api.app:create_app --factory --host 0.0.0.0 --port \"${PORT:-10000}\""]
