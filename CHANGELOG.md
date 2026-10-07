# Changelog

## [2.0.0] - Unreleased

Docker is now the main way to run RePlexOn. The separate Docker edition is merged in.

### Added
- Multi-arch container image `ghcr.io/wickedhardflip/replexon` (amd64, arm64), `compose.yml` and `compose.nas.yml`.
- First-run setup wizard: admin account, Plex location (auto-detected for Docker, deb/rpm, snap and Synology layouts, and checked), what to back up (Essential / Standard / Full / custom), destination (folder or NAS rsync daemon), schedule, email.
- Settings page with the same forms; everything is configured in the UI.
- Built-in scheduler (presets or any cron expression). No crontab.
- Configurable snapshot retention, applied on the NAS too (no SSH needed).
- Database safety modes: safe copy (default) and pausing the Plex container via the Docker socket (opt-in).
- Direct SMTP email (STARTTLS, SSL/TLS or none) with notify-on choice and test send.
- `/health` endpoint without login; Docker `HEALTHCHECK`.
- Optional single sign-on behind a reverse proxy (`TRUST_PROXY_AUTH`, off by default). Trusts `Remote-User` only from a trusted network AND with a shared proxy secret; see docs/configuration.md.
- New look based on a transit-sign theme, light by default, with the RePlexOn station sign.
- CI: tests on every push and pull request; image build and push on version tags.

### Changed
- A failed database copy now fails the run (red, "DB FAILED"). There is no fallback to copying live database files.
- SMTP and rsync passwords are stored encrypted; `SECRET_KEY` is generated into the data folder when not set.
- Bare-metal install moved to `native/`; the installer no longer installs msmtp or edits crontab.
- Backup and cleanup scripts read their settings from the environment instead of being edited.
- Python 3.10 or newer is required.

### Removed
- msmtp support, crontab reading/editing (`CRON_EDIT_ENABLED`, `CRON_USER`), `config.example.yaml`.

### Upgrading from 1.x (bare metal)
Re-run `sudo bash native/install.sh`, remove the old `backup-plex.sh` and `cleanup-plex-snapshots.sh` lines from root's crontab, then finish the setup wizard. See native/README.md.

## [1.1.0] - 2026-04-23

### Added
- NAS snapshot retention dashboard on Schedules page (via rsync --list-only)
- Restore guide as top-level nav page with context-aware rsync commands
- Log rotation config (weekly, 4 rotations, compressed via copytruncate)
- Restore documentation (`docs/restore.md`)
- Safe SQLite `.backup` before rsync (with automatic fallback)
- DB Safety badge on dashboard (safe vs live rsync indicator)
- Backup calendar heatmap (GitHub-contributions style)
- Duration trend chart
- Next backup countdown timer (parsed from cron schedule)
- Login rate limiting (5 attempts/min per IP)
- Security headers middleware (X-Frame-Options, CSP, Referrer-Policy)
- CSRF protection on logout (POST form)
- Concise daily backup email with transfer stats and success rate
- Failure clustering alerts (streak detection vs one-offs)

### Changed
- Simplified to single-user auth (removed unused email/is_admin fields)
- Removed password change UI from Settings page
- Startup refuses default SECRET_KEY

### Security
- Semgrep static analysis: 0 real findings
- PII scan: all tracked files use placeholder values
- SMTP passwords never stored (delegated to msmtp)

## [1.0.0] - 2026-04-20

Initial release.
