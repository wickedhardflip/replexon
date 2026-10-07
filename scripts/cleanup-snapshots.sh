#!/bin/bash
# =============================================================================
# cleanup-snapshots.sh - Weekly snapshot retention (RePlexOn)
#
# Keeps the newest SNAPSHOT_KEEP_COUNT dated snapshots and removes older ones,
# in a local backup folder or on an rsync daemon (no SSH needed).
#
# Log markers are parsed by RePlexOn (app/services/log_parser.py).
# DO NOT change the marker format without updating the regex patterns.
# =============================================================================

if [ -z "$REPLEXON_MANAGED" ] && [ -r "${REPLEXON_ENV_FILE:-/etc/replexon/backup.env}" ]; then
    # shellcheck disable=SC1090
    . "${REPLEXON_ENV_FILE:-/etc/replexon/backup.env}"
fi

BACKUP_MODE="${BACKUP_MODE:-local}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
NAS_IP="${NAS_IP:-}"
RSYNC_USER="${RSYNC_USER:-}"
RSYNC_MODULE="${RSYNC_MODULE:-}"
RSYNC_PASSWORD_FILE="${RSYNC_PASSWORD_FILE:-/data/rsync.secret}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-plex-snapshots}"
KEEP_COUNT="${SNAPSHOT_KEEP_COUNT:-4}"
LOG_FILE="${BACKUP_LOG_PATH:-/data/logs/plex-backup.log}"

mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Plex Snapshot Cleanup - $(date) ===="

case "$KEEP_COUNT" in ''|*[!0-9]*) echo "Invalid SNAPSHOT_KEEP_COUNT: $KEEP_COUNT"; exit 1 ;; esac
if [ "$KEEP_COUNT" -lt 1 ]; then
    echo "SNAPSHOT_KEEP_COUNT must be at least 1"
    exit 1
fi

if [ "$BACKUP_MODE" = "nas" ]; then
    AUTH=()
    [ -z "$RSYNC_PASSWORD" ] && AUTH=(--password-file="$RSYNC_PASSWORD_FILE")
    REMOTE="${RSYNC_USER}@${NAS_IP}::${RSYNC_MODULE}/${SNAPSHOT_DIR}/"
    SNAPSHOTS=$(rsync --list-only "${AUTH[@]}" "$REMOTE" 2>/dev/null \
        | awk '{print $NF}' | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort)
else
    SNAP_PATH="$BACKUP_DIR/$SNAPSHOT_DIR"
    if [ ! -d "$SNAP_PATH" ]; then
        echo "Snapshot directory not found: $SNAP_PATH"
        echo "Cleanup complete."
        exit 0
    fi
    SNAPSHOTS=$(cd "$SNAP_PATH" && ls -1d ????-??-?? 2>/dev/null | sort)
fi

TOTAL=$(echo "$SNAPSHOTS" | grep -c .)
if [ "$TOTAL" -le "$KEEP_COUNT" ]; then
    echo "Only $TOTAL snapshots found (keeping $KEEP_COUNT). Nothing to clean."
    echo "Cleanup complete."
    exit 0
fi

DELETE_COUNT=$((TOTAL - KEEP_COUNT))
echo "Found $TOTAL snapshots, keeping $KEEP_COUNT, deleting $DELETE_COUNT oldest"

FAILED=0
EMPTY=$(mktemp -d)
for SNAP in $(echo "$SNAPSHOTS" | head -n "$DELETE_COUNT"); do
    echo "Deleting: $SNAP"
    if [ "$BACKUP_MODE" = "nas" ]; then
        # Sync an empty folder over just this one dated folder: rsync deletes it on the daemon.
        rsync -r --delete "${AUTH[@]}" --include="/$SNAP/***" --exclude='*' "$EMPTY/" "$REMOTE" || FAILED=1
    else
        rm -rf "${SNAP_PATH:?}/$SNAP" || FAILED=1
    fi
done
rmdir "$EMPTY"

if [ "$FAILED" -ne 0 ]; then
    echo "Cleanup finished with errors."
    exit 1
fi
echo "Cleanup complete. Removed $DELETE_COUNT old snapshot(s)."
