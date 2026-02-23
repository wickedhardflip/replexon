"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    secret_key: str = "change-me-to-a-random-string"
    app_name: str = "RePlexOn"
    app_host: str = "0.0.0.0"
    app_port: int = 9847
    debug: bool = False

    # Database
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'replexon.db'}"

    # Backup paths (server-side)
    backup_log_path: str = "/var/log/plex-backup.log"
    backup_script_path: str = "/usr/local/bin/backup-plex.sh"
    backup_destination: str = ""
    plex_data_path: str = ""

    # Cron management
    cron_edit_enabled: bool = False
    cron_user: str = "root"

    # Log polling interval (seconds)
    log_poll_interval: int = 60

    # Manual backup rate limit (seconds)
    backup_cooldown: int = 300


settings = Settings()
