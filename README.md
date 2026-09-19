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

## Required pre-release known-problem gate

Before a service-qualified release is finalized, evaluate every active ID in
[Part 12](https://github.com/psewdon1m-exocortex/general/blob/main/PART_12_KNOWN_DEPLOYMENT_AND_OPERATIONS_PROBLEMS.md) against the exact candidate. Retain
`known-problems-report.json` bound to the service revision, qualified tag,
immutable central-documentation revision and catalog digest. Missing, stale,
failed, unknown or unsupported `N/A` evidence blocks publication. The workflow enforces separate pre-signing and final phases. See [DEPLOYMENT.md](DEPLOYMENT.md) for the current release order and operator activation checks.

## Автоматические резервные копии

После обычной установки создайте в Saturn одноразовый Neptune setup code. Откройте Settings → Backup, нажмите **Initialize Neptune** и введите код. Интерфейс устанавливает отсутствующий агент или подключает существующий; `sudo chronos-install backup` остаётся эквивалентным CLI-сценарием. Расписание задаётся в Saturn → Synchronization.

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
- Manifest-verified ZIP backup and restore with legacy JSON import.
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

> The next source release implements signed exact-version bootstrap, Access Key
> sessions and typed head profiles. Previously published assets remain unchanged;
> use this flow only after the new qualified release passes CI.

## Production target

The following procedure applies to the next qualified release; see
[DEPLOYMENT.md](DEPLOYMENT.md) for its exact version and required bindings.

Bootstrap one explicit immutable Chronos release (replace `X.Y.Z`), edit only
Chronos's own mode-`0600` `.env`, then use `compose.production.yaml`:

```bash
curl -fsSL https://github.com/psewdon1m-exocortex/chronos/releases/download/chronos-vX.Y.Z/bootstrap.sh | sudo sh
```

Release contract:
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

`CHRONOS_ACCESS_KEY` is a required, explicitly supplied opaque exact value, not
a password governed by a strength policy. It has no minimum/maximum length,
required or forbidden characters, URL-safe/ASCII restriction, entropy check or
known/example/placeholder denylist. Bootstrap, login, rotation and restore must
not trim, normalize, fold case or truncate it; only missing configuration is
invalid.

> Implementation gap (2026-09-14): the current installer and runtime require at
> least 12 characters, the change endpoint repeats that minimum and startup
> strips surrounding whitespace. These behaviors violate shared issue `BST-13`
> and block the next production release until code and tests are corrected.

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

Chronos requires the additive typed profile in [app/deployment-profile.json](app/deployment-profile.json). All values use numeric Volt field references and are resolved only through Kernel. Required bindings and the operator sequence are in [DEPLOYMENT.md](DEPLOYMENT.md).

## Updater contract

- GET /api/updates/status and POST /api/updates/check.
- `/api/update-flow/check`, `/backup`, `/install/{component}` and `/jobs` implement
  the saved-copy protocol. The old `/api/updates/apply` route returns 426.
- The same standard ZIP is downloaded and returned for installation; Updater keeps
  rollback bytes only in RAM and requires the saved ZIP after a restart.
- POST /api/internal/updater/restore is a token-protected host-local callback.

## Main API

- POST /api/auth/login and /api/auth/logout.
- GET /api/dashboard; POST /api/timer/press and /api/timer/stop.
- GET/POST /api/sessions; PUT/DELETE /api/sessions/{id}.
- POST /api/actions/undo; GET/PUT /api/settings.
- GET /api/analytics and /api/export.csv.
- GET /api/health (core readiness); authenticated GET /api/ready (dependencies).

## Gryphon / Telegram behavior

- Gryphon owns the bot token, webhook, update deduplication and the
  service-scoped Telegram identity binding. Chronos contains no bot runtime.
- Command flow: `/timer` opens the four persistent category buttons; `/active`,
  `/today`, `/week` and `/month` report timer state; `/stop`, `/undo` and
  `/retype` mutate it; `/backfill` prompts for minutes and also accepts a minute
  value on the same command.
- Chronos exposes `POST /internal/gryphon/command`; the endpoint accepts
  only the bearer token shared when the service connection is created.
- Connect a bot with `sudo gryphon bot connect ALIAS`, then use **Link Chronos
  function** in the Bot connection Settings card to select it. Chronos never
  accepts or persists a bot token.
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

## Unified updates (protocol 2)

See [Update protocol, saved ZIP and first migration](docs/UPDATE-PROTOCOL.md).
The UI uses Updater **0.5.0**, an exact selected version, the standard ZIP saved
on the operator PC, and durable status/progress. Helper updates use the same
dialog without a backup. No update ZIP is retained on the application host.
