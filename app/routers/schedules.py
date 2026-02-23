"""Schedule management routes: view and edit cron backup schedules."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.backup_runner import can_trigger_backup, trigger_backup
from app.services.cron_service import get_backup_cron_entries, update_cron_entry
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Display backup schedules from crontab."""
    entries = get_backup_cron_entries()
    can_run, cooldown_msg = can_trigger_backup()

    return templates.TemplateResponse(
        "pages/schedules.html",
        {
            "request": request,
            "user": user,
            "active_page": "schedules",
            "cron_entries": entries,
            "cron_edit_enabled": settings.cron_edit_enabled,
            "cron_user": settings.cron_user,
            "can_trigger": can_run,
            "cooldown_msg": cooldown_msg,
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/schedules/run-now")
async def run_backup_now(
    request: Request,
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Trigger a manual backup."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/schedules", status_code=303)

    result = trigger_backup(db)
    if isinstance(result, str):
        # Error message
        return RedirectResponse(url="/schedules?error=" + result, status_code=303)

    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/schedules/update")
async def update_schedule(
    request: Request,
    old_line: str = Form(...),
    new_line: str = Form(...),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
):
    """Update a cron schedule entry."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/schedules", status_code=303)

    if not settings.cron_edit_enabled:
        return RedirectResponse(url="/schedules?error=Cron+editing+disabled", status_code=303)

    success = update_cron_entry(old_line, new_line)
    if not success:
        return RedirectResponse(url="/schedules?error=Failed+to+update+crontab", status_code=303)

    return RedirectResponse(url="/schedules?success=Schedule+updated", status_code=303)
