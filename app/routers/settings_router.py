"""Settings page (same forms as the setup wizard), test email, restore guide."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.services import timefmt
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.routers.setup import _back, form_context
from app.services.app_settings import get_config
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
timefmt.register(templates.env)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from app.services.email_service import get_recent_email_logs

    ctx = form_context(db)
    ctx.update({
        "request": request,
        "user": user,
        "active_page": "settings",
        "next_url": "/settings",
        "here_url": "/settings",
        "backup_log_path": settings.backup_log_path,
        "backup_script_path": settings.backup_script_path,
        "email_logs": get_recent_email_logs(db, limit=5),
    })
    return templates.TemplateResponse(request, "pages/settings.html", ctx)


@router.post("/settings/test-email")
async def test_email(
    request: Request,
    csrf_token: str = Form(...),
    next: str = Form("/settings"),
    here: str = Form(""),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Send a test email with the saved settings."""
    next = here or next  # come back to the form the button was on
    if not validate_csrf_token(csrf_token):
        return _back(next, error="Form expired, please try again")
    from app.services.email_service import send_test_email
    success, message = send_test_email(db)
    return _back(next, success=message) if success else _back(next, error=message)


@router.get("/restore", response_class=HTMLResponse)
async def restore_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Restore guide page."""
    cfg = get_config(db)
    if cfg["dest_mode"] == "nas":
        rsync_dest = f"{cfg['rsync_user']}@{cfg['nas_host']}::{cfg['rsync_module']}"
    else:
        rsync_dest = cfg["backup_dir"]

    return templates.TemplateResponse(
        request, "pages/restore.html",
        {
            "request": request,
            "user": user,
            "active_page": "restore",
            "rsync_dest": rsync_dest,
            "dest_mode": cfg["dest_mode"],
            "plex_data_path": cfg["plex_data_path"],
            "rsync_password_file": settings.rsync_password_file,
            "snapshot_dir": settings.snapshot_dir,
            "csrf_token": generate_csrf_token(),
        },
    )
