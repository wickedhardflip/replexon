"""Dashboard route: main overview with stats, charts, and recent backups."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.dependencies import get_current_user, get_db
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

    return templates.TemplateResponse(
        "pages/dashboard.html",
        {
            "request": request,
            "user": user,
            "active_page": "dashboard",
            "stats": stats,
            "type_counts": type_counts,
            "daily_sizes": daily_sizes,
            "recent_backups": recent,
            "selected_days": days,
        },
    )
