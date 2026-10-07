#!/bin/bash
# =============================================================================
# backup-plex.sh - Plex Media Server backup via rsync (RePlexOn)
#
# Mirrors the chosen parts of the Plex data folder to a local folder or an rsync
# daemon on a NAS. On Sundays it also makes a dated snapshot for weekly retention.
#
# DATABASE SAFETY (DB_SAFETY):
#   safe_copy        (default) copy each .db with its -wal/-shm to scratch space, run
#                    sqlite3 .backup on the copy, check it, and ship that. Plex keeps running.
#   pause_container  pause the Plex container through /var/run/docker.sock while the
#                    files are copied, then resume it. Needs the socket mounted.
#   There is no live-file fallback: if a database cannot be copied consistently the
#   run is marked FAILED (the rest of the data is still mirrored, and the last good
#   database copy at the destination is left untouched).
#
# Configuration comes from the environment. RePlexOn passes it in from the Settings
# page. Bare-metal cron use can put the same variables in /etc/replexon/backup.env.
#
# Log markers are parsed by RePlexOn (app/services/log_parser.py).
# DO NOT change the marker format without updating the regex patterns.
# =============================================================================

if [ -z "$REPLEXON_MANAGED" ] && [ -r "${REPLEXON_ENV_FILE:-/etc/replexon/backup.env}" ]; then
    # shellcheck disable=SC1090
    . "${REPLEXON_ENV_FILE:-/etc/replexon/backup.env}"
fi

# -- Configuration ------------------------------------------------------------
PLEX_DATA="${PLEX_DATA:-/plex}"
BACKUP_MODE="${BACKUP_MODE:-local}"            # local | nas
BACKUP_DIR="${BACKUP_DIR:-/backups}"
NAS_IP="${NAS_IP:-}"
RSYNC_USER="${RSYNC_USER:-}"
RSYNC_MODULE="${RSYNC_MODULE:-}"
RSYNC_PASSWORD_FILE="${RSYNC_PASSWORD_FILE:-/data/rsync.secret}"
LOG_FILE="${BACKUP_LOG_PATH:-/data/logs/plex-backup.log}"
TRACKING_FILE="${LOG_FILE%.log}-tracking.log"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-plex-snapshots}"
BACKUP_ITEMS="${BACKUP_ITEMS:-databases,preferences,plugins}"
DB_SAFETY="${DB_SAFETY:-safe_copy}"
PLEX_CONTAINER="${PLEX_CONTAINER:-plex}"
DOCKER_SOCK="${DOCKER_SOCK:-/var/run/docker.sock}"
SCRATCH_DIR="${SCRATCH_DIR:-/tmp}"

# -- Setup --------------------------------------------------------------------
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1   # stdout (docker logs / RePlexOn) and the log file

TODAY=$(date +%Y-%m-%d)
DAY_OF_WEEK=$(date +%u)  # 1=Monday, 7=Sunday
[ -n "$FORCE_SNAPSHOT" ] && DAY_OF_WEEK=7

DB_DIR="$PLEX_DATA/Plug-in Support/Databases"
STAGING_DIR="$SCRATCH_DIR/replexon-db.$$"
SAFE_DB_SUCCESS=false
PAUSED=false

# -- Helper Functions ---------------------------------------------------------

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
  TOTAL_SIZE=$(grep "Total file size:" "$stats_file" 2>/dev/null | grep -oP '[\d,]+' | head -1 | tr -d ',')
  XFER_SIZE=$(grep "Total transferred file size:" "$stats_file" 2>/dev/null | grep -oP '[\d,]+' | head -1 | tr -d ',')
}

record_backup_result() {
  echo "$(date +%Y-%m-%d):$1" >> "$TRACKING_FILE"
  tail -n 30 "$TRACKING_FILE" > "$TRACKING_FILE.tmp" && mv "$TRACKING_FILE.tmp" "$TRACKING_FILE"
}

has_item() {
  case ",$BACKUP_ITEMS," in *",$1,"*) return 0 ;; esac
  return 1
}

docker_api() {  # docker_api pause|unpause
  curl -sf -o /dev/null --max-time 30 --unix-socket "$DOCKER_SOCK" \
    -X POST "http://localhost/containers/${PLEX_CONTAINER}/$1"
}

resume_plex() {
  if [ "$PAUSED" = true ]; then
    if docker_api unpause; then
      echo "Resumed Plex container: $PLEX_CONTAINER"
    else
      echo "ERROR: could not resume Plex container $PLEX_CONTAINER - run: docker unpause $PLEX_CONTAINER"
    fi
    PAUSED=false
  fi
}

finish() {
  resume_plex
  rm -rf "$STAGING_DIR"
}
trap finish EXIT

