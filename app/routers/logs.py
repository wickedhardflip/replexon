"""Log viewer routes: filterable backup history."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DBSession

from app.dependencies import get_current_user, get_db
from app.models.backup import BackupRun
from app.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    backup_type: str = Query(default=""),
    status: str = Query(default=""),
    search: str = Query(default=""),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Backup log history page with filters."""
    per_page = 25
    query = db.query(BackupRun)

    if backup_type:
        query = query.filter(BackupRun.backup_type == backup_type)
    if status:
        query = query.filter(BackupRun.status == status)
    if search:
        query = query.filter(BackupRun.raw_log.contains(search))

    total = query.count()
    backups = (
        query.order_by(BackupRun.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    ctx = {
        "request": request,
        "user": user,
        "active_page": "logs",
        "backups": backups,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "backup_type": backup_type,
        "status_filter": status,
        "search": search,
    }

    # HTMX partial: only return the table + pagination
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("components/log_table.html", ctx)

    return templates.TemplateResponse("pages/logs.html", ctx)


@router.get("/logs/{backup_id}", response_class=HTMLResponse)
async def backup_detail(
    request: Request,
    backup_id: int,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Single backup run detail view."""
    backup = db.query(BackupRun).filter(BackupRun.id == backup_id).first()
    if not backup:
        return templates.TemplateResponse(
            "pages/error.html",
            {"request": request, "status_code": 404, "message": "Backup not found"},
            status_code=404,
        )

    return templates.TemplateResponse(
        "pages/backup_detail.html",
        {
            "request": request,
            "user": user,
            "active_page": "logs",
            "backup": backup,
        },
    )
