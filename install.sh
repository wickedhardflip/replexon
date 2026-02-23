#!/bin/bash
# =============================================================================
# RePlexOn Installer
#
# Usage:
#   sudo bash install.sh                 # Default mode (minimal prompts)
#   sudo bash install.sh --interactive   # Interactive mode (prompts for all config)
#
# Installs the RePlexOn Plex backup dashboard and optionally sets up
# the backup scripts, systemd service, and cron schedules.
# =============================================================================

set -euo pipefail

APP_NAME="RePlexOn"
INSTALL_DIR="/opt/replexon"
CONFIG_DIR="/etc/replexon"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
INTERACTIVE=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }
info() { echo -e "${BLUE}[i]${NC} $*"; }

# Parse arguments
for arg in "$@"; do
    case $arg in
        --interactive|-i) INTERACTIVE=true ;;
        --help|-h)
            echo "Usage: sudo bash install.sh [--interactive]"
            echo ""
            echo "Options:"
            echo "  --interactive, -i   Prompt for all configuration values"
            echo "  --help, -h          Show this help"
            exit 0
            ;;
        *) err "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Pre-flight Checks ─────────────────────────────────────────────────────────

check_os() {
    if [ ! -f /etc/os-release ]; then
        err "Cannot detect OS. This installer requires Ubuntu or Debian."
        exit 1
    fi
    . /etc/os-release
    case "$ID" in
        ubuntu|debian) log "Detected $PRETTY_NAME" ;;
        *)
            err "Unsupported OS: $ID. This installer is designed for Ubuntu/Debian."
            exit 1
            ;;
    esac
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        err "This script must be run as root (use sudo)."
        exit 1
    fi
}

# ── System Dependencies ───────────────────────────────────────────────────────

install_system_deps() {
    log "Installing system dependencies..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv rsync > /dev/null

    # msmtp is optional for email
    if $INTERACTIVE; then
        read -rp "Install msmtp for email notifications? [Y/n] " install_msmtp
        install_msmtp=${install_msmtp:-Y}
    else
        install_msmtp="Y"
    fi
    if [[ "$install_msmtp" =~ ^[Yy] ]]; then
        apt-get install -y -qq msmtp msmtp-mta > /dev/null
        log "msmtp installed"
    fi
}

# ── Application Directory ─────────────────────────────────────────────────────

create_app_directory() {
    log "Setting up application directory at $INSTALL_DIR..."

    if [ -d "$INSTALL_DIR" ]; then
        warn "$INSTALL_DIR already exists. Updating files..."
    else
        mkdir -p "$INSTALL_DIR"
    fi

    # Copy app files (exclude venv, data, .env, .git)
    rsync -a --exclude='venv/' --exclude='.venv/' --exclude='data/' \
        --exclude='.env' --exclude='.git/' --exclude='__pycache__/' \
        --exclude='*.pyc' --exclude='install.sh' \
        "$SCRIPT_DIR/" "$INSTALL_DIR/"

    # Create data directory
    mkdir -p "$INSTALL_DIR/data"

    # Determine service user
    if id "plex" &>/dev/null; then
        SERVICE_USER="plex"
    else
        SERVICE_USER="www-data"
        if $INTERACTIVE; then
            read -rp "Service user (default: $SERVICE_USER): " custom_user
            SERVICE_USER=${custom_user:-$SERVICE_USER}
        fi
    fi
    SERVICE_GROUP="$SERVICE_USER"

    chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
    log "Owned by $SERVICE_USER:$SERVICE_GROUP"
}

# ── Python Virtual Environment ────────────────────────────────────────────────

setup_venv() {
    log "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
    log "Python dependencies installed"
}

# ── Environment Configuration ─────────────────────────────────────────────────

