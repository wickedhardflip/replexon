"""Settings routes: email config, paths, password change, about."""

from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.setting import AppSetting
from app.models.user import User
from app.services.auth_service import hash_password, verify_password
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Default SMTP settings (Gmail as example)
SMTP_DEFAULTS = {
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_from": "",
    "smtp_tls": "on",
    "email_recipient": "",
}


def _get_setting(db: DBSession, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def _set_setting(db: DBSession, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        row = AppSetting(key=key, value=value)
        db.add(row)
    db.commit()


def _try_read_msmtp() -> Dict[str, str]:
    """Try to read msmtp config as fallback defaults for first-time setup.

    This provides a nice experience on servers that already have msmtp
    configured -- the SMTP fields pre-populate with existing values.
    Returns empty dict if msmtp is not installed or not readable.
    """
    config = {}
    for msmtp_path in [Path.home() / ".msmtprc", Path("/etc/msmtprc")]:
        if msmtp_path.exists():
            try:
                for line in msmtp_path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        key, value = parts
                        if key.lower() in ("password", "passwordeval"):
                            continue
                        config[key.lower()] = value
            except PermissionError:
                pass
            break
    return config


def _get_smtp_settings(db: DBSession) -> Dict[str, str]:
    """Get SMTP settings from app_settings, falling back to msmtp config."""
    result = {}
    for key, default in SMTP_DEFAULTS.items():
        result[key] = _get_setting(db, key, "")
    # If nothing configured yet, try msmtp as initial defaults
    if not result["smtp_host"]:
        msmtp = _try_read_msmtp()
        if msmtp:
            result.setdefault("smtp_host", msmtp.get("host", ""))
            result.setdefault("smtp_port", msmtp.get("port", "587"))
            result.setdefault("smtp_from", msmtp.get("from", ""))
            result.setdefault("smtp_tls", msmtp.get("tls", "on"))
            if not result["email_recipient"]:
                result["email_recipient"] = msmtp.get("from", "")
            # Fill in any that were still blank
            for key in ("smtp_host", "smtp_port", "smtp_from", "smtp_tls"):
                if not result[key]:
                    result[key] = msmtp.get(key.replace("smtp_", ""), SMTP_DEFAULTS[key])
    return result


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Settings page."""
    smtp = _get_smtp_settings(db)
    backup_destination = _get_setting(db, "backup_destination", settings.backup_destination)
    plex_data_path = _get_setting(db, "plex_data_path", settings.plex_data_path)

    return templates.TemplateResponse(
        "pages/settings.html",
        {
            "request": request,
            "user": user,
            "active_page": "settings",
            "email_recipient": smtp["email_recipient"],
            "smtp_host": smtp["smtp_host"],
            "smtp_port": smtp["smtp_port"],
            "smtp_from": smtp["smtp_from"],
            "smtp_tls": smtp["smtp_tls"],
            "backup_log_path": settings.backup_log_path,
            "backup_script_path": settings.backup_script_path,
            "backup_destination": backup_destination,
            "plex_data_path": plex_data_path,
            "cron_edit_enabled": settings.cron_edit_enabled,
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/settings/email")
async def update_email_settings(
    request: Request,
    email_recipient: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update email notification recipient."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/settings", status_code=303)

    _set_setting(db, "email_recipient", email_recipient.strip())
    return RedirectResponse(url="/settings?success=Email+settings+updated", status_code=303)


@router.post("/settings/smtp")
async def update_smtp_settings(
    request: Request,
    smtp_host: str = Form(...),
    smtp_port: str = Form("587"),
    smtp_from: str = Form(...),
    smtp_tls: str = Form("off"),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update SMTP server settings (stored in app database)."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/settings", status_code=303)

    if not smtp_host.strip():
        return RedirectResponse(url="/settings?error=SMTP+host+is+required", status_code=303)
    if not smtp_from.strip() or "@" not in smtp_from:
        return RedirectResponse(url="/settings?error=Valid+from+address+is+required", status_code=303)

    _set_setting(db, "smtp_host", smtp_host.strip())
    _set_setting(db, "smtp_port", smtp_port.strip())
    _set_setting(db, "smtp_from", smtp_from.strip())
    _set_setting(db, "smtp_tls", smtp_tls.strip())
    return RedirectResponse(url="/settings?success=SMTP+settings+updated", status_code=303)


@router.post("/settings/backup-info")
async def update_backup_info(
    request: Request,
    backup_destination: str = Form(""),
    plex_data_path: str = Form(""),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update backup destination and Plex data path."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/settings", status_code=303)

    _set_setting(db, "backup_destination", backup_destination.strip())
    _set_setting(db, "plex_data_path", plex_data_path.strip())
    return RedirectResponse(url="/settings?success=Backup+info+updated", status_code=303)


@router.post("/settings/test-email")
async def test_email(
    request: Request,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Send a test email to verify configuration."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/settings", status_code=303)

    from app.services.email_service import send_test_email
    success, message = send_test_email(db)

    if success:
        return RedirectResponse(url="/settings?success=" + message.replace(" ", "+"), status_code=303)
    return RedirectResponse(url="/settings?error=" + message.replace(" ", "+"), status_code=303)


@router.post("/settings/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Change the current user's password."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/settings", status_code=303)

    if new_password != confirm_password:
        return RedirectResponse(url="/settings?error=Passwords+do+not+match", status_code=303)

    if len(new_password) < 8:
        return RedirectResponse(url="/settings?error=Password+must+be+at+least+8+characters", status_code=303)

    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(url="/settings?error=Current+password+is+incorrect", status_code=303)

    user.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(url="/settings?success=Password+changed", status_code=303)
