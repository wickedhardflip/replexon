#!/bin/bash
# =============================================================================
# backup-plex.sh - Daily Plex Media Server backup via rsync
#
# Mirrors Plex data to a NAS/Synology using rsync daemon protocol.
# On Sundays, creates an additional dated snapshot for weekly retention.
#
# Log markers are parsed by RePlexOn dashboard (log_parser.py).
# DO NOT change the marker format without updating the regex patterns.
#
# Schedule: daily at 3 AM via cron
#   0 3 * * * /usr/local/bin/backup-plex.sh >> /var/log/plex-backup.log 2>&1
# =============================================================================

# ── Configuration ──────────────────────────────────────────────────────────────
# Plex data directory (where Plex stores its database, metadata, etc.)
# Common locations:
#   Snap install:   /snap/plexmediaserver/common/Library/Application Support/Plex Media Server
#   Apt/deb install: /var/lib/plexmediaserver/Library/Application Support/Plex Media Server
#   Manual install: /opt/plexmediaserver/Library/Application Support/Plex Media Server
PLEX_DATA="/var/lib/plexmediaserver/Library/Application Support/Plex Media Server"

# NAS/Synology rsync daemon settings
NAS_IP="192.168.1.100"
RSYNC_USER="backupuser"
RSYNC_MODULE="plex-backups"
RSYNC_PASSWORD_FILE="/etc/replexon/rsync.secret"

# Backup log paths (must match RePlexOn .env BACKUP_LOG_PATH)
LOG_FILE="/var/log/plex-backup.log"
TRACKING_FILE="/var/log/plex-backup-tracking.log"

# Snapshot settings
SNAPSHOT_DIR="plex-snapshots"

# Optional: email notification on failure (requires mail/mailx)
EMAIL_ON_FAILURE=""  # Set to email address, or leave empty to disable

# ── Do not edit below this line ────────────────────────────────────────────────

TODAY=$(date +%Y-%m-%d)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
RSYNC_DEST="${RSYNC_USER}@${NAS_IP}::${RSYNC_MODULE}"

echo "=== Plex Backup Started: $(date) ==="

# Daily mirror: sync current state to NAS
rsync -avh --delete \
    --password-file="$RSYNC_PASSWORD_FILE" \
    "$PLEX_DATA/" \
    "${RSYNC_DEST}/plex-current/"

EXIT=$?

if [ $EXIT -eq 0 ]; then
    echo "=== Plex Backup Completed Successfully: $(date) ==="
    echo "${TODAY}:success" >> "$TRACKING_FILE"

    # Sunday snapshot: create a dated copy for weekly retention
    if [ "$DAY_OF_WEEK" -eq 7 ]; then
        echo "Sunday detected - creating weekly snapshot"
        rsync -avh \
            --password-file="$RSYNC_PASSWORD_FILE" \
            "${RSYNC_DEST}/plex-current/" \
            "${RSYNC_DEST}/${SNAPSHOT_DIR}/${TODAY}/"
        SNAP_EXIT=$?
        if [ $SNAP_EXIT -eq 0 ]; then
            echo "Weekly snapshot created: ${SNAPSHOT_DIR}/${TODAY}/"
        else
            echo "WARNING: Weekly snapshot failed with code $SNAP_EXIT"
        fi
    fi
else
    echo "=== Plex Backup FAILED with code $EXIT: $(date) ==="
    echo "${TODAY}:failed" >> "$TRACKING_FILE"

    # Send failure notification email
    if [ -n "$EMAIL_ON_FAILURE" ]; then
        echo "Plex backup failed on $(hostname) at $(date) with exit code $EXIT" \
            | mail -s "Plex Backup FAILED on $(hostname)" "$EMAIL_ON_FAILURE"
    fi
fi
