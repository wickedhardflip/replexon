"""Read and optionally modify crontab entries for backup schedules."""

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from app.config import settings


SCRIPT_LABELS = {
    "backup-plex": "Daily Plex Backup",
    "cleanup-plex": "Weekly Snapshot Cleanup",
    "backup-scripts": "Monthly Config Backup",
}


@dataclass
class CronEntry:
    minute: str
    hour: str
    dom: str  # day of month
    month: str
    dow: str  # day of week
    command: str
    raw_line: str

    @property
    def label(self) -> str:
        """Friendly name based on the script."""
        cmd_lower = self.command.lower()
        for key, label in SCRIPT_LABELS.items():
            if key in cmd_lower:
                return label
        return self.command.split("/")[-1] if "/" in self.command else self.command

    @property
    def schedule_display(self) -> str:
        """Human-readable schedule description."""
        parts = []
        if self.dow != "*":
            day_names = {
                "0": "Sundays", "1": "Mondays", "2": "Tuesdays", "3": "Wednesdays",
                "4": "Thursdays", "5": "Fridays", "6": "Saturdays", "7": "Sundays",
            }
            days = [day_names.get(d.strip(), d.strip()) for d in self.dow.split(",")]
            parts.append(", ".join(days))
        elif self.dom != "*":
            if self.dom == "1":
                parts.append("1st of each month")
            else:
                parts.append(f"Day {self.dom} of each month")
        else:
            parts.append("Every day")

        if self.hour != "*":
            h = int(self.hour)
            ampm = "AM" if h < 12 else "PM"
            h_display = h if h <= 12 else h - 12
            if h_display == 0:
                h_display = 12
            minute = self.minute.zfill(2) if self.minute != "*" else "00"
            parts.append(f"{h_display}:{minute} {ampm}")

        return " at ".join(parts) if parts else self.raw_line

    @property
    def cron_expression(self) -> str:
        return f"{self.minute} {self.hour} {self.dom} {self.month} {self.dow}"


def _read_crontab() -> str:
    """Read crontab for the configured user, using sudo if needed."""
    try:
        result = subprocess.run(
            ["sudo", "crontab", "-l", "-u", settings.cron_user],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def get_backup_cron_entries() -> List[CronEntry]:
    """Read crontab and return entries related to backup scripts."""
    text = _read_crontab()
    if not text:
        return []

    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        cmd = parts[5]
        if "backup" in cmd.lower() or "plex" in cmd.lower() or "cleanup" in cmd.lower():
            entries.append(CronEntry(
                minute=parts[0],
                hour=parts[1],
                dom=parts[2],
                month=parts[3],
                dow=parts[4],
                command=cmd,
                raw_line=line,
            ))

    return entries


def get_next_backup_time(entries: Optional[List[CronEntry]] = None) -> Optional[str]:
    """Calculate the next fire time for the daily backup cron entry.

    Returns ISO format string or None if no backup schedule found.
    Handles daily (0 3 * * *), weekly (0 4 * * 0), and monthly (0 5 1 * *).
    """
    if entries is None:
        entries = get_backup_cron_entries()

    if not entries:
        return None

    now = datetime.now()
    soonest = None

    for entry in entries:
        if entry.hour == "*" or entry.minute == "*":
            continue

        hour = int(entry.hour)
        minute = int(entry.minute)

        if entry.dom != "*":
            dom = int(entry.dom)
            candidate = now.replace(day=dom, hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                month = now.month + 1
                year = now.year
                if month > 12:
                    month = 1
                    year += 1
                candidate = candidate.replace(year=year, month=month)
        elif entry.dow != "*":
            target_dow = int(entry.dow) % 7
            current_dow = now.weekday()
            py_target = (target_dow - 1) % 7
            days_ahead = (py_target - current_dow) % 7
            candidate = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if candidate <= now:
                candidate += timedelta(days=7)
        else:
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)

        if soonest is None or candidate < soonest:
            soonest = candidate

    return soonest.isoformat() if soonest else None


def update_cron_entry(old_line: str, new_line: str) -> bool:
    """Replace a cron entry. Requires CRON_EDIT_ENABLED=true.

    Returns True on success.
    """
    if not settings.cron_edit_enabled:
        return False

    current = _read_crontab()
    if not current or old_line not in current:
        return False

    try:
        new_crontab = current.replace(old_line, new_line)
        proc = subprocess.run(
            ["sudo", "crontab", "-u", settings.cron_user, "-"],
            input=new_crontab, capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
