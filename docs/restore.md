# Restoring from Backup

How to restore your Plex Media Server data from a RePlexOn backup.

## Prerequisites

- `rsync` installed on the Plex server
- Access to your NAS/backup destination
- The rsync password file (default: `/etc/replexon/rsync.secret`)

## Before You Start

1. **Stop Plex** before restoring to prevent database corruption:

   ```bash
   # Snap install
   sudo snap stop plexmediaserver

   # Apt/deb install
   sudo systemctl stop plexmediaserver
   ```

2. **Back up the current state** (optional safety net):

   ```bash
   sudo cp -a "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server" \
     "/tmp/plex-pre-restore-$(date +%Y%m%d)"
   ```

## Full Restore from Daily Mirror

Restores the most recent backup:

```bash
rsync -avh --password-file=/etc/replexon/rsync.secret \
  backupuser@NAS_IP::plex-backups/plex-current/ \
  "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server/"
```

Replace `backupuser`, `NAS_IP`, and `plex-backups` with your actual rsync user, NAS IP, and module name from `backup-plex.sh`.

## Restore from Weekly Snapshot

List available snapshots:

```bash
rsync --list-only --password-file=/etc/replexon/rsync.secret \
  backupuser@NAS_IP::plex-backups/plex-snapshots/
```

Restore a specific snapshot:

```bash
rsync -avh --password-file=/etc/replexon/rsync.secret \
  backupuser@NAS_IP::plex-backups/plex-snapshots/2026-04-20/ \
  "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server/"
```

## Database-Only Restore

If you only need to restore the Plex database (watch history, metadata, etc.):

```bash
PLEX_DB="/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server/Plug-in Support/Databases"

rsync -avh --password-file=/etc/replexon/rsync.secret \
  backupuser@NAS_IP::plex-backups/plex-current/Plug-in\ Support/Databases/ \
  "$PLEX_DB/"
```

Remove any stale WAL/SHM files if the database was backed up using the safe SQLite `.backup` method (the safe copies are standalone and don't need WAL/SHM):

```bash
rm -f "$PLEX_DB"/*.db-wal "$PLEX_DB"/*.db-shm
```

## After Restore

1. **Fix file ownership** to match your Plex install:

   ```bash
   # Snap install
   sudo chown -R root:root "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server"

   # Apt/deb install
   sudo chown -R plex:plex "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"
   ```

2. **Start Plex**:

   ```bash
   # Snap install
   sudo snap start plexmediaserver

   # Apt/deb install
   sudo systemctl start plexmediaserver
   ```

3. **Verify** by opening Plex Web (`http://your-server:32400/web`) and checking:
   - Libraries appear and are browsable
   - Watch history is intact
   - Server settings are correct

## What Gets Restored

RePlexOn backs up Plex **configuration, database, metadata, and artwork** -- NOT media files. Your media files (movies, TV shows, music) must still be accessible at their original paths or re-mapped in Plex after restore.

Specifically backed up:
- `Plug-in Support/Databases/` -- watch history, metadata, ratings, playlists
- `Plug-in Support/Preferences/` -- server and plugin settings
- `Metadata/` -- posters, artwork, agent data
- `Media/` -- analysis files (BIF thumbnails, etc.)
- `Preferences.xml` -- core server configuration
