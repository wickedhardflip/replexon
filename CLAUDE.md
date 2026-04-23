# RePlexOn - Project Context

## Overview
RePlexOn is a complete Plex backup system + web monitoring dashboard. It backs up Plex **config, database, metadata, watch history, and artwork** (NOT media files) to a NAS/Synology via rsync, then provides a web UI to monitor backup status, history, charts, and email alerts.

**Repo**: https://github.com/wickedhardflip/replexon (PUBLIC, MIT license)
**Live**: http://192.168.4.5:9847
**Server path**: /opt/replexon
**Local path**: C:\Users\briwa\OneDrive\Claude\plex\replexon

## Tech Stack
- **Backend**: Python 3.9+, FastAPI, SQLAlchemy 2.0 (SQLite WAL), Pydantic Settings
- **Frontend**: Jinja2, HTMX 2.0, Chart.js 4.x -- vendored, no npm/CDN
- **Auth**: Argon2id hashing, server-side sessions, HMAC CSRF tokens
- **Backup**: rsync daemon protocol to Synology NAS, bash scripts, cron

## Architecture

### Two Parts
1. **Backup scripts** (`scripts/`) -- bash scripts run via cron:
   - `backup-plex.sh`: Daily 3AM rsync mirror + Sunday dated snapshots
   - `cleanup-plex-snapshots.sh`: Sunday 4AM, keeps 4 weekly snapshots
   - `backup-scripts.sh`: 1st of month, config self-backup
2. **Web dashboard** (`app/`) -- FastAPI app that parses backup logs

### Log Parsing Strategy
- **Tracking file** (`plex-backup-tracking.log`): One line per day `YYYY-MM-DD:success|failed` -- primary data source
- **Main log** (`plex-backup.log`): Full rsync output (15GB+), extracted via `grep -F` into small cache file
- Background poller reads every 60 seconds
- Stats extracted: transfer size, total size, duration, start/end times

### Critical Regex Patterns (log_parser.py)
```python
BACKUP_START_RE   = r"=== Plex Backup Started: (.+?) ==="
BACKUP_SUCCESS_RE = r"=== Plex Backup Completed Successfully: (.+?) ==="
BACKUP_FAILED_RE  = r"=== Plex Backup FAILED with code (\d+): (.+?) ==="
CLEANUP_START_RE  = r"=== Plex Snapshot Cleanup - (.+?) ===="  # 4 trailing equals!
SNAPSHOT_RE       = r"Sunday detected - creating weekly snapshot"
```
**DO NOT** change log marker format in scripts without updating these patterns.

### Backup Types
- `daily_mirror`: Runs daily at 3AM
- `snapshot`: Sundays at 3:30AM (if daily_mirror succeeds)
- `cleanup`: Sundays at 4AM
- `script_backup`: Monthly config backup
- `manual`: Triggered via UI

### Database Models
- `User` / `Session`: Argon2id auth, 30-day session expiry
- `BackupRun`: All backup records (type, status, started_at, size, duration, db_safe, etc.)
- `AppSetting`: Key-value store for UI-configurable settings (SMTP, backup paths, NAS health, etc.)
- `EmailLog`: Tracks email delivery attempts (recipient, subject, method, success, error)

### Database Safety
Backup script uses SQLite `.backup` API to create consistent DB snapshots before rsync. `db_safe` column on `BackupRun` tracks whether safe snapshot was used. Fallback to live rsync if sqlite3 unavailable.

## Server Setup (Production)
- **OS**: Ubuntu on 192.168.4.5, user `bwagner`
- **SSH key**: `.ssh/plex-server`
- **Service user**: `bwagner` (owns /opt/replexon/data)
- **Plex install**: Snap (`/var/snap/plexmediaserver/common/...`)
- **NAS**: Synology at 192.168.4.4, rsync user `backup`, module `LinuxBackups`
- **systemd**: `replexon.service` with ProtectSystem=strict, MemoryMax=256M

## Deployment
1. SCP changed files to server (no rsync on Windows)
2. No restart needed for template/CSS changes (Jinja2 reloads)
3. Restart needed for Python changes: `sudo systemctl restart replexon.service`
4. Verify: `python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:9847/login').status)"`
5. DB settings (backup_destination, plex_data_path, etc.) are editable via Settings UI -- no restart needed

