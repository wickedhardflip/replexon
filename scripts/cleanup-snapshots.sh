#!/bin/bash
# =============================================================================
# cleanup-snapshots.sh - Weekly snapshot retention cleanup
#
# Removes oldest snapshots beyond the retention count from local backup dir.
#
# Log markers are parsed by RePlexOn dashboard (log_parser.py).
# DO NOT change the marker format without updating the regex patterns.
# =============================================================================

# ── Configuration (from environment) ─────────────────────────────────────────
BACKUP_MODE="${BACKUP_MODE:-local}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-plex-snapshots}"
KEEP_COUNT="${SNAPSHOT_KEEP_COUNT:-4}"
LOG_FILE="${BACKUP_LOG_PATH:-/data/logs/plex-backup.log}"

# ── Setup ────────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Plex Snapshot Cleanup - $(date) ===="

if [ "$BACKUP_MODE" != "local" ]; then
    echo "Snapshot cleanup runs locally only. For NAS cleanup, run from your NAS or host."
    echo "Cleanup complete."
    exit 0
fi

SNAP_PATH="$BACKUP_DIR/$SNAPSHOT_DIR"

if [ ! -d "$SNAP_PATH" ]; then
    echo "Snapshot directory not found: $SNAP_PATH"
    echo "Cleanup complete."
    exit 0
fi

SNAPSHOTS=$(ls -1d "$SNAP_PATH"/????-??-??/ 2>/dev/null | sort)
TOTAL=$(echo "$SNAPSHOTS" | grep -c .)

if [ "$TOTAL" -le "$KEEP_COUNT" ]; then
    echo "Only $TOTAL snapshots found (keeping $KEEP_COUNT). Nothing to clean."
    echo "Cleanup complete."
    exit 0
fi

DELETE_COUNT=$((TOTAL - KEEP_COUNT))
echo "Found $TOTAL snapshots, keeping $KEEP_COUNT, deleting $DELETE_COUNT oldest"

echo "$SNAPSHOTS" | head -n "$DELETE_COUNT" | while read -r SNAP_DIR; do
    echo "Deleting: $SNAP_DIR"
    rm -rf "$SNAP_DIR"
done

echo "Cleanup complete. Removed $DELETE_COUNT old snapshot(s)."
