"""First-run wizard, the shared settings forms it uses, and /health.

The wizard and the Settings page post the same forms to /settings/section/<name>;
a hidden `next` field decides where to go afterwards.
"""

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services import app_settings as aps
from app.services import plex_paths
from app.services.scheduler_service import (
    BACKUP_PRESETS, CLEANUP_PRESETS, get_schedule, initialize_schedules, preset_for, update_schedule, valid_cron,
)
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

STEPS = ["admin", "plex", "items", "destination", "schedule", "email", "done"]
STEP_TITLES = {
    "admin": "Admin account", "plex": "Plex location", "items": "What to back up",
    "destination": "Where backups go", "schedule": "When", "email": "Email", "done": "All aboard",
}
SECTIONS = ("plex", "items", "destination", "schedule", "email")


def _safe_next(next_url: str, default: str = "/settings") -> str:
    return next_url if next_url.startswith("/") and not next_url.startswith("//") else default


def _back(next_url: str, error: str = "", success: str = "") -> RedirectResponse:
    url = _safe_next(next_url)
    sep = "&" if "?" in url else "?"
    if error:
        url += f"{sep}error={quote_plus(error)}"
    elif success:
        url += f"{sep}success={quote_plus(success)}"
    return RedirectResponse(url=url, status_code=303)


def form_context(db: DBSession) -> dict:
    """Everything the shared settings forms need (no secret values, only whether one is set)."""
    cfg = aps.get_config(db)
    backup = get_schedule(db, "daily_backup")
    cleanup = get_schedule(db, "weekly_cleanup")
    backup_cron = backup.cron_expr if backup else BACKUP_PRESETS["daily"][1]
    cleanup_cron = cleanup.cron_expr if cleanup else CLEANUP_PRESETS["weekly"][1]
    return {
        "cfg": cfg,
        "items": aps.selected_items(cfg),
        "item_labels": aps.BACKUP_ITEMS,
        "presets": aps.PRESETS,
        "smtp_password_set": aps.has_secret(db, "smtp_password"),
        "rsync_password_set": aps.has_secret(db, "rsync_password"),
        "docker_sock": os.path.exists("/var/run/docker.sock"),
        "backup_presets": BACKUP_PRESETS,
        "cleanup_presets": CLEANUP_PRESETS,
        "backup_cron": backup_cron,
        "backup_preset": preset_for(backup_cron, BACKUP_PRESETS),
        "backup_enabled": backup.enabled if backup else True,
        "cleanup_cron": cleanup_cron,
        "cleanup_preset": preset_for(cleanup_cron, CLEANUP_PRESETS),
        "tz": os.environ.get("TZ", "the server's local time"),
        "csrf_token": generate_csrf_token(),
    }


# ---------- health ----------

