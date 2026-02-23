"""Parse plex-backup logs into BackupRun records.

The server has two data sources:
1. /var/log/plex-backup-tracking.log - lightweight daily results (YYYY-MM-DD:success|failed)
2. /var/log/plex-backup.log - full rsync output (15GB+, impractical to parse fully)

Strategy:
- Primary: Parse the tracking file for historical backup records
- Detail: For the most recent backup(s), read the tail of the main log
  to extract transfer stats (sent/received bytes, total size)
- The tracking file is the reliable source; the main log adds optional detail
"""

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.backup import BackupRun

# Patterns for the main log file
BACKUP_START_RE = re.compile(r"=== Plex Backup Started: (.+?) ===")
BACKUP_SUCCESS_RE = re.compile(r"=== Plex Backup Completed Successfully: (.+?) ===")
BACKUP_FAILED_RE = re.compile(r"=== Plex Backup FAILED with code (\d+): (.+?) ===")
CLEANUP_START_RE = re.compile(r"=== Plex Snapshot Cleanup - (.+?) ====")
SNAPSHOT_RE = re.compile(r"Sunday detected - creating weekly snapshot")
SENT_BYTES_RE = re.compile(r"sent ([\d,]+) bytes\s+received ([\d,]+) bytes")
TOTAL_SIZE_RE = re.compile(r"total size is ([\d,]+)\s+speedup is")

