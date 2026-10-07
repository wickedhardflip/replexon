"""In-app backup scheduler: cron expressions stored in AppSetting, run in the container's TZ.

Replaces the root crontab. The background task in main.py calls check_and_run_due_jobs()
every minute; due jobs start through backup_runner (one job at a time).
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from croniter import croniter
from sqlalchemy.orm import Session as DBSession

from app.models.setting import AppSetting

logger = logging.getLogger("replexon.scheduler")

SCHEDULES_KEY = "backup_schedules"

# Presets offered in the wizard / Settings. "custom" means type a cron expression.
BACKUP_PRESETS = {
    "daily": ("Every day at 3:00 AM", "0 3 * * *"),
    "twice_daily": ("Twice a day (3:00 AM and 3:00 PM)", "0 3,15 * * *"),
    "weekly": ("Once a week (Sunday 3:00 AM)", "0 3 * * 0"),
}
CLEANUP_PRESETS = {
    "weekly": ("Every Sunday at 4:00 AM", "0 4 * * 0"),
    "monthly": ("1st of the month at 4:00 AM", "0 4 1 * *"),
}

DEFAULT_SCHEDULES = [
    {"id": "daily_backup", "label": "Plex Backup", "kind": "backup", "cron_expr": "0 3 * * *", "enabled": True},
    {"id": "weekly_cleanup", "label": "Snapshot Cleanup", "kind": "cleanup", "cron_expr": "0 4 * * 0", "enabled": True},
]

DAY_NAMES = {
    0: "Sundays", 1: "Mondays", 2: "Tuesdays", 3: "Wednesdays",
    4: "Thursdays", 5: "Fridays", 6: "Saturdays",
}


def valid_cron(expr: str) -> bool:
    return bool(expr) and len(expr.split()) == 5 and croniter.is_valid(expr)


def preset_for(expr: str, presets: dict) -> str:
    for key, (_label, cron) in presets.items():
        if cron == expr:
            return key
    return "custom"


@dataclass
class ScheduleEntry:
    id: str
    label: str
    kind: str
    cron_expr: str
    enabled: bool
    last_run: Optional[str] = None

    @property
    def schedule_display(self) -> str:
        try:
            minute, hour, dom, _month, dow = self.cron_expr.split()[:5]
            desc_parts = []
            if dow != "*":
                desc_parts.append(", ".join(DAY_NAMES.get(int(d) % 7, d) for d in dow.split(",")))
            elif dom != "*":
                desc_parts.append("1st of each month" if dom == "1" else f"Day {dom} of each month")
            else:
                desc_parts.append("Every day")
            if hour != "*":
                times = []
                for h in (int(x) for x in hour.split(",")):
                    h_display = h % 12 or 12
                    m = minute.zfill(2) if minute.isdigit() else "00"
                    times.append(f"{h_display}:{m} {'AM' if h < 12 else 'PM'}")
                desc_parts.append(" and ".join(times))
            return " at ".join(desc_parts)
        except (ValueError, IndexError):
            return self.cron_expr

    @property
    def next_run(self) -> Optional[str]:
        if not self.enabled or not valid_cron(self.cron_expr):
            return None
        return croniter(self.cron_expr, datetime.now()).get_next(datetime).isoformat()

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleEntry":
        return cls(
            id=data["id"],
            label=data.get("label", data["id"]),
            kind=data.get("kind", "cleanup" if "cleanup" in data["id"] else "backup"),
            cron_expr=data.get("cron_expr") or "",
            enabled=data.get("enabled", True),
            last_run=data.get("last_run"),
        )


def _read(db: DBSession) -> list:
    row = db.query(AppSetting).filter(AppSetting.key == SCHEDULES_KEY).first()
    if row and row.value:
        try:
            return json.loads(row.value)
        except json.JSONDecodeError:
            return []
    return []


def _write(db: DBSession, data: list) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == SCHEDULES_KEY).first()
    value = json.dumps(data)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=SCHEDULES_KEY, value=value))
    db.commit()


def initialize_schedules(db: DBSession) -> None:
    """Create the default jobs on first start (existing ones are left alone)."""
    raw = _read(db)
    known = {e.get("id") for e in raw}
    added = [dict(d) for d in DEFAULT_SCHEDULES if d["id"] not in known]
    if added:
        _write(db, raw + added)


def get_schedules(db: DBSession) -> List[ScheduleEntry]:
    return [ScheduleEntry.from_dict(d) for d in _read(db)]


def get_schedule(db: DBSession, schedule_id: str) -> Optional[ScheduleEntry]:
    return next((s for s in get_schedules(db) if s.id == schedule_id), None)


def update_schedule(db: DBSession, schedule_id: str, cron_expr: str, enabled: bool) -> bool:
    if not valid_cron(cron_expr):
        return False
    raw = _read(db)
    for entry in raw:
        if entry["id"] == schedule_id:
            entry["cron_expr"] = cron_expr
            entry["enabled"] = enabled
            entry["last_run"] = datetime.now().isoformat()  # count from now, no surprise catch-up run
            _write(db, raw)
            return True
    return False


def get_next_backup_time(db: DBSession) -> Optional[str]:
    times = [s.next_run for s in get_schedules(db) if s.kind == "backup" and s.next_run]
    return min(times) if times else None


def due_jobs(raw: list, now: datetime) -> list:
    """Ids of enabled jobs whose next fire time since last_run has passed."""
    due = []
    for entry in raw:
        expr = entry.get("cron_expr") or ""
        if not entry.get("enabled", True) or not valid_cron(expr) or not entry.get("last_run"):
            continue
        last_run = datetime.fromisoformat(entry["last_run"])
        if croniter(expr, last_run).get_next(datetime) <= now:
            due.append(entry["id"])
    return due


def check_and_run_due_jobs(db: DBSession) -> None:
    from app.services.app_settings import get_setting
    from app.services.backup_runner import start_job

    raw = _read(db)
    now = datetime.now()
    changed = False

    for entry in raw:  # first sight of a job: start counting from now
        if not entry.get("last_run"):
            entry["last_run"] = now.isoformat()
            changed = True

    if get_setting(db, "setup_complete"):
        for job_id in due_jobs(raw, now):
            entry = next(e for e in raw if e["id"] == job_id)
            kind = entry.get("kind", "cleanup" if "cleanup" in job_id else "backup")
            result = start_job(db, kind, "scheduled")
            if isinstance(result, str):
                logger.warning("Scheduled job %s not started: %s", job_id, result)
                continue  # e.g. another job running: try again next minute
            logger.info("Started scheduled job %s (%s)", job_id, entry["cron_expr"])
            entry["last_run"] = now.isoformat()
            changed = True
            break  # one job at a time; the next due job starts on a later tick

    if changed:
        _write(db, raw)
