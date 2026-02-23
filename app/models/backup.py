"""Backup run model for tracking backup history."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # daily_mirror | snapshot | cleanup | script_backup | manual
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True
    )  # success | failure | running
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transferred_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    files_transferred: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(
        String(10), default="cron", nullable=False
    )  # cron | manual
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<BackupRun {self.backup_type} {self.status} {self.started_at}>"

    @property
    def duration_display(self) -> str:
        """Format duration as human-readable string."""
        if self.duration_seconds is None:
            return "-"
        total = int(self.duration_seconds)
        if total < 60:
            return f"{total}s"
        minutes, seconds = divmod(total, 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {seconds}s"

    @property
    def size_display(self) -> str:
        """Format total size as human-readable string."""
        if self.total_size_bytes is None:
            return "-"
        return _format_bytes(self.total_size_bytes)

    @property
    def transferred_display(self) -> str:
        """Format transferred bytes as human-readable string."""
        if self.transferred_bytes is None:
            return "-"
        return _format_bytes(self.transferred_bytes)


def _format_bytes(n: int) -> str:
    """Format byte count to human-readable size."""
    if abs(n) < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"
