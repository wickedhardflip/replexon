```
  ____       ____  _            ___
 |  _ \ ___ |  _ \| | _____  __/ _ \ _ __
 | |_) / _ \| |_) | |/ _ \ \/ / | | | '_ \
 |  _ <  __/|  __/| |  __/>  <| |_| | | | |
 |_| \_\___||_|   |_|\___/_/\_\\___/|_| |_|
 ==========================================
      "Previously on your Plex server..."
```

# RePlexOn

A web dashboard for monitoring and managing your Plex server backup system. Track daily backups, view history, manage schedules, and configure notifications -- all from a clean, modern interface.

## Features

- **Dashboard** -- At-a-glance backup status with size charts, success rates, and recent activity
- **Backup History** -- Filterable log viewer with expandable detail rows, search, and pagination
- **Schedule Management** -- View cron-based backup schedules with human-readable descriptions
- **Manual Trigger** -- Run backups on demand with rate limiting
- **Email Notifications** -- SMTP configuration with test email support (auto-detects msmtp)
- **Settings** -- SMTP config, email recipient, password management, server path display
- **Secure** -- Argon2id password hashing, CSRF protection, server-side sessions

## Tech Stack

- **Backend**: Python 3.9+, FastAPI, SQLAlchemy 2.0 (SQLite WAL mode), Pydantic Settings
- **Frontend**: Jinja2, HTMX 2.0, Chart.js 4.x -- no build tools, no npm
- **Auth**: Argon2id + server-side sessions + HMAC-signed CSRF tokens

## Quick Start

```bash
# Clone
git clone https://github.com/wickedhardflip/replexon.git
cd replexon

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env -- set SECRET_KEY and backup paths

# Initialize
python replexon.py init-db
python replexon.py create-user --username admin --admin

# Run
uvicorn app.main:app --host 0.0.0.0 --port 9847
```

Then visit `http://your-server:9847`

## Configuration

### Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | (required) | Random string for session signing |
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `9847` | Port number |
| `BACKUP_LOG_PATH` | `/var/log/plex-backup.log` | Path to rsync backup log |
| `BACKUP_SCRIPT_PATH` | `/usr/local/bin/backup-plex.sh` | Backup script location |
| `CRON_EDIT_ENABLED` | `false` | Allow schedule editing via UI |
| `CRON_USER` | `root` | User whose crontab to read |
| `LOG_POLL_INTERVAL` | `60` | Seconds between log file checks |
| `BACKUP_COOLDOWN` | `300` | Seconds between manual backup triggers |

### Backup Log Format

RePlexOn reads two files:

1. **Tracking file** (`plex-backup-tracking.log`) -- lightweight daily results:
   ```
   2026-02-20:success
   2026-02-21:success
   2026-02-22:failed
   ```

2. **Main log** (`plex-backup.log`) -- full rsync output with markers:
   ```
   === Plex Backup Started: Mon Feb 23 03:00:01 AM EST 2026 ===
   ...rsync output...
   sent 24,265,611 bytes  received 114,210,946 bytes
   total size is 8,081,447,228  speedup is 58.36
   === Plex Backup Completed Successfully: Mon Feb 23 03:13:23 AM EST 2026 ===
   ```

The tracking file is the primary data source. The main log is used to enrich records with transfer size and duration data.

## CLI Commands

RePlexOn includes a TV-themed CLI:

```bash
# Admin commands
python replexon.py init-db              # Initialize database
python replexon.py create-user          # Create user account
python replexon.py import-logs          # Import backup history from logs
python replexon.py reset-password       # Reset a user's password

# TV-themed commands
python replexon.py --broadcast          # Trigger manual backup
python replexon.py --rerun              # Show most recent backup info
python replexon.py --static             # Health check on backup files
```

## Production Deployment

### systemd Service

```bash
# Copy and edit the service file
sudo cp systemd/replexon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable replexon
sudo systemctl start replexon
```

The included service file runs as a non-root user with security hardening (ProtectSystem, PrivateTmp, memory limits). Edit `User=` and `Group=` to match your server setup.

### Crontab Access

If your backup cron jobs run as root, the service user needs sudo access to read the crontab:

```bash
# /etc/sudoers.d/replexon
plex ALL=(root) NOPASSWD: /usr/bin/crontab -l -u root
```

### Import Historical Data

After first deploy, import existing backup history:

```bash
cd /opt/replexon
source venv/bin/activate
python replexon.py import-logs
```

This extracts stats from the main log (may take a few minutes on large files) and imports records from the tracking file.

## Project Structure

```
replexon/
  app/
    main.py              # FastAPI app + background log poller
    config.py            # Pydantic Settings (.env loading)
    database.py          # SQLAlchemy engine (SQLite WAL)
    models/              # User, Session, BackupRun, AppSetting
    routers/             # Auth, Dashboard, Logs, Schedules, Settings
    services/            # Log parser, metrics, cron, backup runner, email
    templates/           # Jinja2 (base + pages + components)
    static/              # CSS, JS (HTMX + Chart.js vendored)
  systemd/               # systemd unit file
  replexon.py            # CLI entry point
  requirements.txt       # ~10 Python dependencies
```

## License

MIT