configure_env() {
    local env_file="$INSTALL_DIR/.env"

    if [ -f "$env_file" ]; then
        warn ".env already exists, skipping (edit manually if needed)"
        return
    fi

    log "Generating .env configuration..."
    cp "$INSTALL_DIR/.env.example" "$env_file"

    # Auto-generate SECRET_KEY
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" "$env_file"
    log "SECRET_KEY generated"

    if $INTERACTIVE; then
        # Backup log path
        read -rp "Backup log path [/var/log/plex-backup.log]: " log_path
        log_path=${log_path:-/var/log/plex-backup.log}
        sed -i "s|^BACKUP_LOG_PATH=.*|BACKUP_LOG_PATH=$log_path|" "$env_file"

        # Backup script path
        read -rp "Backup script path [/usr/local/bin/backup-plex.sh]: " script_path
        script_path=${script_path:-/usr/local/bin/backup-plex.sh}
        sed -i "s|^BACKUP_SCRIPT_PATH=.*|BACKUP_SCRIPT_PATH=$script_path|" "$env_file"

        # Plex data path - try to auto-detect
        detected_plex=""
        for plex_path in \
            "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server" \
            "/snap/plexmediaserver/common/Library/Application Support/Plex Media Server" \
            "/opt/plexmediaserver/Library/Application Support/Plex Media Server"; do
            if [ -d "$plex_path" ]; then
                detected_plex="$plex_path"
                break
            fi
        done
        if [ -n "$detected_plex" ]; then
            info "Auto-detected Plex data at: $detected_plex"
            read -rp "Plex data path [$detected_plex]: " plex_data
            plex_data=${plex_data:-$detected_plex}
        else
            read -rp "Plex data path: " plex_data
        fi
        if [ -n "$plex_data" ]; then
            sed -i "s|^PLEX_DATA_PATH=.*|PLEX_DATA_PATH=$plex_data|" "$env_file"
        fi

        # Backup destination
        read -rp "Backup destination (e.g., rsync://user@NAS_IP/module/plex): " backup_dest
        if [ -n "$backup_dest" ]; then
            sed -i "s|^BACKUP_DESTINATION=.*|BACKUP_DESTINATION=$backup_dest|" "$env_file"
        fi

        # Cron editing
        read -rp "Enable cron editing via UI? [y/N] " cron_edit
        if [[ "$cron_edit" =~ ^[Yy] ]]; then
            sed -i "s/^CRON_EDIT_ENABLED=.*/CRON_EDIT_ENABLED=true/" "$env_file"
        fi
    fi

    chown "$SERVICE_USER:$SERVICE_GROUP" "$env_file"
    chmod 600 "$env_file"
    log ".env configured"
}

# ── Backup Scripts ────────────────────────────────────────────────────────────

install_backup_scripts() {
    log "Installing backup scripts..."
    mkdir -p "$CONFIG_DIR"

    # Create rsync secret file
    if [ ! -f "$CONFIG_DIR/rsync.secret" ]; then
        cp "$INSTALL_DIR/scripts/rsync.secret.example" "$CONFIG_DIR/rsync.secret"
        chmod 600 "$CONFIG_DIR/rsync.secret"
        log "Created $CONFIG_DIR/rsync.secret (edit with your rsync password)"
    else
        warn "$CONFIG_DIR/rsync.secret already exists, skipping"
    fi

    # Copy scripts to /usr/local/bin
    for script in backup-plex.sh cleanup-plex-snapshots.sh backup-scripts.sh; do
        cp "$INSTALL_DIR/scripts/$script" "/usr/local/bin/$script"
        chmod +x "/usr/local/bin/$script"
    done

    if $INTERACTIVE; then
        # Configure script variables
        read -rp "NAS/Synology IP address: " nas_ip
        if [ -n "$nas_ip" ]; then
            sed -i "s/^NAS_IP=.*/NAS_IP=\"$nas_ip\"/" /usr/local/bin/backup-plex.sh
            sed -i "s/^NAS_IP=.*/NAS_IP=\"$nas_ip\"/" /usr/local/bin/cleanup-plex-snapshots.sh
            sed -i "s/^NAS_IP=.*/NAS_IP=\"$nas_ip\"/" /usr/local/bin/backup-scripts.sh
        fi

        read -rp "Rsync username [backupuser]: " rsync_user
        rsync_user=${rsync_user:-backupuser}
        sed -i "s/^RSYNC_USER=.*/RSYNC_USER=\"$rsync_user\"/" /usr/local/bin/backup-plex.sh
        sed -i "s/^RSYNC_USER=.*/RSYNC_USER=\"$rsync_user\"/" /usr/local/bin/backup-scripts.sh

        read -rp "Rsync module name [plex-backups]: " rsync_module
        rsync_module=${rsync_module:-plex-backups}
        sed -i "s/^RSYNC_MODULE=.*/RSYNC_MODULE=\"$rsync_module\"/" /usr/local/bin/backup-plex.sh
        sed -i "s/^RSYNC_MODULE=.*/RSYNC_MODULE=\"$rsync_module\"/" /usr/local/bin/backup-scripts.sh

        read -rp "Failure notification email (leave empty to disable): " fail_email
        if [ -n "$fail_email" ]; then
            sed -i "s/^EMAIL_ON_FAILURE=.*/EMAIL_ON_FAILURE=\"$fail_email\"/" /usr/local/bin/backup-plex.sh
        fi

        # Plex data path in backup script
        if [ -n "${plex_data:-}" ]; then
            sed -i "s|^PLEX_DATA=.*|PLEX_DATA=\"$plex_data\"|" /usr/local/bin/backup-plex.sh
        fi
    fi

    log "Backup scripts installed to /usr/local/bin/"
}