# Date format from the bash `date` command output
# e.g. "Mon Feb 23 03:13:23 AM EST 2026"
DATE_FORMATS = [
    "%a %b %d %I:%M:%S %p %Z %Y",
    "%a %b %d %H:%M:%S %Z %Y",
    "%a %b %d %I:%M:%S %p %Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def _parse_date(date_str: str) -> Optional[datetime]:
    """Try multiple date formats to parse a date string."""
    date_str = date_str.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _parse_comma_int(s: str) -> int:
    """Parse a comma-separated integer string like '24,265,611'."""
    return int(s.replace(",", ""))


def import_from_tracking_file(db: DBSession, tracking_path: str) -> int:
    """Import backup history from the lightweight tracking file.

    Format: YYYY-MM-DD:success|failed (one per line, last 30 days)
    These are daily backups that run at 3 AM via cron.
    """
    path = Path(tracking_path)
    if not path.exists():
        return 0

    count = 0
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        date_str, result = line.rsplit(":", 1)
        try:
            backup_date = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        except ValueError:
            continue

        # The backup runs at 3 AM
        started_at = backup_date.replace(hour=3, minute=0, second=0)
        status = "success" if result.strip() == "success" else "failure"

        # Check for Sunday = snapshot day
        is_sunday = started_at.weekday() == 6
        backup_type = "daily_mirror"

        # Skip if already exists
        existing = (
            db.query(BackupRun)
            .filter(
                BackupRun.started_at == started_at,
                BackupRun.backup_type == backup_type,
            )
            .first()
        )
        if existing:
            continue

        run = BackupRun(
            backup_type=backup_type,
            status=status,
            started_at=started_at,
            triggered_by="cron",
        )
        db.add(run)
        count += 1

        # If Sunday, also create a snapshot entry
        if is_sunday and status == "success":
            snap_existing = (
                db.query(BackupRun)
                .filter(
                    BackupRun.started_at == started_at,
                    BackupRun.backup_type == "snapshot",
                )
                .first()
            )
            if not snap_existing:
                snap = BackupRun(
                    backup_type="snapshot",
                    status="success",
                    started_at=started_at.replace(hour=3, minute=30),
                    triggered_by="cron",
                )
                db.add(snap)
                count += 1

            # Also a cleanup entry at 4 AM
            cleanup_existing = (
                db.query(BackupRun)
                .filter(
                    BackupRun.started_at == started_at.replace(hour=4),
                    BackupRun.backup_type == "cleanup",
                )
                .first()
            )
            if not cleanup_existing:
                cleanup = BackupRun(
                    backup_type="cleanup",
                    status="success",
                    started_at=started_at.replace(hour=4, minute=0),
                    triggered_by="cron",
                )
                db.add(cleanup)
                count += 1

    if count:
        db.commit()
    return count


def extract_stats_file(log_path: str) -> Optional[str]:
    """Extract marker/stats lines from the main log into a small cache file.

    Uses grep -F with multiple fixed-string patterns to quickly scan the
    15GB+ log file. The result is cached in the app's data directory.
    Returns the path to the extract file, or None on failure.
    """
    from app.config import BASE_DIR
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    extract_path = str(data_dir / "plex-backup-stats.txt")

    # Use grep with fixed strings piped through grep -E for speed.
    # grep -F is much faster than grep -E on large files.
    # We grep for lines containing any of our marker strings.
    try:
        result = subprocess.run(
            ["bash", "-c",
             f"grep -F -e '=== Plex Backup' -e 'total size is' -e 'sent ' '{log_path}' "
             f"| grep -E '=== Plex Backup (Started|Completed|FAILED)|sent .* bytes.*received|total size is .* speedup' "
             f"> '{extract_path}'"],
            capture_output=True, text=True, timeout=300,
        )
        # grep returns 1 if no matches - that's ok
        if result.returncode not in (0, 1):
            return None
        return extract_path
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def enrich_from_stats(db: DBSession, stats_path: str) -> int:
    """Read an extracted stats file and enrich backup records.

    The stats file contains just the marker lines from the main log,
    produced by extract_stats_file() or the import-logs CLI command.
    """
    path = Path(stats_path)
    if not path.exists():
        return 0

    text = path.read_text()
    if not text.strip():
        return 0

    # Parse all backup entries from the extracted lines
    entries = []  # type: List[Dict]
    current = {}  # type: Dict

    for line in text.splitlines():
        m = BACKUP_START_RE.search(line)
        if m:
            current = {"start": _parse_date(m.group(1))}
            continue

        if not current:
            continue

        m = SENT_BYTES_RE.search(line)
        if m:
            # Keep the last sent/total pair (Sunday has 2 rsync runs)
            current["sent"] = _parse_comma_int(m.group(1))

        m = TOTAL_SIZE_RE.search(line)
        if m:
            current["total_size"] = _parse_comma_int(m.group(1))

        m = BACKUP_SUCCESS_RE.search(line)
        if m:
            current["end"] = _parse_date(m.group(1))
            current["status"] = "success"
            entries.append(current)
            current = {}

        m = BACKUP_FAILED_RE.search(line)
        if m:
            current["end"] = _parse_date(m.group(2))
            current["status"] = "failure"
            entries.append(current)
            current = {}

    # Now enrich database records with the extracted data
    updated = 0
    for entry in entries:
        start = entry.get("start")
        if not start:
            continue

        # Find matching daily_mirror record for this date
        run = (
            db.query(BackupRun)
            .filter(
                BackupRun.backup_type == "daily_mirror",
                BackupRun.started_at >= start.replace(hour=0, minute=0),
                BackupRun.started_at <= start.replace(hour=23, minute=59),
            )
            .first()
        )
        if not run:
            continue

        changed = False
        total_size = entry.get("total_size")
        sent = entry.get("sent")
        end = entry.get("end")

        if total_size and not run.total_size_bytes:
            run.total_size_bytes = total_size
            changed = True
        if sent and not run.transferred_bytes:
            run.transferred_bytes = sent
            changed = True
        if start and end and not run.duration_seconds:
            run.duration_seconds = (end - start).total_seconds()
            run.finished_at = end
            changed = True
        if changed:
            updated += 1

    if updated:
        db.commit()
    return updated


def parse_full_log(db: DBSession, log_path: str) -> int:
    """Full import: use tracking file + enrich from extracted stats.

    This is the main entry point called on startup.
    Enrichment uses a pre-extracted stats file if available.
    """
    tracking_path = log_path.replace("plex-backup.log", "plex-backup-tracking.log")
    count = import_from_tracking_file(db, tracking_path)

    # Try enrichment from the stats extract file
    from app.config import BASE_DIR
    stats_path = str(BASE_DIR / "data" / "plex-backup-stats.txt")
    enrich_from_stats(db, stats_path)
    return count


def parse_incremental(db: DBSession, log_path: str) -> int:
    """Incremental update: re-read tracking file for new entries.

    Called periodically by the background poller.
    """
    tracking_path = log_path.replace("plex-backup.log", "plex-backup-tracking.log")
    count = import_from_tracking_file(db, tracking_path)

    # On new entries, re-extract and enrich
    if count:
        stats_path = extract_stats_file(log_path)
        if stats_path:
            enrich_from_stats(db, stats_path)
    return count
