"""FastAPI application factory with middleware and lifespan."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import Base, SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("replexon")

BANNER = r"""
  ____       ____  _            ___
 |  _ \ ___ |  _ \| | _____  __/ _ \ _ __
 | |_) / _ \| |_) | |/ _ \ \/ / | | | '_ \
 |  _ <  __/|  __/| |  __/>  <| |_| | | | |
 |_| \_\___||_|   |_|\___/_/\_\\___/|_| |_|
 ==========================================
      "Previously on your Plex server..."
"""


async def _poll_logs():
    """Background task: poll backup log file for new entries."""
    from app.services.log_parser import parse_incremental
    from app.services.backup_runner import check_running_backup

    while True:
        try:
            await asyncio.sleep(settings.log_poll_interval)
            db = SessionLocal()
            try:
                count = parse_incremental(db, settings.backup_log_path)
                if count:
                    logger.info(f"Parsed {count} new backup entries from log")
                check_running_backup(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in log poll task")


async def _poll_nas_health():
    """Background task: check NAS reachability every 5 minutes."""
    from app.services.nas_health import check_nas_health

    while True:
        try:
            await asyncio.sleep(300)
            db = SessionLocal()
            try:
                check_nas_health(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in NAS health check")


async def _poll_snapshots():
    """Background task: enumerate snapshots every hour."""
    from app.services.snapshot_service import fetch_snapshots

    while True:
        try:
            await asyncio.sleep(3600)
            db = SessionLocal()
            try:
                fetch_snapshots(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in snapshot poll task")


async def _run_scheduler():
    """Background task: start scheduled jobs when due (checked every 60 seconds)."""
    from app.services.scheduler_service import check_and_run_due_jobs

    while True:
        try:
            await asyncio.sleep(60)
            db = SessionLocal()
            try:
                check_and_run_due_jobs(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in scheduler task")


def _startup_db_tasks(db) -> None:
    """Optional env admin, default schedules, and runs a restart interrupted."""
    from datetime import datetime, timezone
    from app.models.backup import BackupRun
    from app.models.user import User
    from app.services.scheduler_service import initialize_schedules

    if settings.admin_user and settings.admin_password and db.query(User).first() is None:
        from app.services.auth_service import hash_password
        db.add(User(username=settings.admin_user, password_hash=hash_password(settings.admin_password)))
        db.commit()
        logger.info("Created admin user from ADMIN_USER")

    initialize_schedules(db)

    stale = db.query(BackupRun).filter(BackupRun.status == "running").all()
    for run in stale:
        run.status = "failure"
        run.error_message = "Interrupted: RePlexOn restarted while this was running"
        run.finished_at = datetime.now(timezone.utc)
    if stale:
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    print(BANNER)

    Path(settings.data_dir, "logs").mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _startup_db_tasks(db)
    finally:
        db.close()

    # Initial log parse on startup
    try:
        from app.services.log_parser import parse_full_log
        db = SessionLocal()
        try:
            count = parse_full_log(db, settings.backup_log_path)
            if count:
                logger.info(f"Initial import: {count} backup records from log")
        finally:
            db.close()
    except Exception:
        logger.exception("Failed initial log import (non-fatal)")

    # Initial snapshot fetch on startup
    try:
        from app.services.snapshot_service import fetch_snapshots
        db = SessionLocal()
        try:
            fetch_snapshots(db)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed initial snapshot fetch (non-fatal)")

    # Start background tasks
    poll_task = asyncio.create_task(_poll_logs())
    nas_task = asyncio.create_task(_poll_nas_health())
    snap_task = asyncio.create_task(_poll_snapshots())
    sched_task = asyncio.create_task(_run_scheduler())

    yield

    for task in (poll_task, nas_task, snap_task, sched_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


SETUP_EXEMPT = ("/setup", "/static", "/health", "/login", "/logout", "/api/")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.middleware("http")
    async def first_run_redirect(request: Request, call_next):
        """Send people to the setup wizard until it has been finished."""
        path = request.url.path
        if request.method == "GET" and not path.startswith(SETUP_EXEMPT):
            from app.models.user import User
            from app.services.app_settings import get_setting
            db = SessionLocal()
            try:
                if db.query(User).first() is None:
                    return RedirectResponse(url="/setup", status_code=303)
                if not get_setting(db, "setup_complete") and request.cookies.get("session_token"):
                    return RedirectResponse(url="/setup?step=plex", status_code=303)
            finally:
                db.close()
        return await call_next(request)

    from app.routers import auth, dashboard, logs, schedules, settings_router, setup

    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(logs.router)
    app.include_router(schedules.router)
    app.include_router(settings_router.router)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/dashboard", status_code=303)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        templates = Jinja2Templates(directory="app/templates")
        return templates.TemplateResponse(
            request, "pages/error.html",
            {"request": request, "status_code": 404, "message": "Page not found"},
            status_code=404,
        )

    return app


app = create_app()
