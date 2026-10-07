# Configuration

Almost everything is set in the web UI: the setup wizard on first start, then the
Settings page. Those values live in RePlexOn's database under `/data`
(`/opt/replexon/data` on bare metal). Environment variables are only for start-up
knobs and are listed here.

## Settings in the web UI

| Section | What it holds |
|---|---|
| Plex location | The Plex data folder. Auto-detected for the usual Docker mount (`/plex`), deb/rpm, snap and Synology installs. Checked on save. |
| What to back up | Essential (databases + Preferences.xml), Standard (+ plug-ins), Full (+ metadata and artwork), or a custom pick. Cache, Logs, Crash Reports, Codecs and Updates are never copied. |
| Database safety | **Safe copy** (default) or **Pause Plex during the copy**. See below. |
| Where backups go | A folder (local disk or mounted share), or a NAS rsync daemon (address, user, module, password). |
| Weekly snapshots | How many Sunday snapshots to keep (1-52). |
| Schedule | Presets or any 5-field cron expression, for the backup and the snapshot cleanup. Times use the `TZ` time zone. |
| Email | SMTP host, port, encryption (STARTTLS, SSL/TLS, none), login, from/to, and when to send. Has a test button. |

Passwords (SMTP and rsync) are encrypted before they are stored and are never sent
back to the browser. Leave a password field blank to keep the saved one.

### Database safety

Plex keeps your library in SQLite databases that it writes to all the time. Copying
those files mid-write can produce a backup that will not open.

- **Safe copy (default).** Plex keeps running. RePlexOn copies the database files
  (including the `-wal` and `-shm` journals) to a scratch folder, runs SQLite's own
  `.backup` on that copy to get one consistent file, and checks it with
  `PRAGMA quick_check`. If any database fails, the run is marked **FAILED** (red on the
  dashboard, "DB FAILED" badge). It never quietly falls back to copying the live files.
- **Pause Plex during the copy (advanced).** Only for Plex in Docker on the same host.
  RePlexOn pauses the Plex container (`docker pause`) for the few seconds the database
  copy takes, then resumes it, also when the copy fails. Needs
  `/var/run/docker.sock` mounted into RePlexOn, which gives it full control of Docker
  on that host, so only use it if you are comfortable with that. If the socket is
  missing or the pause fails, the run logs a warning and makes a safe copy instead.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TZ` | `UTC` | Time zone for schedules and log times. |
| `PUID` / `PGID` | `1000` | Docker only. User and group RePlexOn runs as. Match your Plex container so the Plex folder is readable. Plex installed as a snap or package has root-only files (`Preferences.xml`); use `PUID=0` and `PGID=0` there and RePlexOn stays root inside the container. |
| `SECRET_KEY` | generated | Signs sessions and encrypts stored passwords. When unset it is generated once into `DATA_DIR/.secret_key` (mode 600). If you lose that file you must re-enter the SMTP and rsync passwords. |
| `DATA_DIR` | `/data` | Database, logs, secret key. |
| `ADMIN_USER` / `ADMIN_PASSWORD` | empty | Create the admin on first start instead of in the wizard (only when no user exists yet). |
| `APP_PORT` | `9847` | Port, when started with `replexon.py`. In Docker, change the published port instead. |
| `DEBUG` | `false` | Enables `/docs`. |
| `BACKUP_LOG_PATH` | `/data/logs/plex-backup.log` | Where the backup log is written and read. |
| `BACKUP_SCRIPT_PATH` | `/app/scripts/backup-plex.sh` | The backup script. |
| `BACKUP_COMMAND` | empty | Run this instead of the script for backups (bare metal, e.g. a sudo wrapper). See [native/README.md](../native/README.md). |
| `SCRATCH_DIR` | `/tmp` | Where the database copy is staged. Needs room for the Plex databases. |
| `PLEX_DATA_PATH`, `BACKUP_DIR`, `BACKUP_MODE`, `SNAPSHOT_KEEP_COUNT` | `/plex`, `/backups`, `local`, `4` | Starting values for the wizard only. |
| `SNAPSHOT_DIR` | `plex-snapshots` | Folder name for weekly snapshots. |
| `BACKUP_COOLDOWN` | `300` | Seconds between manual "Run Now" backups. |
| `LOG_POLL_INTERVAL` | `60` | Seconds between log reads. |

## What is in /data

```
/data/
  replexon.db                # settings, users, backup history
  .secret_key                # generated SECRET_KEY (keep it with your backups of /data)
  logs/plex-backup.log       # full backup output
  logs/plex-backup-tracking.log
  logs/last-backup.out       # output of the most recent run
```

## Health check

`GET /health` answers `{"status": "ok"}` without signing in. The Docker image uses it
for `HEALTHCHECK`; use it for uptime monitors too.

## Behind a reverse proxy (single sign-on)

If RePlexOn sits behind a reverse proxy that already signs people in (for example
Caddy with `forward_auth`), it can accept that sign-in instead of showing its own
login page. **It is off by default.** Turn it on only when the proxy is set up as
described here, because the proxy vouches for who the user is.

RePlexOn trusts the `Remote-User` header only when **both** are true:

1. The connection comes from a trusted network (`TRUSTED_PROXY_NETWORKS`, default
   `172.16.0.0/12`, which covers Docker networks), so a device on your LAN cannot fake it.
2. The request carries an `X-Homelab-Proxy` header matching a shared secret
   (`PROXY_AUTH_SECRET`), which the proxy adds.

If either check fails, RePlexOn falls back to its normal login.

```bash
TRUST_PROXY_AUTH=true
PROXY_AUTH_SECRET=***          # long random value, the same one the proxy sends
TRUSTED_PROXY_NETWORKS=172.16.0.0/12
PROXY_AUTH_USER_MAP=alice=admin   # optional: proxy username=RePlexOn username
PROXY_AUTH_LOGOUT_URL=https://sso.example.com/logout   # optional: where Sign out sends proxy users
```

The proxy must remove any client-sent `Remote-User` and `X-Homelab-Proxy` headers,
then set its own. Example Caddy route (the `route` block matters: without it Caddy
runs `forward_auth` before `request_header` and strips the header it just set):

```
handle @replexon {
	route {
		request_header -Remote-User
		request_header -X-Homelab-Proxy
		forward_auth portal:8000 {
			uri /auth/verify
			copy_headers Remote-User
		}
		reverse_proxy replexon:9847 {
			header_up X-Homelab-Proxy {env.PROXY_SECRET}
		}
	}
}
```

Keep uvicorn's default `--forwarded-allow-ips` (127.0.0.1) so RePlexOn sees the
proxy's real address.
