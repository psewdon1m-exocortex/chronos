# Chronos

Chronos is a production-ready time tracking service for the Exocortex ecosystem.

Chronos runs in three modes:
- Telegram bot for quick timer start/stop.
- Web UI for full control and analytics.
- Kernel + Updater integration for centralized domain and release management.

## What Chronos does

- Tracks session blocks in four fixed categories:
  - Recovery
  - Accumulation
  - Execution
  - Maintenance
- Personal settings for a single operator:
  - profile data
  - timezone
  - category priorities
  - reminder rules
  - data export and history
- Session workflow:
  - start and stop
  - manual corrections
  - stable public IDs such as `t-00000001`
  - delete and restore entries
- Analytics by day and period, including percentage splits.
- Full backup and restore flow using JSON archive.
- Release status + restore flow through Updater.

## Stack

- Backend: FastAPI + asyncpg + PostgreSQL
- Frontend: React + Vite
- Telegram: aiogram
- Infrastructure: Docker Compose, GitHub Actions

## Layout

- `app/` - core API and runtime
- `web/` - frontend interface
- `infrastructure/` - migrations and deployment
- `.docs/` - internal documentation

## Local development

1. Copy `.env.example` to `.env`
2. Fill required values
3. Run:

```bash
docker compose -f compose.yaml up -d --build
```

Health check endpoint: `GET /api/health`

## Production

Use `compose.production.yaml`:

```bash
sudo chronos-install
```

or

```bash
docker compose --env-file .env -f compose.production.yaml up -d
```

Public routing and TLS are expected to be handled by Kernel/Nginx layer.

The release bundle contains Chronos's own `nginx.security.conf`. Include it
inside the public HTTPS `server {}` block (for example,
`include /opt/exocortex/chronos/nginx.security.conf;`) and run `nginx -t`
before reload. The policy is route-list independent: new UI tabs require no
Nginx edits because only `/` serves the SPA shell.

## Required environment keys

- `KERNEL_URL`
- `KERNEL_SERVICE_TOKEN`
- `CHRONOS_ADMIN_USERNAME`
- `CHRONOS_ADMIN_PASSWORD`
- `CHRONOS_SESSION_SECRET`
- `CHRONOS_DB_PASSWORD`
- `UPDATER_CONTROL_TOKEN`
- `UPDATER_SOCKET_GID`

## Kernel Register contract

Chronos expects:
- `repositories.chronos.url` or `services.chronos.url`
- `services.chronos.sni` (domain binding)
- `services.chronos.telegram_api` or `services.chronos.telegram_bot_api`
- `secrets.chronos.telegram_bot_token` from `secret://env/...`

Values are refreshed by watcher loop and applied live.

## Updater contract

1. `GET /api/admin/repository` - repository status
2. `POST /api/admin/update` - create update request
3. `POST /api/internal/updater/restore` - restore on deploy result

Restore header: `X-Updater-Token`.

## Main API

- `POST /api/admin/auth`
- `GET /api/timers/active`
- `POST /api/timers/start`
- `POST /api/timers/stop`
- `DELETE /api/timers/active`
- `GET /api/timers/history`
- `POST /api/settings`
- `GET /api/settings`
- `GET /api/analytics/overview`
- `GET /api/health`

## Telegram behavior

- Bot works independently from web session state.
- Command flow: start/stop by category, quick summary, retype the last completed
  session with `/retype`, and insert a completed recent session with `/backfill`.
- Token priority:
  1. `services.chronos.telegram_api` from Kernel Register
  2. `CHRONOS_TELEGRAM_BOT_TOKEN` from `.env` (local fallback only)

## Roadmap

- Multi-user support (current build is single-operator only).
- Optional SSO and external telemetry.
