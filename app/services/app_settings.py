"""UI-editable settings (AppSetting table): defaults, encrypted secrets, and the backup script's env.

Secrets (SMTP and rsync passwords) are stored encrypted with a key derived from SECRET_KEY.
They are never put in a settings dict, a log line, or a template; read them with get_secret().
"""

import base64
import hashlib
import logging
import os
from typing import Dict

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models.setting import AppSetting

logger = logging.getLogger("replexon")

SECRET_KEYS = {"smtp_password", "rsync_password"}
_ENC_PREFIX = "enc:v1:"

# What can be backed up. Databases are always included; Cache/Logs/etc. never are.
BACKUP_ITEMS = {
    "databases": "Databases (library, watch history, settings)",
    "preferences": "Preferences.xml (server identity and settings)",
    "plugins": "Plug-ins, scanners and their data",
    "metadata": "Metadata and media artwork (large)",
}
PRESETS = {
    "essential": "databases,preferences",
    "standard": "databases,preferences,plugins",
    "full": "databases,preferences,plugins,metadata",
}
DB_SAFETY_MODES = ("safe_copy", "pause_container")
NOTIFY_MODES = ("failure", "success", "both", "never")
TLS_MODES = ("starttls", "ssl", "none")


def defaults() -> Dict[str, str]:
    return {
        "setup_complete": "",
        "plex_data_path": settings.plex_data_path,
        "backup_items": PRESETS["standard"],
        "dest_mode": settings.backup_mode if settings.backup_mode in ("local", "nas") else "local",
        "backup_dir": settings.backup_dir,
        "nas_host": "",
        "rsync_user": "",
        "rsync_module": "",
        "snapshot_keep_count": str(settings.snapshot_keep_count),
        "db_safety": "safe_copy",
        "plex_container": "plex",
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_tls": "starttls",
        "smtp_user": "",
        "smtp_from": "",
        "email_recipient": "",
        "notify_on": "failure",
    }


def get_setting(db: DBSession, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def set_setting(db: DBSession, key: str, value: str) -> None:
    if key in SECRET_KEYS:
        raise ValueError("use set_secret() for secret settings")
    _write(db, key, value)


def _write(db: DBSession, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def get_config(db: DBSession) -> Dict[str, str]:
    """All non-secret settings, DB value first, default second."""
    cfg = defaults()
    rows = db.query(AppSetting).filter(AppSetting.key.in_(list(cfg))).all()
    for row in rows:
        cfg[row.key] = row.value
    # Older installs stored TLS as on/off.
    cfg["smtp_tls"] = {"on": "starttls", "off": "none"}.get(cfg["smtp_tls"], cfg["smtp_tls"])
    return cfg


def selected_items(cfg: Dict[str, str]) -> list:
    items = [i for i in cfg.get("backup_items", "").split(",") if i in BACKUP_ITEMS]
    if "databases" not in items:
        items.insert(0, "databases")
    return items


# ---------- secrets ----------

def _fernet() -> Fernet:
    digest = hashlib.sha256(b"replexon-settings-v1:" + settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def set_secret(db: DBSession, key: str, value: str) -> None:
    """Store a secret encrypted. An empty value clears it."""
    if key not in SECRET_KEYS:
        raise ValueError(f"not a secret setting: {key}")
    token = _ENC_PREFIX + _fernet().encrypt(value.encode()).decode() if value else ""
    _write(db, key, token)


def get_secret(db: DBSession, key: str) -> str:
    raw = get_setting(db, key)
    if not raw:
        return ""
    if not raw.startswith(_ENC_PREFIX):
        logger.warning("Setting %s is not encrypted; re-enter it in Settings", key)
        return ""
    try:
        return _fernet().decrypt(raw[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        logger.warning("Cannot decrypt setting %s (SECRET_KEY changed?); re-enter it in Settings", key)
        return ""


def has_secret(db: DBSession, key: str) -> bool:
    return bool(get_setting(db, key))


# ---------- derived values ----------

def destination_display(cfg: Dict[str, str]) -> str:
    if cfg["dest_mode"] == "nas":
        return f"rsync://{cfg['rsync_user']}@{cfg['nas_host']}/{cfg['rsync_module']}"
    return cfg["backup_dir"]


def sync_destination(db: DBSession) -> None:
    """Keep the legacy backup_destination string (dashboard, NAS health) in step."""
    _write(db, "backup_destination", destination_display(get_config(db)))


def script_env(db: DBSession) -> Dict[str, str]:
    """Environment for scripts/backup-plex.sh and cleanup-snapshots.sh."""
    cfg = get_config(db)
    env = dict(os.environ)
    env.update({
        "REPLEXON_MANAGED": "1",
        "PLEX_DATA": cfg["plex_data_path"],
        "BACKUP_MODE": cfg["dest_mode"],
        "BACKUP_DIR": cfg["backup_dir"],
        "NAS_IP": cfg["nas_host"],
        "RSYNC_USER": cfg["rsync_user"],
        "RSYNC_MODULE": cfg["rsync_module"],
        "BACKUP_LOG_PATH": settings.backup_log_path,
        "SNAPSHOT_DIR": settings.snapshot_dir,
        "SNAPSHOT_KEEP_COUNT": cfg["snapshot_keep_count"],
        "BACKUP_ITEMS": ",".join(selected_items(cfg)),
        "DB_SAFETY": cfg["db_safety"],
        "PLEX_CONTAINER": cfg["plex_container"],
        "SCRATCH_DIR": settings.scratch_dir,
    })
    rsync_password = get_secret(db, "rsync_password")
    if rsync_password:
        env["RSYNC_PASSWORD"] = rsync_password  # rsync reads this itself; never on a command line
    else:
        env["RSYNC_PASSWORD_FILE"] = settings.rsync_password_file
    return env
