# Chronos documentation and engineering rules

## Authority

The workspace documentation rooted at
[Part 00](https://github.com/psewdon1m-exocortex/general/blob/main/PART_00_SYSTEM_UNIFICATION_SPECIFICATION.md) is the source
of truth. Chronos-local documents describe concrete paths, ports, commands and
implemented behavior only. If a local statement conflicts with an applicable
central Part, the central rule wins and the local document must be corrected.
A material implementation difference must follow the divergence protocol in
Part 00; it must not be hidden by changing the wording of a local document.

Applicable central guides include:

- [Part 01 — UI/UX](https://github.com/psewdon1m-exocortex/general/blob/main/PART_01_INTERFACE_AND_INTERACTION_UNIFICATION.md);
- [Part 02 — observability](https://github.com/psewdon1m-exocortex/general/blob/main/PART_02_OBSERVABILITY_AUDIT_AND_LOG_EXPORT.md);
- [Part 03 — backup and recovery](https://github.com/psewdon1m-exocortex/general/blob/main/PART_03_BACKUP_AND_RECOVERY.md);
- [Part 04 — bootstrap and deployment](https://github.com/psewdon1m-exocortex/general/blob/main/PART_04_BOOTSTRAP_AND_DEPLOYMENT.md);
- [Part 05 — CI, releases and updates](https://github.com/psewdon1m-exocortex/general/blob/main/PART_05_CI_RELEASES_AND_LOCAL_UPDATES.md);
- [Part 06 — pre-push acceptance](https://github.com/psewdon1m-exocortex/general/blob/main/PART_06_UNIFIED_ACCEPTANCE_CHECKLIST.md);
- [Part 07 — security and exposure](https://github.com/psewdon1m-exocortex/general/blob/main/PART_07_SECURITY_AND_EXPOSURE_CONTROL.md);
- [Part 09 — shared-agent lifecycle](https://github.com/psewdon1m-exocortex/general/blob/main/PART_09_SERVICE_AGENTS_DEPLOYMENT_AND_LIFECYCLE.md);
- [Part 10 — shared-agent UI](https://github.com/psewdon1m-exocortex/general/blob/main/PART_10_SERVICE_AGENTS_UI_AND_OPERATOR_WORKFLOWS.md).

Part 08 applies only if Chronos intentionally gains public, indexable content.
The authenticated operator UI is private/concealed content, must not appear in
sitemaps or feeds, and must carry the non-indexing policy from Parts 07 and 08.

## Required documentation discipline

- Update the project [README](../README.md) and the affected local article in
  the same change as a behavior, API, environment, deployment, backup, restore,
  UI or operator-flow change.
- Keep repository URL, default branch, tag namespace, commands, paths and
  version requirements current. Clearly label retained history as
  non-normative.
- Never place Access Keys, session secrets, bot tokens, service tokens or
  private release keys in documentation, examples, links or logs.
- Use Markdown links whose targets exist. The documentation check must reject
  missing local targets and broken same-document anchors.

## Mandatory pre-push evidence

Every push must record the Part 06 gate result. Backup/restore, updater,
embedded Documentation content and affected technical documentation are
checked when the change can affect them. Security is always checked. SEO/GEO
is checked for public/indexable surfaces; concealment, crawler policy and
automated-probe resistance are checked for authenticated or intentionally
hidden surfaces. Each row is `PASS` or a reasoned `N/A`; an unexplained skip is
a failure.

## Version and release namespace

- Chronos versions use SemVer and the first releasable version is `0.0.1`.
- A plain tag such as `v0.0.1` starts verification-only CI and must not publish
  or mutate a release.
- Only `chronos-vMAJOR.MINOR.PATCH` starts the Chronos release pipeline.
- Release instructions must remain consistent with
  [Part 05](https://github.com/psewdon1m-exocortex/general/blob/main/PART_05_CI_RELEASES_AND_LOCAL_UPDATES.md).