## Key Files
```
app/config.py                  # Pydantic Settings -- all env vars defined here
app/main.py                    # FastAPI app factory, background tasks (log poll, NAS health)
app/routers/dashboard.py       # Dashboard + /api/backup-status endpoint
app/routers/logs.py            # Log viewer with type/status/date/search filters
app/routers/settings_router.py # Settings CRUD -- backup paths, SMTP, email, password
app/services/log_parser.py     # Log parsing + regex patterns
app/services/metrics.py        # Dashboard stats, calendar data, failure clustering
app/services/nas_health.py     # NAS ping health check (background, every 5 min)
app/services/email_service.py  # Email sending + delivery logging
app/services/cron_service.py   # Cron parsing + next backup time calculation
app/services/backup_runner.py  # Manual backup trigger + process tracking
app/models/backup.py           # BackupRun model (includes db_safe column)
app/models/setting.py          # AppSetting key-value model
app/models/email_log.py        # EmailLog model for delivery tracking
app/static/css/style.css       # All CSS with dark mode support (~1000 lines)
app/static/js/dashboard.js     # Chart.js charts + countdown timer
app/static/js/app.js           # Global JS: dark mode toggle, hamburger menu, CSRF
app/templates/pages/           # Jinja2 templates
scripts/                       # Backup script templates (sanitized, no creds)
install.sh                     # Automated installer (default + interactive)
systemd/replexon.service       # systemd unit file
```

## Settings Pattern
UI-configurable settings use `AppSetting` table (key-value) with fallback to `config.py` defaults:
```python
# Read: DB first, config fallback
row = db.query(AppSetting).filter(AppSetting.key == key).first()
value = row.value if row else settings.some_default

# Write: upsert into AppSetting
_set_setting(db, "key", "value")
```

## Dashboard Features
- Stat cards: last backup status, total size, success rate, backup count
- DB Safety Badge: shows safe SQLite `.backup` vs live rsync
- Size + Duration bar charts (Chart.js), calendar heatmap (pure CSS)
- Next backup countdown (cron-parsed), time period filters (7d/30d/90d/All)
- NAS health badge (background ping every 5 min)
- Live backup progress bar (HTMX polls /api/backup-status every 10s)
- Failure clustering alerts (consecutive streaks vs isolated one-offs)
- Email delivery log on Settings page
- Dark mode (default, toggle in nav, localStorage persistence)
- Mobile hamburger menu (<768px)
- Logs page: type/status/date-range/search filters with HTMX live filtering

## Static File Cache Busting
Bump `?v=N` query param on CSS/JS includes in templates when changing static files. Current: `?v=4`. Files: `base.html`, `login.html`, `dashboard.html`.

## Background Tasks (main.py)
- `_poll_logs()`: every 60s, parses incremental log entries + checks running backups
- `_poll_nas_health()`: every 300s, pings NAS IP and stores result in AppSetting

## Security
- Semgrep scanned: 0 real findings (6 false positives from Django CSRF rule)
- PII scan: clean, all tracked files use placeholder values
- `.gitignore` covers: `.env`, `data/`, `*.log`, `scripts/rsync.secret`, `.mcp.json`
- Credentials: rsync password in `/etc/replexon/rsync.secret` (chmod 600), never in scripts

## GitHub
- **Visibility**: Public
- **Release**: v1.0.0
- **Topics**: plex, plex-media-server, backup, synology, nas, rsync, self-hosted, dashboard, fastapi, monitoring, htmx, python, homelab, backup-tool
- **Funding**: Ko-fi at https://ko-fi.com/punchybuttons (`.github/FUNDING.yml`)
- **Screenshots**: `docs/screenshots/` (dashboard, settings, logs, schedules, login) -- all use safe placeholder values

## Documentation
- **Confluence**: https://hardflip.atlassian.net/wiki/spaces/MFS/pages/61276162 (full system overview)

## Social / Promotion
- **Ko-fi**: https://ko-fi.com/punchybuttons (linked in README + Settings About section)
- **X/Twitter**: @punchybuttons (linked in Settings About section)
- **GitHub Pages**: N/A (server-side app, not static)
- **Target subs**: r/PleX, r/selfhosted, r/homelab
- **Messaging**: "Free Plex backup system + monitoring dashboard" -- emphasize it backs up config/metadata/database NOT media files, built for specific setup but configurable, MIT licensed