@router.get("/health")
async def health(db: DBSession = Depends(get_db)):
    """Unauthenticated liveness check for Docker and reverse proxies."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error"}, status_code=503)
    return {"status": "ok"}


# ---------- wizard ----------

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, step: str = "", db: DBSession = Depends(get_db)):
    has_users = db.query(User).first() is not None
    if not has_users:
        step = "admin"
        user = None
    else:
        try:
            user = get_current_user(request, request.cookies.get("session_token"), db)
        except HTTPException:
            return RedirectResponse(url="/login", status_code=303)
        if step not in STEPS or step == "admin":
            step = "plex"

    ctx = form_context(db)
    if step == "plex":
        ctx["detected"] = plex_paths.detect()
        if not ctx["cfg"]["plex_data_path"] and ctx["detected"]:
            ctx["cfg"]["plex_data_path"] = ctx["detected"][0]["path"]
    idx = STEPS.index(step)
    ctx.update({
        "request": request, "user": user, "step": step, "steps": STEPS, "step_titles": STEP_TITLES,
        "step_index": idx,
        "next_url": f"/setup?step={STEPS[min(idx + 1, len(STEPS) - 1)]}",
        "here_url": f"/setup?step={step}",
        "prev_url": f"/setup?step={STEPS[idx - 1]}" if idx > 1 else "",
    })
    return templates.TemplateResponse(request, "pages/setup.html", ctx)


@router.post("/setup/admin")
async def setup_admin(
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: DBSession = Depends(get_db),
):
    """Create the first admin. Only works while no account exists."""
    if not validate_csrf_token(csrf_token):
        return _back("/setup", error="Form expired, please try again")
    if db.query(User).first() is not None:
        return RedirectResponse(url="/login", status_code=303)
    username = username.strip()
    if not username or len(password) < 8:
        return _back("/setup", error="Pick a username and a password of at least 8 characters")
    if password != password_confirm:
        return _back("/setup", error="Passwords do not match")

    from app.services.auth_service import create_session, hash_password
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    session = create_session(db, user)
    response = RedirectResponse(url="/setup?step=plex", status_code=303)
    response.set_cookie("session_token", session.id, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return response


@router.post("/setup/finish")
async def setup_finish(
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not validate_csrf_token(csrf_token):
        return _back("/setup?step=done", error="Form expired, please try again")
    aps.set_setting(db, "setup_complete", "1")
    return RedirectResponse(url="/dashboard?success=Setup+complete", status_code=303)


# ---------- Plex helpers ----------

@router.get("/api/plex-sizes", response_class=HTMLResponse)
async def plex_sizes(request: Request, user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Size per backup item (HTMX fragment). Walks the Plex folder, so only on request."""
    from app.models.backup import _format_bytes
    sizes = plex_paths.item_sizes(aps.get_config(db)["plex_data_path"])
    return templates.TemplateResponse(
        request, "components/plex_sizes.html",
        {"request": request, "sizes": {k: _format_bytes(v) for k, v in sizes.items()}, "labels": aps.BACKUP_ITEMS},
    )


# ---------- shared section forms ----------

