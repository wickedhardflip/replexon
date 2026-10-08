"""Schedules page: view the in-app schedules, run a backup now, and list snapshots."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.services import timefmt
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.routers.setup import _back
from app.services.backup_runner import can_trigger_backup, trigger_backup
from app.services.scheduler_service import get_schedules, update_schedule
from app.services.snapshot_service import get_cached_snapshots
from app.utils.security import generate_csrf_token, validate_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
timefmt.register(templates.env)


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    can_run, cooldown_msg = can_trigger_backup()
    return templates.TemplateResponse(
        request, "pages/schedules.html",
        {
            "request": request,
            "user": user,
            "active_page": "schedules",
            "schedules": get_schedules(db),
            "can_trigger": can_run,
            "cooldown_msg": cooldown_msg,
            "csrf_token": generate_csrf_token(),
            "snapshot_data": get_cached_snapshots(db),
        },
    )


@router.post("/schedules/run-now")
async def run_now(
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
        return _back("/schedules", error=result)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/schedules/update")
async def update_schedule_route(
    request: Request,
    schedule_id: str = Form(...),
    cron_expr: str = Form(...),
    enabled: str = Form("off"),
    csrf_token: str = Form(...),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Update one schedule's cron expression or enabled state."""
    if not validate_csrf_token(csrf_token):
        return RedirectResponse(url="/schedules", status_code=303)
    if not update_schedule(db, schedule_id, cron_expr.strip(), enabled == "on"):
        return _back("/schedules", error="Invalid cron expression or schedule not found")
    return _back("/schedules", success="Schedule updated")
