# Chronos module description

Chronos is the centralized time tracker service inside Exocortex.

- Single operator model (one user profile).
- Four fixed categories:
  - Recovery
  - Accumulation
  - Execution
  - Maintenance
- Web interface + Telegram bot in one product.
- Full backup and restore path.
- Kernel Register driven config and Updater integration.

## Current behavior

- Timer session tracking with start/stop and manual corrections.
- Timeline and analytics views in UI.
- Activity history and audit trail.
- Per-operator settings including timezone and preferences.
- Release control through Updater contract endpoints.

## Boundaries

- Categories are fixed and cannot be renamed in current release.
- Multi-user mode is not enabled in current version.
- Telegram and web work with one shared data model.
