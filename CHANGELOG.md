# Changelog

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
