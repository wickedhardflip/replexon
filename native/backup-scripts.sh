#!/bin/bash
# =============================================================================
# backup-scripts.sh - Monthly config self-backup
#
# Collects all backup-related scripts and config files into a temporary
# directory, then rsyncs them to the NAS for safekeeping.
#
# Schedule: 1st of month at 5 AM via cron
#   0 5 1 * * /usr/local/bin/backup-scripts.sh >> /var/log/plex-backup.log 2>&1
# =============================================================================

# ── Configuration ──────────────────────────────────────────────────────────────
NAS_IP="192.168.1.100"
RSYNC_USER="backupuser"
RSYNC_MODULE="plex-backups"
RSYNC_PASSWORD_FILE="/etc/replexon/rsync.secret"
RSYNC_DEST="${RSYNC_USER}@${NAS_IP}::${RSYNC_MODULE}"

# Files and directories to back up
SCRIPT_PATHS=(
    "/usr/local/bin/backup-plex.sh"
    "/usr/local/bin/cleanup-plex-snapshots.sh"
    "/usr/local/bin/backup-scripts.sh"
    "/etc/replexon/"
    "/opt/replexon/.env"
    "/opt/replexon/systemd/"
)

# ── Do not edit below this line ────────────────────────────────────────────────

echo "=== Script Config Backup Started: $(date) ==="

TMPDIR=$(mktemp -d)
trap "rm -rf '$TMPDIR'" EXIT

for SRC in "${SCRIPT_PATHS[@]}"; do
    if [ -e "$SRC" ]; then
        # Preserve directory structure
        DEST_DIR="$TMPDIR/$(dirname "$SRC")"
        mkdir -p "$DEST_DIR"
        cp -a "$SRC" "$DEST_DIR/"
        echo "Collected: $SRC"
    else
        echo "Skipping (not found): $SRC"
    fi
done

# Also save current crontab
crontab -l > "$TMPDIR/crontab-$(whoami).txt" 2>/dev/null && echo "Collected: crontab"

# Rsync to NAS
rsync -avh \
    --password-file="$RSYNC_PASSWORD_FILE" \
    "$TMPDIR/" \
    "${RSYNC_DEST}/config-backups/$(date +%Y-%m-%d)/"

EXIT=$?
if [ $EXIT -eq 0 ]; then
    echo "=== Script Config Backup Completed: $(date) ==="
else
    echo "=== Script Config Backup FAILED with code $EXIT: $(date) ==="
fi
