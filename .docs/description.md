# Chronos module description

Chronos is the single-operator time-tracking service in the Exocortex
workspace. The workspace-wide documentation in
[Part 00](https://github.com/psewdon1m-exocortex/general/blob/main/PART_00_SYSTEM_UNIFICATION_SPECIFICATION.md) is
normative; this file adds Chronos-specific detail and cannot weaken an
applicable central requirement.

## Responsibilities

- Track timer sessions in the fixed Recovery, Accumulation, Execution and
  Maintenance categories.
- Provide the authenticated web interface, history, corrections, analytics,
  settings, audit trail, backup and restore workflows.
- Resolve non-secret coordinates and secret references through Kernel Register
  and use the host Updater for verified releases and shared-agent operations.
- Expose a service-scoped command adapter for Gryphon.

## Telegram boundary

Chronos contains no Telegram bot runtime and stores no Telegram bot token.
Gryphon owns bot tokens, webhooks, update deduplication, Telegram identity
binding and outbound delivery. Chronos accepts only authenticated,
service-scoped commands from Gryphon and applies them to the same timer model
used by the web interface. This boundary follows
[Part 09](https://github.com/psewdon1m-exocortex/general/blob/main/PART_09_SERVICE_AGENTS_DEPLOYMENT_AND_LIFECYCLE.md).

## Product boundaries

- The current deployment is single-operator.
- Category identifiers are fixed and cannot be renamed.
- Browser login follows the public-authenticated profile: the sign-in page is
  reachable from every client IP, while the Access Key and bounded application
  session protect all operator data.
- Public ingress and TLS belong to the server-managed Nginx. Chronos does not
  ship an embedded Nginx and does not use coturn.
