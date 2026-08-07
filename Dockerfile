FROM node:24-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS web-build

WORKDIR /app/web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHRONOS_DATA_DIR=/app/data
WORKDIR /app

RUN groupadd --system --gid 10001 chronos \
    && useradd --system --uid 10001 --gid chronos --home-dir /app chronos

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY infrastructure/migrations infrastructure/migrations
COPY --from=web-build /app/web/dist web/dist

RUN mkdir -p /app/data && chown -R chronos:chronos /app
USER chronos

EXPOSE 18280
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('CHRONOS_LISTEN_PORT','18280')+'/api/health', timeout=3)"

CMD ["python", "-m", "app"]
