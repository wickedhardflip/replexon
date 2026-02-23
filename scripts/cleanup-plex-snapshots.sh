#!/bin/bash
# =============================================================================
# cleanup-plex-snapshots.sh - Weekly snapshot retention cleanup
#
# SSH into the NAS and remove oldest snapshots beyond the retention count.
# Requires SSH key auth to the NAS (no password prompts).
#
# Log markers are parsed by RePlexOn dashboard (log_parser.py).
# DO NOT change the marker format without updating the regex patterns.
#
# Schedule: Sunday at 4 AM via cron
#   0 4 * * 0 /usr/local/bin/cleanup-plex-snapshots.sh >> /var/log/plex-backup.log 2>&1
# =============================================================================

# ── Configuration ──────────────────────────────────────────────────────────────
NAS_IP="192.168.1.100"
NAS_USER="admin"
SNAPSHOT_PATH="/volume1/plex-backups/plex-snapshots"
KEEP_COUNT=4  # Number of weekly snapshots to retain

# ── Do not edit below this line ────────────────────────────────────────────────

echo "=== Plex Snapshot Cleanup - $(date) ===="

# List snapshot directories (YYYY-MM-DD format), sorted oldest first
SNAPSHOTS=$(ssh "${NAS_USER}@${NAS_IP}" "ls -1d ${SNAPSHOT_PATH}/????-??-??/ 2>/dev/null | sort")
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
    ssh "${NAS_USER}@${NAS_IP}" "rm -rf '$SNAP_DIR'"
done

echo "Cleanup complete. Removed $DELETE_COUNT old snapshot(s)."
