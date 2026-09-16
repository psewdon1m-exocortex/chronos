# Deploying chronos

This runbook applies to the next signed chronos-v0.1.3 release. Source changes are not a published release. Start only after the exact immutable tag, anonymous assets, signature and Part 12 report pass CI.

## Ownership and release order

Kernel, Volt and Saturn are already deployed and are not replaced by this installer. Publish compatible Updater 0.4.6 first; the head bundle pins it. Updater upgrades an older host agent and adds this head to its existing registry. Existing newer agents are reused. Publish Neptune Linux 0.1.6 before connecting the new heads: it bounds shared Kernel requests and preserves older state. Publish Gryphon Linux 0.1.4 before Chronos so the global command catalog, persistent keyboard and pending input protocol are available. Migration fixtures cover Updater 0.4.3/0.4.4/0.4.5, Neptune Linux 0.1.0/0.1.1 and unified 0.1.5 and Gryphon Linux 0.1.0/0.1.1; first read actual server versions before upgrading.

The operator explicitly authorized this head profile on 2026-09-14. Its additive typed profile lives in app/deployment-profile.json. Kernel's initial six-service profile remains unchanged. Add bindings manually without replacing or pruning existing entries; the head validates its own required keys, including content branch as a branch rather than a URL.

## Operator sequence on the intended Linux server

Record hostname, working directory and installed agent versions before changes. Prepare Docker Compose v2, curl, OpenSSL, Python 3 and server nginx yourself. DNS egress, github.com/release-assets.githubusercontent.com, ghcr.io and the Kernel/Saturn HTTPS origins must be reachable. No incoming application port is public.

```bash
curl -fsSL https://github.com/psewdon1m-exocortex/chronos/releases/download/chronos-v0.1.3/bootstrap.sh | sudo sh
sudoedit /opt/exocortex/chronos/.env
sudo chmod 600 /opt/exocortex/chronos/.env
sudo chronos-install
sudo chronos-install status
curl -fsS http://127.0.0.1:18280/api/health
```

Fill only CHRONOS_ACCESS_KEY, KERNEL_URL (canonical HTTPS origin), and KERNEL_SERVICE_TOKEN (the scoped machine credential issued for this head). Bootstrap supplies the immutable image digest, local session secret and helper control/export credentials. Do not copy another service's .env or release private key. The installer generates the actual Docker gateway proxy addresses; there is no operator IP allowlist or wildcard proxy trust.

CHRONOS_ACCESS_KEY must be explicitly present but has no length, composition,
character-set, URL-safe/ASCII, strength/entropy or value-denylist policy. Every
supported path must preserve the exact operator-supplied value. The current
12-character validation and whitespace stripping are a documented `BST-13`
implementation gap, not deployment requirements.

Bootstrap has no arguments. It rejects a mismatched signature, version, digest, unsafe tar member, foreign existing trust key or existing installation. After an interrupted staging, inspect the fixed target before removing only a newly created incomplete directory; an established deployment must be updated through its authenticated Updater. Re-running prepare/install preserves operator values. An update merges missing safe defaults; rollback restores the exact previous .env and deployment plus the supplied data backup.

## Volt values and Kernel bindings

Create a separate Volt entry/field for every value below and bind the Register key to volt://ENTRY_UUID/1 (or the appropriate numeric field 1–5). Never put a plaintext credential into Register. Existing common bindings services.saturn.sni/port and repositories.updater/neptune.url remain authoritative. Do not edit the six-service seed/profile to add this head.

| Register key | Value / responsibility |
| --- | --- |
| repositories.chronos.url | https://github.com/psewdon1m-exocortex/chronos |
| services.chronos.sni | Your canonical hostname, without scheme or path |
| services.chronos.port | Public HTTPS port, normally 443 |
| services.chronos.health.path | /api/public/reachability |
| services.chronos.health.contract | public-readiness |
| services.chronos.backup.saturn_slug | Exact producer slug returned by Saturn enrollment |

IndexNow's verification key is intentionally public and is not an access credential. In Laboratory it is an optional environment setting. GitHub, Saturn, Gemini and Google private credentials are resolved through Kernel, remain in memory and are excluded from backups/log exports. The Kernel URL and initial machine token are the bootstrap exception; subsequent Laboratory connection edits are encrypted locally and excluded from portable recovery.

## Agents and public activation

In the head's Settings, initialize Neptune with a one-time archive setup code issued in Saturn. One host daemon can serve the existing projects and both new heads. Saturn → Synchronization owns desired schedules, manual remote runs and run receipts. A saved schedule or installed binary is not proof of a successful backup: inspect enrolled/linked state, last seen, last successful backup, next due and overdue status separately. Revoke old credentials in their issuer and reconnect using a newly issued code; do not reuse an already consumed code.

In Chronos Settings initialize Gryphon, register/select a bot, connect it and complete its Telegram user binding. The canonical authenticated callback is /internal/gryphon/command on the current Kernel-resolved Chronos HTTPS origin. The compatibility /api/internal path is host-only. Bot tokens are write-only; a returned job must reach COMPLETED before showing success. Telegram delivery is verified only after the operator binds a real bot and user.

Use nginx.server.example.conf as the service-specific server configuration template. It is an example for the operator-managed nginx, not a proxy installed by this service. Configure an independent default server rejecting unknown Host/SNI, exact server_name and certificate pair, then run nginx -t. The template binds only the intended upstream, forwards Host/proto/client identity, denies machine-only routes, and sets route-specific upload limits/timeouts with bounded server staging. No coturn is installed. Login remains reachable from every client IP; all Chronos pages are noindex.

Run public checks from two independent external clients after nginx configuration: DNS/TLS/SNI; correct canonical links; unauthenticated private API refusal; draft file refusal; CSRF and logout replay rejection; no direct 18280/database port; oversized upload 413. Unknown/stale telemetry is not zero. /api/health reports core database/Register readiness; authenticated /api/ready reports the required agents/dependencies. It explicitly does not claim external provider delivery.

## Recovery and acceptance

Export → Neptune → Saturn receipt → actual stored SHA-256 → download → isolated clean restore is the required drill. Local settings, content/history, authoritative metadata and Access Key verifier are included; plaintext secrets are not. Restore retains the target enrollment credentials and invalidates all previous sessions. Log in again with the restored Access Key. Timer IDs, source/provenance, soft-deleted entries and retained Undo/command history survive; test a new session and Undo immediately after restore. Undo is bounded to 30 days / 10,000 entries; command replay history to 30 days / 100,000 entries. Ambiguous in-flight commands from older releases are not executed twice.

A backup on the same physical failure domain is not independent disaster recovery. Confirm a separate Saturn storage/account and a tested off-host recovery copy using the operator's infrastructure policy. Do not label that production check PASS from a local fixture.

After a change record UTC time, hostname, service version/image digest, container state, redacted logs, command/endpoint, migration result, core readiness, authenticated integrations and backup receipt/rollback metadata. Exclude .env, bearer values, private keys and request bodies. Only close an incident after its regression and updated runbook pass. The release gate stores production activation as NOT_RUN until the external checks above are performed.

Chronos restore accepts a bounded 128 MiB archive; configure the upstream upload route accordingly.
