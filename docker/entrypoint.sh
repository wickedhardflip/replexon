#!/bin/bash
# Runs as root only long enough to create the replexon user with the host's PUID/PGID
# (match the Plex container's user so the read-only Plex mount is readable), then drops to it.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    getent group replexon >/dev/null || groupadd -o -g "$PGID" replexon
    id replexon >/dev/null 2>&1 || useradd -o -u "$PUID" -g "$PGID" -d /app -s /bin/bash replexon
    # docker.sock (only for the optional "pause Plex" mode): join its group so curl can reach it.
    if [ -S /var/run/docker.sock ]; then
        SOCK_GID=$(stat -c %g /var/run/docker.sock)
        getent group "$SOCK_GID" >/dev/null || groupadd -o -g "$SOCK_GID" dockersock
        usermod -aG "$(getent group "$SOCK_GID" | cut -d: -f1)" replexon
    fi
    mkdir -p "${DATA_DIR:-/data}/logs"
    chown -R "$PUID:$PGID" "${DATA_DIR:-/data}"
    # Local backup target: own the top level only (never recurse through old backups).
    if [ -d /backups ]; then chown "$PUID:$PGID" /backups 2>/dev/null || true; fi
    exec gosu replexon "$0" "$@"
fi

echo ""
echo ' RePlexOn - "Previously on your Plex server..."'
echo ""
python3 replexon.py init-db >/dev/null 2>&1 || true
exec "$@"
