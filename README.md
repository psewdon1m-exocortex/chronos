# Chronos

> Documentation authority: the workspace-wide [Part 00](https://github.com/psewdon1m-exocortex/general/blob/main/PART_00_SYSTEM_UNIFICATION_SPECIFICATION.md)
> and its applicable Parts are normative. This repository documents
> Chronos-specific details only; a conflict is corrected here and a material
> implementation difference follows the Part 00 divergence protocol.

## Required pre-push gate

After native checks and before every push, complete the checks required by
[Part 06 — Unified acceptance checklist](https://github.com/psewdon1m-exocortex/general/blob/main/PART_06_UNIFIED_ACCEPTANCE_CHECKLIST.md) and run the versioned policy in
`.github/pre-push-gate.json` through `scripts/pre-push-gate.py`. CI repeats the
gate on `main`. Security is always reviewed; backup/restore, updater, embedded
Documentation and affected technical docs are reviewed when relevant. Apply
SEO/GEO checks to intentionally public/indexable surfaces and concealment,
crawler and probe-resistance checks to private or authenticated surfaces.
Every area requires `PASS` evidence or a reasoned `N/A`.

## Автоматические резервные копии

После обычной установки создайте в Saturn одноразовый Neptune setup code. Если локальный Neptune уже установлен, но Chronos ещё не связан с ним, откройте Settings → Backup, нажмите **Initialize Neptune** и введите код. Команда `sudo chronos-install backup` остаётся способом установить отсутствующий агент и резервным CLI-сценарием. Расписание задаётся в Saturn → Synchronization.

Chronos is a single-operator time-tracking service for the Exocortex ecosystem.

Chronos runs in three modes:
- Gryphon command adapter for quick timer start/stop through Telegram.
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
- Telegram transport and identity binding: external Gryphon gateway
- Infrastructure: Docker Compose, GitHub Actions

## Layout

- `app/` - core API and runtime
- `web/` - frontend interface
- `infrastructure/` - migrations and deployment
- `.docs/` - [module boundary](.docs/description.md),
  [engineering rules](.docs/rules.md) and
  [repository/release workflow](.docs/git-management.md)

## Local development

1. Copy `.env.example` to `.env`
2. Fill required values
3. Run:

```bash
docker compose -f compose.yaml up -d --build
```

Health check endpoint: `GET /api/health`

## Release identity

Chronos follows SemVer from the initial `0.0.1`. A plain `v0.0.1`-style tag
runs verification-only CI and cannot publish or mutate a release. Only
`chronos-vMAJOR.MINOR.PATCH` starts the protected Chronos release workflow.

> Current implementation gap (2026-09-13): `ci.yml` does not yet listen to
> plain `v*` tags, and the release workflow does not yet sign the manifest or
> build an exact-version bootstrap with the embedded public key described
> below. This is a material Part 04/05 divergence and blocks the next release
> until a separate CI/code change is implemented and verified.

## Production target

The following is the required Part 04 procedure, not proof that the current
release artifacts already satisfy it. Do not use it until the release gap
recorded above is closed and verified.

Bootstrap one explicit immutable Chronos release (replace `X.Y.Z`), edit only
Chronos's own mode-`0600` `.env`, then use `compose.production.yaml`:

```bash
curl -fsSL https://github.com/psewdon1m-exocortex/chronos/releases/download/chronos-vX.Y.Z/bootstrap.sh | sudo sh
```

Required target release contract (subject to the implementation gap above):
release CI keeps Chronos's private release-signing key in GitHub Secrets and
embeds only its derived public counterpart in this versioned bootstrap. The
bootstrap creates `/etc/exocortex/release-trust/chronos.pem`, verifies the
signed manifest before downloading the service, and fails on an existing
mismatching trust key. No `scp`, manual release-key fingerprint or separately
downloaded public key is part of installation.

```bash
sudoedit /opt/exocortex/chronos/.env
sudo chmod 600 /opt/exocortex/chronos/.env
sudo chronos-install
sudo chronos-install status
curl -fsS http://127.0.0.1:18280/api/health
```

Public routing and TLS are handled only by the server-managed Nginx. Chronos
does not ship or run an embedded Nginx and does not use coturn; a future genuine
WebRTC NAT-traversal feature would require a separately reviewed TURN design.

The release bundle contains Chronos's own `nginx.security.conf`. Include it
inside the public HTTPS `server {}` block (for example,
`include /opt/exocortex/chronos/nginx.security.conf;`) and run `nginx -t`
before reload. The policy is route-list independent: new UI tabs require no
Nginx edits because only `/` serves the SPA shell.

The login page remains reachable from every client IP in the
public-authenticated profile. Do not add `OPERATOR_CIDR`, a VPN prerequisite or
a source-IP allow-list. The Access Key and bounded Chronos session protect all
operator data and API routes.

## Required environment keys

- `KERNEL_URL`
- `KERNEL_SERVICE_TOKEN`
- `CHRONOS_ACCESS_KEY`
- `CHRONOS_SESSION_SECRET`
- `CHRONOS_DB_PASSWORD`
- `UPDATER_CONTROL_TOKEN`
- `UPDATER_SOCKET_GID`
- `GRYPHON_SERVICE_TOKEN_HOST_FILE`
- `GRYPHON_SOCKET_PATH`

## Kernel Register contract

Chronos expects every present Register value below to be a strict
`volt://<entry-id>/<field-id>` reference:
- `repositories.chronos.url` or `services.chronos.url`
- `services.chronos.sni` (domain binding)

The watcher batch-resolves the relevant keys through Kernel and applies the
returned values live without persisting them.

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

## Gryphon / Telegram behavior

- Gryphon owns the bot token, webhook, update deduplication and the
  service-scoped Telegram identity binding. Chronos contains no bot runtime.
- Command flow: start/stop by category, quick summary, retype the last completed
  session with `/chronos retype`, and insert a completed recent session with
  `/chronos backfill MINUTES`.
- Chronos exposes `POST /api/internal/gryphon/command`; the endpoint accepts
  only the bearer token shared when the service connection is created.
- Connect one or more bot tokens with `gryphon bot connect`, then use **Link
  Chronos function** in the Bot connection Settings card to select one of those
  bots. Chronos receives only its service credential and never sees a bot token.
- When a bot function is connected but no Telegram user is bound, **Initialize
  bot** in Settings creates a one-time `/link CODE` challenge. Send that command
  in a private chat with the selected bot. `gryphon link issue chronos` remains
  the equivalent CLI fallback. The Settings card also checks and installs
  verified Gryphon Linux updates through the host Updater.
- Reminders and daily summaries are sent through Gryphon's service-scoped Unix
  socket.

Chronos has no Volt URL or token. Kernel contacts Volt on Chronos' behalf and
Chronos keeps the returned plaintext only in process memory.

## Roadmap

- Multi-user support (current build is single-operator only).
- Optional SSO and external telemetry.
