# Chronos repository and release workflow

## Repository

- URL: `https://github.com/psewdon1m-exocortex/chronos.git`
- Default and production branch: `main`
- Feature branches are short-lived and merge into `main` through the repository
  review policy. The retired `dev`/`stage`/`prod` branch model is not used.

The workspace-wide rules in
[Part 00](https://github.com/psewdon1m-exocortex/general/blob/main/PART_00_SYSTEM_UNIFICATION_SPECIFICATION.md) and
[Part 05](https://github.com/psewdon1m-exocortex/general/blob/main/PART_05_CI_RELEASES_AND_LOCAL_UPDATES.md) are normative.

## Commits and pushes

Keep each commit reviewable and describe the observable change. Before pushing,
run the repository checks and complete the
[Part 06 pre-push gate](https://github.com/psewdon1m-exocortex/general/blob/main/PART_06_UNIFIED_ACCEPTANCE_CHECKLIST.md).
The gate includes an always-required security review plus conditional backup,
update, Documentation, technical-documentation, SEO/GEO and concealment checks.

A push to `main` runs ordinary verification. Documentation changes do not
authorize bypassing tests, and code changes do not authorize leaving operator
documentation stale.

## Versions and tags

Chronos uses SemVer `MAJOR.MINOR.PATCH`; an independently versioned service
starts at `0.0.1`.

| Ref | Meaning |
| --- | --- |
| `main` push | ordinary verification CI |
| `v0.0.1` | explicit verification-only CI; no release publication |
| `chronos-v0.0.1` | immutable Chronos release pipeline |

The numeric portion of a qualified release tag must match the service version
and release manifest. Do not reinterpret a plain `v*` tag as a production
release and do not publish from a mutable branch or a `latest` bootstrap URL.

## Release procedure

1. Update the service version, release manifest, changelog/release notes and
   affected operator or technical documentation.
2. Complete repository tests, security checks, artifact checks and the Part 06
   pre-push gate.
3. Push the reviewed commit to `main` and confirm verification CI succeeds.
4. Create and push an annotated `chronos-vMAJOR.MINOR.PATCH` tag.
5. Confirm that the protected release job signs the manifest using a private
   key held only in GitHub Secrets, embeds only the derived public key into the
   exact-version `bootstrap.sh`, and publishes immutable checksummed artifacts.
6. Verify installation, status, loopback health and rollback evidence before
   recommending the release for production.

The bootstrap, environment, server-managed Nginx and operator sequence are
defined by
[Part 04](https://github.com/psewdon1m-exocortex/general/blob/main/PART_04_BOOTSTRAP_AND_DEPLOYMENT.md). Chronos owns its
separate bootstrap and `.env`; trust is not prepared with `scp`, a manual
fingerprint or a key downloaded beside the manifest.
