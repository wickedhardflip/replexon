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
#   0 3 * * * /usr/local/bin/backup-plex.sh >/dev/null 2>&1
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

# Optional: email notification (requires mail/mailx)
EMAIL_TO=""  # Set to email address, or leave empty to disable
DASHBOARD_URL="http://your-server:9847"

# ── Do not edit below this line ────────────────────────────────────────────────

TODAY=$(date +%Y-%m-%d)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
RSYNC_DEST="${RSYNC_USER}@${NAS_IP}::${RSYNC_MODULE}"

# Staging directory for safe database copies
STAGING_DIR="/tmp/plex-db-safe"
DB_DIR="$PLEX_DATA/Plug-in Support/Databases"
SAFE_DB_SUCCESS=false

# ── Helper Functions ──────────────────────────────────────────────────────────

format_bytes() {
  local bytes=$1
  if [ "$bytes" -ge 1073741824 ] 2>/dev/null; then
    echo "$(echo "scale=1; $bytes / 1073741824" | bc) GB"
  elif [ "$bytes" -ge 1048576 ] 2>/dev/null; then
    echo "$(echo "scale=1; $bytes / 1048576" | bc) MB"
  elif [ "$bytes" -ge 1024 ] 2>/dev/null; then
    echo "$(echo "scale=1; $bytes / 1024" | bc) KB"
  else
    echo "${bytes} B"
  fi
}

format_duration() {
  local secs=$1
  if [ "$secs" -ge 3600 ]; then
    printf "%dh %dm %ds" $((secs/3600)) $((secs%3600/60)) $((secs%60))
  elif [ "$secs" -ge 60 ]; then
    printf "%dm %ds" $((secs/60)) $((secs%60))
  else
    printf "%ds" "$secs"
  fi
}

parse_rsync_stats() {
  local stats_file="$1"
  XFER_FILES=$(grep "Number of regular files transferred:" "$stats_file" 2>/dev/null | grep -oP '[\d,]+$' | tr -d ',')
  TOTAL_FILES=$(grep "Number of files:" "$stats_file" 2>/dev/null | head -1 | grep -oP '[\d,]+' | head -1 | tr -d ',')
  TOTAL_SIZE=$(grep "Total file size:" "$stats_file" 2>/dev/null | grep -oP '[\d,]+' | head -1 | tr -d ',')
  XFER_SIZE=$(grep "Total transferred file size:" "$stats_file" 2>/dev/null | grep -oP '[\d,]+' | head -1 | tr -d ',')
}

record_backup_result() {
  local result=$1
  local timestamp=$(date +%Y-%m-%d)
  echo "$timestamp:$result" >> "$TRACKING_FILE"

  if [ -f "$TRACKING_FILE" ]; then
    tail -n 30 "$TRACKING_FILE" > "$TRACKING_FILE.tmp"
    mv "$TRACKING_FILE.tmp" "$TRACKING_FILE"
  fi
}

