#!/bin/bash
# =============================================================================
# RePlexOn bare-metal installer (Ubuntu / Debian, systemd)
#
#   sudo bash native/install.sh
#
# Installs the app to /opt/replexon as a systemd service. Everything else
# (Plex location, destination, schedule, email) is set in the web setup wizard;
# the app runs the backups itself, so no crontab entries are needed.
# Docker is the recommended way to run RePlexOn; see the main README.
# =============================================================================

set -euo pipefail

INSTALL_DIR="/opt/replexon"
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)  # repo root (this file lives in native/)
PORT=9847

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

case "${1:-}" in
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    "") ;;
    *) err "Unknown option: $1"; exit 1 ;;
esac

[ "$(id -u)" -eq 0 ] || { err "Run as root (sudo)."; exit 1; }
. /etc/os-release 2>/dev/null || true
case "${ID:-}" in
    ubuntu|debian) log "Detected ${PRETTY_NAME:-$ID}" ;;
    *) warn "Untested OS '${ID:-unknown}'; continuing (needs apt and systemd)" ;;
esac

log "Installing system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv rsync sqlite3 bc curl > /dev/null

PYV=$(python3 -c 'import sys; print("%d%02d" % sys.version_info[:2])')
[ "$PYV" -ge 310 ] || { err "Python 3.10 or newer is required (found $(python3 -V))."; exit 1; }

# Run as the plex user when present so the app can read the Plex data folder.
if id plex &>/dev/null; then SERVICE_USER=plex; else SERVICE_USER=www-data; fi
log "Service user: $SERVICE_USER"

log "Copying app to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude='venv/' --exclude='.venv/' --exclude='data/' --exclude='.env' \
    --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' --exclude='tests/' \
    "$REPO_DIR/" "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/data/logs" "$INSTALL_DIR/data/scratch"

log "Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

ENV_FILE="$INSTALL_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    warn "$ENV_FILE exists, leaving it alone"
else
    # Bootstrap paths only. SECRET_KEY is generated into data/.secret_key on first start.
    cat > "$ENV_FILE" <<EOF
DATA_DIR=$INSTALL_DIR/data
BACKUP_LOG_PATH=$INSTALL_DIR/data/logs/plex-backup.log
BACKUP_SCRIPT_PATH=$INSTALL_DIR/scripts/backup-plex.sh
SCRATCH_DIR=$INSTALL_DIR/data/scratch
EOF
    chmod 600 "$ENV_FILE"
    log "Wrote $ENV_FILE"
fi
chmod +x "$INSTALL_DIR"/scripts/*.sh
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

sed "s/SERVICE_USER/$SERVICE_USER/g" "$INSTALL_DIR/native/logrotate-replexon" > /etc/logrotate.d/replexon
chmod 644 /etc/logrotate.d/replexon

log "Installing systemd service..."
cp "$INSTALL_DIR/native/systemd/replexon.service" /etc/systemd/system/replexon.service
sed -i "s/^User=.*/User=$SERVICE_USER/; s/^Group=.*/Group=$SERVICE_USER/" /etc/systemd/system/replexon.service
systemctl daemon-reload
systemctl enable --now replexon

if crontab -l 2>/dev/null | grep -q "backup-plex.sh"; then
    warn "root's crontab still runs backup-plex.sh. RePlexOn now schedules backups itself;"
    warn "remove those lines (sudo crontab -e) so backups do not run twice."
fi

cat <<EOF

  RePlexOn is running.  Open http://$(hostname -I | awk '{print $1}'):$PORT to finish setup.

  Backing up to a local folder or a mounted share? Let the service write there:
    sudo systemctl edit replexon
      [Service]
      ReadWritePaths=/path/to/backups
  and make sure $SERVICE_USER can write to it.

EOF
