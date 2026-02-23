"""Dashboard route: main overview with stats, charts, and recent backups."""

import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.setting import AppSetting
from app.models.user import User
from app.services.metrics import (
    get_backup_type_counts,
    get_daily_sizes,
    get_dashboard_stats,
    get_recent_backups,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    days: int = Query(default=30, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Main dashboard page."""
    stats = get_dashboard_stats(db, days=days)
    type_counts = get_backup_type_counts(db, days=days)
    daily_sizes = get_daily_sizes(db, days=days)
    recent = get_recent_backups(db, limit=10)

    # Read backup paths from DB, falling back to config
    dest_row = db.query(AppSetting).filter(AppSetting.key == "backup_destination").first()
    backup_destination = dest_row.value if dest_row else settings.backup_destination
    path_row = db.query(AppSetting).filter(AppSetting.key == "plex_data_path").first()
    plex_data_path = path_row.value if path_row else settings.plex_data_path

    return templates.TemplateResponse(
        "pages/dashboard.html",
        {
            "request": request,
            "user": user,
            "active_page": "dashboard",
            "stats": stats,
            "type_counts_json": json.dumps(type_counts),
            "daily_sizes_json": json.dumps(daily_sizes),
            "recent_backups": recent,
            "selected_days": days,
            "backup_destination": backup_destination,
            "plex_data_path": plex_data_path,
        },
    )