@router.post("/settings/section/{section}")
async def save_section(
    section: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    form = await request.form()
    next_url = str(form.get("next", "/settings"))
    if not validate_csrf_token(str(form.get("csrf_token", ""))):
        return _back(next_url, error="Form expired, please try again")
    if section not in SECTIONS:
        return _back(next_url, error="Unknown settings section")

    error = SAVERS[section](db, form)
    if error:
        here = str(form.get("here", "")) or next_url
        return _back(here, error=error)
    return _back(next_url, success="Saved")


def _f(form, key: str, default: str = "") -> str:
    return str(form.get(key, default)).strip()


def _save_plex(db: DBSession, form) -> Optional[str]:
    path = _f(form, "plex_data_path")
    result = plex_paths.validate(path)
    if not result["ok"]:
        return " ".join(result["problems"])
    aps.set_setting(db, "plex_data_path", result["path"])
    return None


def _save_items(db: DBSession, form) -> Optional[str]:
    preset = _f(form, "preset")
    if preset in aps.PRESETS:
        items = aps.PRESETS[preset].split(",")
    else:
        items = [i for i in form.getlist("items") if i in aps.BACKUP_ITEMS]
    if "databases" not in items:
        items.insert(0, "databases")
    aps.set_setting(db, "backup_items", ",".join(i for i in aps.BACKUP_ITEMS if i in items))

    mode = _f(form, "db_safety", "safe_copy")
    if mode not in aps.DB_SAFETY_MODES:
        return "Unknown database safety mode"
    aps.set_setting(db, "db_safety", mode)
    container = _f(form, "plex_container", "plex")
    if not container.replace("-", "").replace("_", "").replace(".", "").isalnum():
        return "Plex container name can only use letters, numbers, - _ ."
    aps.set_setting(db, "plex_container", container)
    return None


def _save_destination(db: DBSession, form) -> Optional[str]:
    mode = _f(form, "dest_mode", "local")
    if mode not in ("local", "nas"):
        return "Pick a destination type"
    try:
        keep = int(_f(form, "snapshot_keep_count", "4"))
    except ValueError:
        keep = 0
    if not 1 <= keep <= 52:
        return "Keep between 1 and 52 weekly snapshots"

    if mode == "local":
        backup_dir = _f(form, "backup_dir")
        if not os.path.isabs(backup_dir):
            return "Backup folder must be an absolute path, e.g. /backups"
        plex = aps.get_config(db)["plex_data_path"]
        target = Path(backup_dir).resolve()
        if plex and (target == Path(plex).resolve() or Path(plex).resolve() in target.parents):
            return "Backup folder cannot be inside the Plex folder"
        if not Path(backup_dir).is_dir() or not os.access(backup_dir, os.W_OK):
            return f"{backup_dir} does not exist or is not writable by RePlexOn"
        aps.set_setting(db, "backup_dir", backup_dir)
    else:
        host, user, module = _f(form, "nas_host"), _f(form, "rsync_user"), _f(form, "rsync_module")
        if not (host and user and module):
            return "NAS needs an address, rsync user and module"
        for value in (host, user, module):
            if any(c in value for c in " @:/'\"`$;"):
                return "NAS address, user and module cannot contain spaces or @ : / quotes"
        aps.set_setting(db, "nas_host", host)
        aps.set_setting(db, "rsync_user", user)
        aps.set_setting(db, "rsync_module", module)
        password = str(form.get("rsync_password", ""))
        if password:
            aps.set_secret(db, "rsync_password", password)
        elif form.get("rsync_password_clear"):
            aps.set_secret(db, "rsync_password", "")

    aps.set_setting(db, "dest_mode", mode)
    aps.set_setting(db, "snapshot_keep_count", str(keep))
    aps.sync_destination(db)
    return None


def _save_schedule(db: DBSession, form) -> Optional[str]:
    def pick(prefix: str, presets: dict) -> str:
        preset = _f(form, f"{prefix}_preset")
        return presets[preset][1] if preset in presets else _f(form, f"{prefix}_cron")

    backup_cron = pick("backup", BACKUP_PRESETS)
    cleanup_cron = pick("cleanup", CLEANUP_PRESETS)
    if not valid_cron(backup_cron):
        return "Backup schedule is not a valid 5-field cron expression"
    if not valid_cron(cleanup_cron):
        return "Cleanup schedule is not a valid 5-field cron expression"
    enabled = form.get("backup_enabled") == "on"
    initialize_schedules(db)  # idempotent; makes sure both entries exist
    if not (update_schedule(db, "daily_backup", backup_cron, enabled)
            and update_schedule(db, "weekly_cleanup", cleanup_cron, enabled)):
        return "Could not save the schedule"
    return None


def _save_email(db: DBSession, form) -> Optional[str]:
    tls = _f(form, "smtp_tls", "starttls")
    notify = _f(form, "notify_on", "failure")
    if tls not in aps.TLS_MODES or notify not in aps.NOTIFY_MODES:
        return "Unknown email option"
    port = _f(form, "smtp_port", "587")
    if not port.isdigit():
        return "SMTP port must be a number"
    recipient, sender = _f(form, "email_recipient"), _f(form, "smtp_from")
    for addr in (recipient, sender):
        if addr and "@" not in addr:
            return "Email addresses need an @"
    for key, value in (("smtp_host", _f(form, "smtp_host")), ("smtp_port", port), ("smtp_tls", tls),
                       ("smtp_user", _f(form, "smtp_user")), ("smtp_from", sender),
                       ("email_recipient", recipient), ("notify_on", notify)):
        aps.set_setting(db, key, value)
    password = str(form.get("smtp_password", ""))
    if password:
        aps.set_secret(db, "smtp_password", password)
    elif form.get("smtp_password_clear"):
        aps.set_secret(db, "smtp_password", "")
    return None


SAVERS = {
    "plex": _save_plex,
    "items": _save_items,
    "destination": _save_destination,
    "schedule": _save_schedule,
    "email": _save_email,
}
