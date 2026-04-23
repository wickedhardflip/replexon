#!/bin/bash
# =============================================================================
# backup-plex.sh - Daily Plex Media Server backup via rsync
#
# Mirrors Plex data to a NAS/Synology using rsync daemon protocol.
# On Sundays, creates an additional dated snapshot for weekly retention.
#
# SAFE DATABASE BACKUP: Before rsyncing, this script uses SQLite's .backup
# API to create consistent snapshots of Plex's databases. This prevents
# corrupt or incomplete database backups while Plex is running. If sqlite3
# is unavailable or .backup fails, falls back to live rsync (same as before).
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
#   Snap install:    /var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server
#   Apt/deb install: /var/lib/plexmediaserver/Library/Application Support/Plex Media Server
#   Manual install:  /opt/plexmediaserver/Library/Application Support/Plex Media Server
PLEX_DATA="/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server"

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

# Staging directory for safe database copies
STAGING_DIR="/tmp/plex-db-safe"
DB_DIR="$PLEX_DATA/Plug-in Support/Databases"
SAFE_DB_SUCCESS=false

cleanup_staging() {
    if [ -d "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR"
    fi
}
trap cleanup_staging EXIT

echo "=== Plex Backup Started: $(date) ==="

# ── Safe Database Snapshot ────────────────────────────────────────────────────
# Use sqlite3 .backup API to create consistent copies of Plex databases.
# This is safe while Plex is running — SQLite handles locking internally.
# If this fails for any reason, we fall back to rsyncing live database files.

if command -v sqlite3 >/dev/null 2>&1; then
    if [ -d "$DB_DIR" ]; then
        mkdir -p "$STAGING_DIR"
        DB_COUNT=0
        DB_FAILED=0
        DB_START=$(date +%s)

        echo "--- Safe database snapshot: starting ---"

        for db_file in "$DB_DIR"/*.db; do
            [ -f "$db_file" ] || continue
            db_name=$(basename "$db_file")
            db_size=$(du -m "$db_file" | cut -f1)
            echo "Backing up: $db_name ($db_size MB)"

            if sqlite3 "$db_file" ".backup '$STAGING_DIR/$db_name'"; then
                DB_COUNT=$((DB_COUNT + 1))
            else
                echo "WARNING: sqlite3 .backup failed for $db_name (exit $?)"
                DB_FAILED=$((DB_FAILED + 1))
            fi
        done

        DB_ELAPSED=$(( $(date +%s) - DB_START ))

        if [ "$DB_FAILED" -eq 0 ] && [ "$DB_COUNT" -gt 0 ]; then
            SAFE_DB_SUCCESS=true
            echo "--- Safe database snapshot: complete ($DB_COUNT databases, ${DB_ELAPSED}s) ---"
        else
            echo "WARNING: Safe snapshot had failures ($DB_FAILED failed, $DB_COUNT succeeded). Falling back to live rsync."
            cleanup_staging
        fi
    else
        echo "WARNING: Database directory not found: $DB_DIR. Skipping safe snapshot."
    fi
else
    echo "WARNING: sqlite3 not installed. Skipping safe database snapshot (databases will be rsynced live)."
    echo "Install with: sudo apt install sqlite3"
fi

# ── Daily Mirror ──────────────────────────────────────────────────────────────
# If safe snapshots succeeded, exclude live DB/WAL/SHM files from main rsync.
# They'll be sent separately from the staging directory.

if [ "$SAFE_DB_SUCCESS" = true ]; then
    rsync -avh --delete \
        --password-file="$RSYNC_PASSWORD_FILE" \
        --exclude='Plug-in Support/Databases/*.db' \
        --exclude='Plug-in Support/Databases/*.db-shm' \
        --exclude='Plug-in Support/Databases/*.db-wal' \
        "$PLEX_DATA/" \
        "${RSYNC_DEST}/plex-current/"
else
    rsync -avh --delete \
        --password-file="$RSYNC_PASSWORD_FILE" \
        "$PLEX_DATA/" \
        "${RSYNC_DEST}/plex-current/"
fi

EXIT=$?

# ── Push Safe Database Copies ─────────────────────────────────────────────────
# Send the consistent snapshots to the correct location on the NAS.

if [ $EXIT -eq 0 ] && [ "$SAFE_DB_SUCCESS" = true ]; then
    echo "Syncing safe database copies to NAS..."
    rsync -avh \
        --password-file="$RSYNC_PASSWORD_FILE" \
        "$STAGING_DIR/" \
        "${RSYNC_DEST}/plex-current/Plug-in Support/Databases/"

    DB_PUSH_EXIT=$?
    if [ $DB_PUSH_EXIT -ne 0 ]; then
        echo "WARNING: Failed to sync safe database copies (exit $DB_PUSH_EXIT)"
    fi
fi

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
