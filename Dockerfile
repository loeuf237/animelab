FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm AS server
LABEL org.opencontainers.image.title="AnimeLab" \
      org.opencontainers.image.source="https://github.com/loeuf237/animelab" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.description="AnimeLab standalone web server"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/data \
    ANIMAN_HOST=0.0.0.0 \
    ANIMAN_PORT=8080 \
    ANIMAN_RELOAD=false \
    ANIMAN_DB_PATH=/data/.animan/db/animan.sqlite3 \
    ANIMAN_CACHE_DIR=/data/.animan/cache \
    ANIMAN_DOWNLOAD_DIR=/downloads

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 animelab \
    && useradd --uid 1000 --gid 1000 --home-dir /data --no-create-home animelab \
    && mkdir -p /data/.animan/db /data/.animan/cache /data/.animan/extensions /downloads \
    && chown -R animelab:animelab /data /downloads

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY animelab/ ./animelab/
COPY run.py ./
COPY LICENSE NOTICE ./
COPY --from=frontend /build/dist/ ./frontend/dist/

USER 1000:1000
EXPOSE 8080
VOLUME ["/data", "/downloads"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('ANIMAN_PORT', '8080') + '/app/', timeout=4).close()"]
CMD ["python", "run.py"]