# ── Crontab ───────────────────────────────────────────────────────────────────

setup_crontab() {
    local cron_entries="# RePlexOn backup schedule
0 3 * * *   /usr/local/bin/backup-plex.sh >> /var/log/plex-backup.log 2>&1
0 4 * * 0   /usr/local/bin/cleanup-plex-snapshots.sh >> /var/log/plex-backup.log 2>&1
0 5 1 * *   /usr/local/bin/backup-scripts.sh >> /var/log/plex-backup.log 2>&1"

    if $INTERACTIVE; then
        echo ""
        info "Recommended crontab entries:"
        echo "$cron_entries"
        echo ""
        read -rp "Add these to root's crontab? [Y/n] " add_cron
        add_cron=${add_cron:-Y}
        if [[ "$add_cron" =~ ^[Yy] ]]; then
            # Check if entries already exist
            if crontab -l 2>/dev/null | grep -q "backup-plex.sh"; then
                warn "Crontab entries already exist, skipping"
            else
                (crontab -l 2>/dev/null; echo ""; echo "$cron_entries") | crontab -
                log "Crontab entries added"
            fi
        fi
    else
        echo ""
        info "Add these to root's crontab (sudo crontab -e):"
        echo "$cron_entries"
    fi
}

# ── systemd Service ───────────────────────────────────────────────────────────

install_systemd_service() {
    log "Installing systemd service..."
    cp "$INSTALL_DIR/systemd/replexon.service" /etc/systemd/system/replexon.service

    # Update user/group in service file
    sed -i "s/^User=.*/User=$SERVICE_USER/" /etc/systemd/system/replexon.service
    sed -i "s/^Group=.*/Group=$SERVICE_GROUP/" /etc/systemd/system/replexon.service

    systemctl daemon-reload
    systemctl enable replexon
    log "Service installed and enabled"
}

# ── Initialize App ────────────────────────────────────────────────────────────

initialize_app() {
    log "Initializing database..."
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" replexon.py init-db

    if $INTERACTIVE; then
        echo ""
        read -rp "Create admin user now? [Y/n] " create_admin
        create_admin=${create_admin:-Y}
        if [[ "$create_admin" =~ ^[Yy] ]]; then
            read -rp "Admin username [admin]: " admin_user
            admin_user=${admin_user:-admin}
            sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/python" replexon.py create-user --username "$admin_user" --admin
        fi
    fi
}

# ── Summary ───────────────────────────────────────────────────────────────────

print_summary() {
    echo ""
    echo "============================================"
    echo -e "  ${GREEN}${APP_NAME} Installation Complete${NC}"
    echo "============================================"
    echo ""
    echo "  Install directory:  $INSTALL_DIR"
    echo "  Config directory:   $CONFIG_DIR"
    echo "  Service user:       $SERVICE_USER"
    echo "  Web port:           9847"
    echo ""

    if ! $INTERACTIVE; then
        echo "  Manual steps remaining:"
        echo "  ────────────────────────"
        echo "  1. Edit rsync password:   sudo nano $CONFIG_DIR/rsync.secret"
        echo "  2. Edit backup scripts:   sudo nano /usr/local/bin/backup-plex.sh"
        echo "  3. Create admin user:     cd $INSTALL_DIR && sudo -u $SERVICE_USER venv/bin/python replexon.py create-user --username admin --admin"
        echo "  4. Set up crontab:        sudo crontab -e"
        echo ""
    fi

    echo "  Start the service:"
    echo "    sudo systemctl start replexon"
    echo ""
    echo "  Then visit: http://$(hostname -I | awk '{print $1}'):9847"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo -e "${BLUE}  ____       ____  _            ___"
    echo " |  _ \ ___ |  _ \| | _____  __/ _ \ _ __"
    echo " | |_) / _ \| |_) | |/ _ \ \/ / | | | '_ \\"
    echo " |  _ <  __/|  __/| |  __/>  <| |_| | | | |"
    echo -e " |_| \_\___||_|   |_|\___/_/\_\\\\\___/|_| |_|${NC}"
    echo ""
    echo "  Installer"
    echo ""

    check_os
    check_root
    install_system_deps
    create_app_directory
    setup_venv
    configure_env
    install_backup_scripts
    setup_crontab
    install_systemd_service
    initialize_app
    print_summary
}

main
