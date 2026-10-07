# RePlexOn on bare metal (no Docker)

Docker is the recommended way to run RePlexOn (see the main [README](../README.md)).
This folder is for running it directly on an Ubuntu or Debian host with systemd,
next to a native Plex install.

## Install

```bash
git clone https://github.com/wickedhardflip/replexon.git
cd replexon
sudo bash native/install.sh
```

The installer:

- installs `python3-venv rsync sqlite3 bc curl` (Python 3.10 or newer is required)
- copies the app to `/opt/replexon` and builds a virtualenv there
- writes `/opt/replexon/.env` with paths only (data in `/opt/replexon/data`)
- runs the app as the `plex` user when it exists (so it can read the Plex folder),
  otherwise as `www-data`
- installs and starts `replexon.service` and a logrotate rule

Then open `http://<server>:9847` and the setup wizard walks you through Plex location,
what to back up, destination, schedule and email. The app runs the backups on its
own schedule; there is nothing to add to crontab.

To update, `git pull` and run the installer again. It keeps `.env` and `data/`.

## Backing up to a local folder or mounted share

The service is sandboxed (`ProtectSystem=strict`) and the backup scripts run inside
that sandbox. Allow the backup folder, and make sure the service user can write to it:

```bash
sudo systemctl edit replexon
#   [Service]
#   ReadWritePaths=/mnt/nas/plex-backups
sudo systemctl restart replexon
```

Backing up to a NAS over the rsync daemon needs no extra paths.

## Upgrading from 1.x

1.x was configured by editing the scripts and root's crontab. In 2.0:

1. Run `sudo bash native/install.sh` again.
2. Remove the old lines from root's crontab (`sudo crontab -e`): `backup-plex.sh`,
   `cleanup-plex-snapshots.sh`. The installer warns if they are still there.
   Leaving them makes backups run twice.
3. Open the web UI and finish the setup wizard. Your Plex path, NAS address,
   rsync user/module and retention go in there. The rsync password is entered
   once and stored encrypted.
4. The old `/usr/local/bin/backup-plex.sh` and `cleanup-plex-snapshots.sh` copies can be deleted.

To keep showing old runs, point `BACKUP_LOG_PATH` in `/opt/replexon/.env` at the old
`/var/log/plex-backup.log` and add that file to `ReadWritePaths`.

## Running the script by hand

`scripts/backup-plex.sh` reads its settings from the environment, so it can still
run outside the app (for example from your own scheduler). When it is not started
by RePlexOn it sources `/etc/replexon/backup.env` if present:

```bash
# /etc/replexon/backup.env  (chmod 600)
PLEX_DATA="/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"
BACKUP_MODE=nas                 # or: local
BACKUP_DIR=/mnt/backups         # local mode
NAS_IP=192.168.1.50             # nas mode
RSYNC_USER=backupuser
RSYNC_MODULE=plex-backups
RSYNC_PASSWORD_FILE=/etc/replexon/rsync.secret
BACKUP_LOG_PATH=/var/log/plex-backup.log
SNAPSHOT_KEEP_COUNT=4
BACKUP_ITEMS=databases,preferences,plugins
DB_SAFETY=safe_copy
```

See `rsync.secret.example` for the password file format.

`BACKUP_COMMAND` in `.env` replaces the script for the "Run Now" button and scheduled
backups, for setups that need `sudo` or a wrapper. The command must write the same
log markers (below).

`backup-scripts.sh` is an optional extra from 1.x that copies scripts and configs to
the NAS once a month. The app does not schedule it.

## Database safety

Plex keeps its library in SQLite databases with write-ahead logs. Copying those files
while Plex writes can give a broken backup. The script copies `.db`, `-wal` and `-shm`
to a scratch folder, runs `sqlite3 .backup` on the copy, and checks the result with
`PRAGMA quick_check`. If that fails the run is marked FAILED; the live database is
never copied instead. (Docker users can also pause the Plex container during the
copy; that mode does not apply here.)

## Log format

`app/services/log_parser.py` reads these markers. Do not change them:

```
=== Plex Backup Started: Mon Feb 23 03:00:01 AM EST 2026 ===
=== Plex Backup Completed Successfully: Mon Feb 23 03:13:23 AM EST 2026 ===
=== Plex Backup FAILED with code 1: Mon Feb 23 03:00:01 AM EST 2026 ===
=== Plex Snapshot Cleanup - Sun Feb 23 04:00:01 AM EST 2026 ====
```

## NAS rsync daemon

See [docs/nas.md](../docs/nas.md).
