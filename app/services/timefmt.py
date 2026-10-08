"""Show stored times in the configured time zone.

Everything is stored as naive UTC (backup_runs.started_at etc.; an external collector reads those
columns as-is). This module is the one place that turns a stored UTC value into local time
(the `timezone` app setting) and formats it. The same functions are Jinja filters, so pages,
emails and the scheduler all agree.
"""

import os
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Optional, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

_zone: Optional[tzinfo] = None  # cached configured zone; set_zone() / reset() keep it current

When = Union[datetime, str, None]


# ---------- the configured zone ----------

def load_zone(name: str) -> Optional[tzinfo]:
    """ZoneInfo for an IANA name, or None if it is not one."""
    name = (name or "").strip()
    if not name or name.startswith(("/", ".")) or ".." in name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc if name == "UTC" else None  # no tz database at all (bare Windows)


def default_zone_name() -> str:
    """The container's TZ if it is a valid zone name, else UTC."""
    env = os.environ.get("TZ", "").lstrip(":")
    return env if load_zone(env) else "UTC"


def zone_name(tz: Optional[tzinfo] = None) -> str:
    tz = tz or zone()
    return getattr(tz, "key", None) or ("UTC" if tz is timezone.utc else str(tz))


@lru_cache(maxsize=1)
def zone_names() -> list:
    """Sorted IANA names for the Settings picker."""
    return sorted(n for n in available_timezones() if "/" in n or n == "UTC")


def set_zone(name: str) -> None:
    global _zone
    _zone = load_zone(name) or load_zone(default_zone_name())


def reset() -> None:
    """Forget the cached zone (tests, or after the settings table is replaced)."""
    global _zone
    _zone = None


def zone(db=None) -> tzinfo:
    """The configured zone. With a db session it is re-read from that database."""
    if db is not None or _zone is None:
        from app.services.app_settings import get_setting
        if db is not None:
            set_zone(get_setting(db, "timezone"))
        else:
            from app.database import SessionLocal
            session = SessionLocal()
            try:
                set_zone(get_setting(session, "timezone"))
            except Exception:  # table not created yet
                set_zone("")
            finally:
                session.close()
    return _zone


# ---------- conversion ----------

def as_utc(value: When) -> Optional[datetime]:
    """Aware UTC datetime from a stored value (naive = UTC) or an ISO string."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: When, tz: Optional[tzinfo] = None) -> Optional[datetime]:
    utc = as_utc(value)
    return utc.astimezone(tz or zone()) if utc else None


def to_utc_naive(local: datetime, tz: Optional[tzinfo] = None) -> datetime:
    """A wall-clock time in the configured zone (naive or aware) as naive UTC, the storage format."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=tz or zone())
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def now_local(tz: Optional[tzinfo] = None) -> datetime:
    return datetime.now(tz or zone())


def local_day(value: When, tz: Optional[tzinfo] = None) -> Optional[date]:
    local = to_local(value, tz)
    return local.date() if local else None


def day_start_utc(day: date, tz: Optional[tzinfo] = None) -> datetime:
    """Naive UTC instant at which a local calendar day starts (for queries on stored columns)."""
    return to_utc_naive(datetime.combine(day, time.min), tz)


def day_bounds_utc(day: date, tz: Optional[tzinfo] = None) -> Tuple[datetime, datetime]:
    """[start, end) of a local day in naive UTC. Handles 23/25-hour DST days."""
    return day_start_utc(day, tz), day_start_utc(day + timedelta(days=1), tz)


def since_days_utc(days: int, tz: Optional[tzinfo] = None) -> datetime:
    """Start of the window "last N days" = local midnight N-1 days ago (today counts), naive UTC."""
    return day_start_utc(now_local(tz).date() - timedelta(days=days - 1), tz)


def iso_utc(value: When) -> str:
    """ISO string with a Z, for JavaScript (new Date() never has to guess)."""
    utc = as_utc(value)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ") if utc else ""


# ---------- formatting (one date, one time, one date-time format) ----------

def _date(d) -> str:
    return f"{d:%b} {d.day}, {d.year}"            # Oct 8, 2026


def _time(d) -> str:
    return f"{d.hour % 12 or 12}:{d:%M} {d:%p}"   # 3:00 AM


def fmt_date(value: Union[When, date]) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return _date(value)
    local = to_local(value)
    return _date(local) if local else "-"


def fmt_time(value: When) -> str:
    local = to_local(value)
    return _time(local) if local else "-"


def fmt_datetime(value: When) -> str:
    local = to_local(value)
    return f"{_date(local)}, {_time(local)}" if local else "-"


def fmt_time_range(start: When, end: When) -> str:
    """3:00 AM – 3:15 AM; a single time when there is no end or it is the same minute."""
    a, b = fmt_time(start), fmt_time(end)
    return a if not end or a == b else f"{a} – {b}"


def register(env) -> None:
    """Jinja filters/globals: {{ run.started_at | datetime }}, {{ tz_name() }}."""
    env.filters.update({
        "date": fmt_date, "time": fmt_time, "datetime": fmt_datetime,
        "timerange": fmt_time_range, "iso_utc": iso_utc,
    })
    env.globals.update({"tz_name": lambda: zone_name()})
