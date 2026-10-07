"""Bootstrap configuration from environment variables.

Everything user-facing (Plex location, destination, schedule, email, ...) lives in the
AppSetting table and is edited in the web UI; see app/services/app_settings.py.
The values here are start-up knobs and the defaults the setup wizard starts from.
"""

import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    secret_key: str = Field(default="", repr=False)
    app_name: str = "RePlexOn"
    app_host: str = "0.0.0.0"
    app_port: int = 9847
    debug: bool = False
    data_dir: str = str(BASE_DIR / "data")

    # Optional first-run admin (otherwise the setup wizard creates one)
    admin_user: str = ""
    admin_password: str = Field(default="", repr=False)

    # Single sign-on behind a reverse proxy (off unless set). See docs/configuration.md.
    trust_proxy_auth: bool = False
    proxy_auth_secret: str = Field(default="", repr=False)
    trusted_proxy_networks: str = "172.16.0.0/12"
    proxy_auth_user_map: str = ""
    proxy_auth_logout_url: str = ""  # where Sign out goes under single sign-on (the proxy's sign-out page)

    # Database (default: <data_dir>/replexon.db)
    database_url: str = ""

    # Backup script + its log
    backup_log_path: str = "/var/log/plex-backup.log"
    backup_script_path: str = str(BASE_DIR / "scripts" / "backup-plex.sh")
    # Run this instead of `bash <script>` when set, e.g. when the script is root-only:
    # BACKUP_COMMAND="sudo -n /usr/bin/systemctl start plex-backup-manual.service" (see native/README.md)
    backup_command: str = ""
    scratch_dir: str = "/tmp"

    # Defaults the setup wizard starts from
    backup_destination: str = ""
    plex_data_path: str = ""
    backup_mode: str = "local"
    backup_dir: str = "/backups"
    rsync_password_file: str = "/etc/replexon/rsync.secret"
    snapshot_dir: str = "plex-snapshots"
    snapshot_keep_count: int = 4

    # Log polling interval (seconds)
    log_poll_interval: int = 60

    # Manual backup rate limit (seconds)
    backup_cooldown: int = 300


def _load_or_create_secret_key(data_dir: Path) -> str:
    """Read DATA_DIR/.secret_key, creating it (chmod 600) on first start."""
    key_file = data_dir / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    import secrets
    key = secrets.token_hex(32)
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(key)
    return key


settings = Settings()

if not settings.database_url:
    settings.database_url = f"sqlite:///{Path(settings.data_dir) / 'replexon.db'}"

if not settings.secret_key or settings.secret_key == "change-me-to-a-random-string":
    try:
        settings.secret_key = _load_or_create_secret_key(Path(settings.data_dir))
    except OSError:
        print(
            "\n[SECURITY ERROR] SECRET_KEY is not set and DATA_DIR is not writable, so one cannot be generated.\n"
            "Set SECRET_KEY in the environment (python3 -c \"import secrets; print(secrets.token_hex(32))\")\n"
            "or make DATA_DIR writable.\n",
            file=sys.stderr,
        )
        sys.exit(1)