cleanup_staging() {
    if [ -d "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR"
    fi
}
trap cleanup_staging EXIT

# Record start time
BACKUP_START=$(date +%s)
BACKUP_START_TIME=$(date '+%-I:%M %p')

echo "=== Plex Backup Started: $(date) ==="

# ── Safe Database Snapshot ────────────────────────────────────────────────────
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
RSYNC_OUTPUT_FILE="/tmp/plex-backup-rsync-output.$$"

if [ "$SAFE_DB_SUCCESS" = true ]; then
    rsync -avh --delete --stats \
        --password-file="$RSYNC_PASSWORD_FILE" \
        --exclude='Plug-in Support/Databases/*.db' \
        --exclude='Plug-in Support/Databases/*.db-shm' \
        --exclude='Plug-in Support/Databases/*.db-wal' \
        "$PLEX_DATA/" \
        "${RSYNC_DEST}/plex-current/" \
        2>&1 | tee "$RSYNC_OUTPUT_FILE"
else
    rsync -avh --delete --stats \
        --password-file="$RSYNC_PASSWORD_FILE" \
        "$PLEX_DATA/" \
        "${RSYNC_DEST}/plex-current/" \
        2>&1 | tee "$RSYNC_OUTPUT_FILE"
fi

EXIT=${PIPESTATUS[0]}

parse_rsync_stats "$RSYNC_OUTPUT_FILE"
rm -f "$RSYNC_OUTPUT_FILE"

# ── Push Safe Database Copies ─────────────────────────────────────────────────
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

# ── Sunday Snapshot ──────────────────────────────────────────────────────────
SNAPSHOT_CREATED=false

if [ "$DAY_OF_WEEK" -eq 7 ]; then
    echo "Sunday detected - creating weekly snapshot"
    rsync -avh --stats \
        --password-file="$RSYNC_PASSWORD_FILE" \
        "${RSYNC_DEST}/plex-current/" \
        "${RSYNC_DEST}/${SNAPSHOT_DIR}/${TODAY}/"
    SNAP_EXIT=$?
    if [ $SNAP_EXIT -eq 0 ]; then
        SNAPSHOT_CREATED=true
        echo "Weekly snapshot created: ${SNAPSHOT_DIR}/${TODAY}/"
    else
        echo "WARNING: Weekly snapshot failed with code $SNAP_EXIT"
    fi
fi

# ── Calculate Duration ────────────────────────────────────────────────────────
BACKUP_END=$(date +%s)
BACKUP_DURATION=$((BACKUP_END - BACKUP_START))
DURATION_STR=$(format_duration $BACKUP_DURATION)

# ── Success Rate ──────────────────────────────────────────────────────────────
SUCCESS_TOTAL=$(wc -l < "$TRACKING_FILE" 2>/dev/null || echo "0")
SUCCESS_COUNT=$(grep -c ":success" "$TRACKING_FILE" 2>/dev/null || echo "0")
if [ "$SUCCESS_TOTAL" -gt 0 ]; then
  SUCCESS_RATE="$SUCCESS_COUNT/$SUCCESS_TOTAL ($(( SUCCESS_COUNT * 100 / SUCCESS_TOTAL ))%)"
else
  SUCCESS_RATE="No history"
fi

# ── Format Sizes ──────────────────────────────────────────────────────────────
TOTAL_SIZE_STR="unknown"
XFER_SIZE_STR="unknown"
XFER_FILES_STR="${XFER_FILES:-0} files"

[ -n "$TOTAL_SIZE" ] && TOTAL_SIZE_STR=$(format_bytes "$TOTAL_SIZE")
[ -n "$XFER_SIZE" ] && XFER_SIZE_STR=$(format_bytes "$XFER_SIZE")

# ── Log Result and Send Email ─────────────────────────────────────────────────
if [ $EXIT -eq 0 ]; then
    echo "=== Plex Backup Completed Successfully: $(date) ==="
    record_backup_result "success"

    if [ -n "$EMAIL_TO" ]; then
        if [ "$SNAPSHOT_CREATED" = true ]; then
            SUBJECT="Plex Backup OK + Snapshot — ${TOTAL_SIZE_STR}, ${DURATION_STR}"
        else
            SUBJECT="Plex Backup OK — ${TOTAL_SIZE_STR}, ${DURATION_STR}"
        fi

        if [ "$SAFE_DB_SUCCESS" = true ]; then
            DB_LINE="DB Safety:    sqlite3 .backup (consistent)"
        else
            DB_LINE="DB Safety:    WARNING — live rsync (no safe snapshot)"
        fi

        BODY="Daily mirror completed at ${BACKUP_START_TIME}

Duration:     ${DURATION_STR}
Transferred:  ${XFER_SIZE_STR} (${XFER_FILES_STR})
Total Size:   ${TOTAL_SIZE_STR}
${DB_LINE}
Success Rate: ${SUCCESS_RATE}"

        if [ "$SNAPSHOT_CREATED" = true ]; then
            BODY="${BODY}

Weekly snapshot created: ${TODAY}"
        fi

        BODY="${BODY}

${DASHBOARD_URL}"

        echo "$BODY" | mail -s "$SUBJECT" "$EMAIL_TO"
    fi
else
    echo "=== Plex Backup FAILED with code $EXIT: $(date) ==="
    record_backup_result "failed"

    if [ -n "$EMAIL_TO" ]; then
        SUBJECT="Plex Backup FAILED — exit code ${EXIT}"

        BODY="Backup FAILED at ${BACKUP_START_TIME}

Duration:     ${DURATION_STR}
Exit Code:    ${EXIT}
Success Rate: ${SUCCESS_RATE}

Last 15 log lines:
$(tail -15 "$LOG_FILE")

${DASHBOARD_URL}"

        echo "$BODY" | mail -s "$SUBJECT" "$EMAIL_TO"
    fi
fi