fail_early() {  # fail_early <code> <message>
  echo "ERROR: $2"
  echo "=== Plex Backup FAILED with code $1: $(date) ==="
  record_backup_result "failed"
  exit "$1"
}

# Copy every database consistently into $STAGING_DIR. Sets DB_COUNT / DB_FAILED.
copy_databases() {
  local raw="$STAGING_DIR/raw" db_file name attempt ok ext
  mkdir -p "$raw"
  DB_COUNT=0
  DB_FAILED=0
  for db_file in "$DB_DIR"/*.db; do
    [ -f "$db_file" ] || continue
    name=$(basename "$db_file")
    echo "Backing up: $name ($(du -m "$db_file" | cut -f1) MB)"
    ok=false
    for attempt in 1 2; do
      rm -f "$raw/$name" "$raw/$name-wal" "$raw/$name-shm" "$STAGING_DIR/$name"
      cp "$db_file" "$raw/$name" || continue
      for ext in -wal -shm; do
        [ -f "$db_file$ext" ] && { cp "$db_file$ext" "$raw/$name$ext" 2>/dev/null || true; }
      done
      if sqlite3 "$raw/$name" ".backup '$STAGING_DIR/$name'" \
         && [ "$(sqlite3 "$STAGING_DIR/$name" 'PRAGMA quick_check;' 2>&1)" = "ok" ]; then
        ok=true
        break
      fi
      echo "WARNING: copy of $name was not consistent (attempt $attempt)"
    done
    rm -f "$raw/$name" "$raw/$name-wal" "$raw/$name-shm"
    if [ "$ok" = true ]; then
      DB_COUNT=$((DB_COUNT + 1))
    else
      echo "ERROR: could not make a consistent copy of $name"
      DB_FAILED=$((DB_FAILED + 1))
    fi
  done
  rm -rf "$raw"
}

# -- Start --------------------------------------------------------------------
BACKUP_START=$(date +%s)

echo "=== Plex Backup Started: $(date) ==="

if [ "$BACKUP_MODE" = "nas" ]; then
    if [ -z "$NAS_IP" ] || [ -z "$RSYNC_USER" ] || [ -z "$RSYNC_MODULE" ]; then
        fail_early 1 "NAS mode needs the NAS address, rsync user and module (Settings > Destination)"
    fi
    RSYNC_DEST="${RSYNC_USER}@${NAS_IP}::${RSYNC_MODULE}"
    RSYNC_AUTH_OPTS=()
    [ -z "$RSYNC_PASSWORD" ] && RSYNC_AUTH_OPTS=(--password-file="$RSYNC_PASSWORD_FILE")
else
    [ -n "$BACKUP_DIR" ] || fail_early 1 "No backup folder set (Settings > Destination)"
    RSYNC_DEST="$BACKUP_DIR"
    RSYNC_AUTH_OPTS=()
    mkdir -p "$BACKUP_DIR/plex-current" || fail_early 1 "Cannot write to $BACKUP_DIR"
fi

echo "Mode: $BACKUP_MODE | Source: $PLEX_DATA | Dest: $RSYNC_DEST | Items: $BACKUP_ITEMS | DB safety: $DB_SAFETY"

[ -d "$DB_DIR" ] || fail_early 2 "Plex databases not found at: $DB_DIR (check the Plex location in Settings)"
command -v sqlite3 >/dev/null 2>&1 || fail_early 2 "sqlite3 is not installed; it is required for a safe database copy"

# -- Safe Database Snapshot ---------------------------------------------------
DB_START=$(date +%s)
echo "--- Safe database snapshot: starting ---"

if [ "$DB_SAFETY" = "pause_container" ]; then
    if [ ! -S "$DOCKER_SOCK" ]; then
        echo "WARNING: pause mode needs $DOCKER_SOCK mounted; using safe copy without pausing"
    elif docker_api pause; then
        PAUSED=true
        echo "Paused Plex container: $PLEX_CONTAINER"
    else
        echo "WARNING: could not pause container '$PLEX_CONTAINER'; using safe copy without pausing"
    fi
fi

copy_databases
resume_plex

DB_ELAPSED=$(( $(date +%s) - DB_START ))
if [ "$DB_FAILED" -eq 0 ] && [ "$DB_COUNT" -gt 0 ]; then
    SAFE_DB_SUCCESS=true
    echo "--- Safe database snapshot: complete ($DB_COUNT databases, ${DB_ELAPSED}s) ---"
else
    echo "ERROR: Plex database backup FAILED ($DB_FAILED failed, $DB_COUNT copied). Databases were NOT backed up this run."
fi

# -- Daily Mirror -------------------------------------------------------------
EXCLUDES=(
    --exclude='/Cache/' --exclude='/Plug-in Support/Caches/' --exclude='/Logs/'
    --exclude='/Crash Reports/' --exclude='/Diagnostics/' --exclude='/Updates/'
    --exclude='/Codecs/' --exclude='/Drivers/'
    # Databases only ever come from the consistent copies above, never the live files.
    --exclude='/Plug-in Support/Databases/*.db'
    --exclude='/Plug-in Support/Databases/*.db-shm'
    --exclude='/Plug-in Support/Databases/*.db-wal'
)
has_item preferences || EXCLUDES+=(--exclude='/Preferences.xml')
has_item plugins || EXCLUDES+=(--exclude='/Plug-ins/' --exclude='/Scanners/'
                               --exclude='/Plug-in Support/Data/' --exclude='/Plug-in Support/Preferences/')
has_item metadata || EXCLUDES+=(--exclude='/Metadata/' --exclude='/Media/'
                                --exclude='/Plug-in Support/Metadata Combination/')

RSYNC_OUTPUT_FILE="$SCRATCH_DIR/plex-backup-rsync-output.$$"
rsync -avh --delete --stats "${RSYNC_AUTH_OPTS[@]}" "${EXCLUDES[@]}" \
    "$PLEX_DATA/" \
    "${RSYNC_DEST}/plex-current/" \
    2>&1 | tee "$RSYNC_OUTPUT_FILE"
EXIT=${PIPESTATUS[0]}

parse_rsync_stats "$RSYNC_OUTPUT_FILE"
rm -f "$RSYNC_OUTPUT_FILE"

# -- Push Safe Database Copies ------------------------------------------------
if [ $EXIT -eq 0 ] && [ "$SAFE_DB_SUCCESS" = true ]; then
    echo "Syncing safe database copies..."
    [ "$BACKUP_MODE" = "local" ] && mkdir -p "${RSYNC_DEST}/plex-current/Plug-in Support/Databases"
    rsync -avh "${RSYNC_AUTH_OPTS[@]}" \
        "$STAGING_DIR/" \
        "${RSYNC_DEST}/plex-current/Plug-in Support/Databases/"
    DB_PUSH_EXIT=$?
    if [ $DB_PUSH_EXIT -ne 0 ]; then
        echo "ERROR: failed to sync safe database copies (exit $DB_PUSH_EXIT)"
        EXIT=$DB_PUSH_EXIT
    fi
fi

# A run without a good database copy is a failed run.
if [ $EXIT -eq 0 ] && [ "$SAFE_DB_SUCCESS" != true ]; then
    EXIT=3
fi

# -- Sunday Snapshot ----------------------------------------------------------
if [ $EXIT -eq 0 ] && [ "$DAY_OF_WEEK" -eq 7 ]; then
    echo "Sunday detected - creating weekly snapshot"
    if [ "$BACKUP_MODE" = "local" ]; then
        mkdir -p "${BACKUP_DIR}/${SNAPSHOT_DIR}/${TODAY}"
        rsync -avh --stats \
            "${BACKUP_DIR}/plex-current/" \
            "${BACKUP_DIR}/${SNAPSHOT_DIR}/${TODAY}/"
    else
        rsync -avh --stats "${RSYNC_AUTH_OPTS[@]}" \
            "${RSYNC_DEST}/plex-current/" \
            "${RSYNC_DEST}/${SNAPSHOT_DIR}/${TODAY}/"
    fi
    SNAP_EXIT=$?
    if [ $SNAP_EXIT -eq 0 ]; then
        echo "Weekly snapshot created: ${SNAPSHOT_DIR}/${TODAY}/"
    else
        echo "WARNING: Weekly snapshot failed with code $SNAP_EXIT"
    fi
fi

# -- Summary ------------------------------------------------------------------
DURATION_STR=$(format_duration $(( $(date +%s) - BACKUP_START )))
TOTAL_SIZE_STR="unknown"
XFER_SIZE_STR="unknown"
[ -n "$TOTAL_SIZE" ] && TOTAL_SIZE_STR=$(format_bytes "$TOTAL_SIZE")
[ -n "$XFER_SIZE" ] && XFER_SIZE_STR=$(format_bytes "$XFER_SIZE")
echo "Duration: $DURATION_STR | Transferred: $XFER_SIZE_STR (${XFER_FILES:-0} files) | Total: $TOTAL_SIZE_STR"

# -- Log Result ---------------------------------------------------------------
if [ $EXIT -eq 0 ]; then
    echo "=== Plex Backup Completed Successfully: $(date) ==="
    record_backup_result "success"
else
    echo "=== Plex Backup FAILED with code $EXIT: $(date) ==="
    record_backup_result "failed"
fi
exit $EXIT
