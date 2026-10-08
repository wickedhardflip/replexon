<p align="center"><img src="app/static/logo/replexon-sign.svg" alt="RePlexOn - Backup Line" width="420"></p>

# RePlexOn

*"Previously on your Plex server..."*

[![Tests](https://github.com/wickedhardflip/replexon/actions/workflows/test.yml/badge.svg)](https://github.com/wickedhardflip/replexon/actions/workflows/test.yml)
[![Image](https://img.shields.io/badge/ghcr.io-wickedhardflip%2Freplexon-2b6cb0?logo=docker&logoColor=white)](https://github.com/wickedhardflip/replexon/pkgs/container/replexon)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20this%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/punchybuttons)

Self-hosted backups and a monitoring dashboard for Plex Media Server. RePlexOn copies
your Plex **database, watch history, settings, plug-ins and (optionally) metadata** to
a folder or a NAS on a schedule, keeps weekly snapshots, emails you when something
goes wrong, and shows it all on one page.

> **What gets backed up:** the Plex data folder (database, accounts, watch history,
> artwork, preferences). **Not your media files.** It is what you need to rebuild a
> Plex server without re-scanning and reconfiguring everything.

Free and open source under the MIT license, provided as-is. See [Disclaimer](#disclaimer).

---

## Quick start (Docker)

1. Save this as `compose.yml` and change the three host paths:

```yaml
services:
  replexon:
    image: ghcr.io/wickedhardflip/replexon:latest
    container_name: replexon
    environment:
      - TZ=America/New_York      # starting time zone (change it later in Settings)
      - PUID=1000                # same user/group IDs as your Plex
      - PGID=1000
    volumes:
      - replexon-data:/data                     # RePlexOn's settings, history and logs
      - /path/to/plex/config:/plex:ro           # your Plex config folder, read-only
      - /path/to/backups:/backups               # where backups go
    ports:
      - "9847:9847"
    restart: unless-stopped

volumes:
  replexon-data:
```

2. `docker compose up -d`
3. Open `http://your-server:9847`. The setup wizard asks for:
   - an admin account
   - where Plex is (auto-detected and checked)
   - what to back up: **Essential**, **Standard** or **Full**
   - where backups go: a folder, or a NAS over rsync
   - when: daily, twice a day, weekly, or your own cron
   - email (optional), with a test button

That is it. No crontab, no editing scripts.

Prefer `docker run`?

```bash
docker run -d --name replexon --restart unless-stopped -p 9847:9847 \
  -e TZ=America/New_York -e PUID=1000 -e PGID=1000 \
  -v replexon-data:/data \
  -v /path/to/plex/config:/plex:ro \
  -v /path/to/backups:/backups \
  ghcr.io/wickedhardflip/replexon:latest
```

Images are built for `linux/amd64` and `linux/arm64`.

## Plex in Docker

If Plex is also a container:

- **Config folder**: mount the same host folder your Plex container uses for `/config`
  at `/plex`, **read-only** (`:ro`). RePlexOn finds the Plex Media Server folder inside.
- **PUID / PGID**: use the same IDs as Plex (linuxserver/plex `PUID`/`PGID`,
  plexinc/pms-docker `PLEX_UID`/`PLEX_GID`) so RePlexOn can read the files.
- **Network**: RePlexOn reads files, it does not talk to Plex, so host networking or a
  shared user-defined network both work. Put them on the same network if a reverse
  proxy fronts both.
- **Health**: the image has a `HEALTHCHECK` on `/health` (no login needed), so
  `docker ps` shows `healthy`.

A full two-service compose file and the optional "pause Plex during the database copy"
mode are in [docs/plex-in-docker.md](docs/plex-in-docker.md).

## Database safety

Plex writes to its SQLite databases constantly, and a file copied mid-write may not
open. By default RePlexOn makes a **safe copy**: it copies the database and its
journal files to a scratch folder, runs SQLite's own `.backup` on that copy and checks
the result. If that fails, the run shows **FAILED** in red with a "DB FAILED" badge.
It never quietly copies the live files instead.

Plex in Docker on the same host can optionally be **paused** for the few seconds the
copy takes (needs the Docker socket). Both modes are explained on the Settings page
and in [docs/configuration.md](docs/configuration.md#database-safety).

## Backing up to a NAS

Pick **A NAS over rsync** in the wizard to send straight to a Synology, TrueNAS or any
rsync daemon, or mount a share at `/backups` (SMB/NFS examples in
[`compose.nas.yml`](compose.nas.yml)). Setup for both: [docs/nas.md](docs/nas.md).

Backups land as:

```
plex-current/            # latest backup, mirrored each run
plex-snapshots/
  2026-08-10/            # dated copy after each successful Sunday backup
  2026-08-17/            # the newest N are kept (configurable)
```

## Without Docker

RePlexOn also runs directly on Ubuntu/Debian with systemd:

```bash
git clone https://github.com/wickedhardflip/replexon.git && cd replexon
sudo bash native/install.sh
```

Same web UI and wizard. See [native/README.md](native/README.md), including upgrading
from 1.x (remove the old crontab lines).

---

## Screenshots

| Dashboard | Backup Logs |
|:-:|:-:|
| ![Dashboard](docs/screenshots/dashboard.png?v=3) | ![Logs](docs/screenshots/logs.png?v=3) |

| Schedules | Settings |
|:-:|:-:|
| ![Schedules](docs/screenshots/schedules.png?v=3) | ![Settings](docs/screenshots/settings.png?v=3) |

## What you get

- **At-a-glance status**: last result, DB safety badge, size, success rate, NAS health
- **Charts**: size and duration over time, a calendar heatmap of daily results
- **Failure clustering**: tells a streak of failures from a one-off
- **Live progress** while a backup runs, and a countdown to the next one
- **History**: searchable, filterable log with per-run details and raw output
- **Schedules**: presets or cron, run now, weekly snapshot list with retention
- **Email**: on failure, on every run, or never; delivery log; test button
- **Restore page**: copy-paste restore commands for your setup ([docs/restore.md](docs/restore.md))
- **Light and dark** themes, mobile layout

## Configuration

Everything is in the web UI. Environment variables are for start-up only (time zone,
user IDs, optional admin, reverse-proxy single sign-on). Reference:
[docs/configuration.md](docs/configuration.md).

Your settings, history and the generated secret key live in the `replexon-data`
volume. Keep it: the SMTP and rsync passwords are encrypted with that key.

## Updating

```bash
docker compose pull && docker compose up -d
```

## Security

- Argon2id password hashing, server-side sessions, CSRF tokens on every form,
  login rate limiting, strict security headers
- SMTP and rsync passwords encrypted at rest and never sent back to the browser
- Runs as an unprivileged user (`PUID`/`PGID`); the Plex folder is mounted read-only
- The Docker socket is optional and only used to pause and resume Plex
- HTMX and Chart.js are vendored: no CDNs, and the app never phones home
- Optional single sign-on behind a reverse proxy, off by default
  ([details](docs/configuration.md#behind-a-reverse-proxy-single-sign-on))

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload --port 9847
```

The backup script tests need Linux with `rsync`, `sqlite3` and `bc` and are skipped
elsewhere; CI runs them.

## Disclaimer

**This software is provided "as-is" without warranty of any kind.** Use at your own risk.

- **No support**: issues and pull requests are welcome, responses are not guaranteed.
- **Your responsibility**: check your backups yourself now and then. Do not rely on the
  dashboard as the only proof they work.
- **Data loss**: the authors are not responsible for data loss from use or misuse of
  this software.

See the [MIT License](LICENSE).

## Contributing and support

Bug reports, ideas and pull requests are welcome. If RePlexOn is useful to you:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/punchybuttons)

## License

[MIT](LICENSE)
