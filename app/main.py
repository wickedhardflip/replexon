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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    print(BANNER)

    Path("data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)

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

    # Start background log poller
    poll_task = asyncio.create_task(_poll_logs())

    yield

    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    from app.routers import auth, dashboard, logs, schedules, settings_router

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
            "pages/error.html",
            {"request": request, "status_code": 404, "message": "Page not found"},
            status_code=404,
        )

    return app


app = create_app()
