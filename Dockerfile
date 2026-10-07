FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="RePlexOn" \
      org.opencontainers.image.description="Plex backup + monitoring dashboard" \
      org.opencontainers.image.source="https://github.com/wickedhardflip/replexon" \
      org.opencontainers.image.licenses="MIT"

# rsync/sqlite3/bc: backup script. curl: optional "pause Plex" mode (docker.sock API).
# gosu: drop from root to PUID/PGID in the entrypoint.
RUN apt-get update && apt-get install -y --no-install-recommends \
        rsync sqlite3 bc curl iputils-ping tini gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
COPY replexon.py .
COPY docker/entrypoint.sh docker/healthcheck.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh scripts/*.sh \
    && mkdir -p /data/logs /backups

# Container defaults; everything user-facing is set in the web UI.
ENV DATA_DIR=/data \
    BACKUP_LOG_PATH=/data/logs/plex-backup.log \
    BACKUP_SCRIPT_PATH=/app/scripts/backup-plex.sh \
    PLEX_DATA_PATH=/plex \
    BACKUP_DIR=/backups \
    PUID=1000 \
    PGID=1000 \
    PYTHONUNBUFFERED=1

EXPOSE 9847
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9847"]
