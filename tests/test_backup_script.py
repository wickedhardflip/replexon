"""scripts/backup-plex.sh and cleanup-snapshots.sh, run for real with bash against fixture folders.

Needs Linux with bash, rsync, sqlite3 and bc (CI installs them); skipped elsewhere.
"""
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "scripts" / "backup-plex.sh"
CLEANUP = ROOT / "scripts" / "cleanup-snapshots.sh"
TOOLS = ("bash", "rsync", "sqlite3", "bc")

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not all(shutil.which(t) for t in TOOLS),
    reason="needs Linux with bash, rsync, sqlite3, bc",
)

DB_NAME = "com.plexapp.plugins.library.db"


@pytest.fixture
def plex(tmp_path):
    """A Plex data folder with a WAL-mode database that has un-checkpointed writes."""
    root = tmp_path / "plex"
    dbs = root / "Plug-in Support" / "Databases"
    dbs.mkdir(parents=True)
    (root / "Preferences.xml").write_text("<Preferences/>")
    for d in ("Cache", "Logs", "Metadata", "Plug-ins", "Media"):
        (root / d).mkdir()
        (root / d / "file.bin").write_text(d)
    conn = sqlite3.connect(dbs / DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE watched (title TEXT)")
    conn.executemany("INSERT INTO watched VALUES (?)", [(f"show {i}",) for i in range(500)])
    conn.commit()
    yield root, conn  # connection stays open, like a running Plex
    conn.close()


def run(script, tmp_path, extra_env=None, path_prefix=None):
    env = {
        "PATH": (f"{path_prefix}:" if path_prefix else "") + os.environ["PATH"],
        "HOME": str(tmp_path),
        "REPLEXON_MANAGED": "1",
        "PLEX_DATA": str(tmp_path / "plex"),
        "BACKUP_MODE": "local",
        "BACKUP_DIR": str(tmp_path / "backups"),
        "BACKUP_LOG_PATH": str(tmp_path / "logs" / "plex-backup.log"),
        "SCRATCH_DIR": str(tmp_path / "scratch"),
        "SNAPSHOT_KEEP_COUNT": "2",
    }
    (tmp_path / "backups").mkdir(exist_ok=True)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    env.update(extra_env or {})
    return subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=120)


def backed_up_rows(tmp_path):
    db = tmp_path / "backups" / "plex-current" / "Plug-in Support" / "Databases" / DB_NAME
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return conn.execute("SELECT count(*) FROM watched").fetchone()[0]
    finally:
        conn.close()


def test_safe_copy_backs_up_consistent_db_including_wal_writes(plex, tmp_path):
    r = run(BACKUP, tmp_path)
    assert r.returncode == 0, r.stdout
    assert "=== Plex Backup Started:" in r.stdout
    assert "--- Safe database snapshot: complete (1 databases" in r.stdout
    assert "=== Plex Backup Completed Successfully:" in r.stdout
    assert backed_up_rows(tmp_path) == 500  # rows that were only in the -wal made it
    dest = tmp_path / "backups" / "plex-current" / "Plug-in Support" / "Databases"
    assert not (dest / f"{DB_NAME}-wal").exists()  # single consolidated file, never live WAL
    log = (tmp_path / "logs" / "plex-backup.log").read_text()
    assert "=== Plex Backup Completed Successfully:" in log
    assert (tmp_path / "logs" / "plex-backup-tracking.log").read_text().strip().endswith(":success")
    assert not list((tmp_path / "scratch").iterdir())  # scratch cleaned up


@pytest.mark.parametrize("items,present,absent", [
    ("databases,preferences", ["Preferences.xml"], ["Metadata", "Plug-ins", "Media"]),
    ("databases,preferences,plugins", ["Plug-ins"], ["Metadata", "Media"]),
    ("databases,preferences,plugins,metadata", ["Metadata", "Media", "Plug-ins"], []),
    ("databases", [], ["Preferences.xml", "Metadata"]),
])
def test_item_presets_and_cache_never(plex, tmp_path, items, present, absent):
    r = run(BACKUP, tmp_path, {"BACKUP_ITEMS": items})
    assert r.returncode == 0, r.stdout
    current = tmp_path / "backups" / "plex-current"
    for name in present:
        assert (current / name).exists(), name
    for name in absent + ["Cache", "Logs"]:
        assert not (current / name).exists(), name


def test_unreadable_database_fails_red_with_no_live_fallback(plex, tmp_path):
    root, _conn = plex
    bad = root / "Plug-in Support" / "Databases" / "com.plexapp.plugins.library.blobs.db"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    r = run(BACKUP, tmp_path)
    assert r.returncode == 3, r.stdout
    assert "Plex database backup FAILED" in r.stdout
    assert "=== Plex Backup FAILED with code 3:" in r.stdout
    assert "Safe database snapshot: complete" not in r.stdout
    dest = tmp_path / "backups" / "plex-current" / "Plug-in Support" / "Databases"
    assert not (dest / bad.name).exists() and not (dest / DB_NAME).exists()  # nothing live copied
    assert (tmp_path / "backups" / "plex-current" / "Preferences.xml").exists()  # rest still mirrored
    assert (tmp_path / "logs" / "plex-backup-tracking.log").read_text().strip().endswith(":failed")


def test_wrong_plex_path_fails_early(tmp_path):
    r = run(BACKUP, tmp_path, {"PLEX_DATA": str(tmp_path / "nope")})
    assert r.returncode == 2
    assert "=== Plex Backup FAILED with code 2:" in r.stdout


def test_nas_mode_needs_its_settings(plex, tmp_path):
    r = run(BACKUP, tmp_path, {"BACKUP_MODE": "nas"})
    assert r.returncode == 1 and "=== Plex Backup FAILED with code 1:" in r.stdout


def _fake_curl(tmp_path, exit_code=0):
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    curl = bindir / "curl"
    curl.write_text(f'#!/bin/bash\necho "$@" >> "{tmp_path}/curl.log"\nexit {exit_code}\n')
    curl.chmod(0o755)
    return bindir


def _fake_socket(tmp_path):
    path = tmp_path / "docker.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    return s, path


def test_pause_mode_pauses_and_resumes_plex(plex, tmp_path):
    bindir = _fake_curl(tmp_path)
    sock, path = _fake_socket(tmp_path)
    try:
        r = run(BACKUP, tmp_path, {"DB_SAFETY": "pause_container", "PLEX_CONTAINER": "my-plex",
                                   "DOCKER_SOCK": str(path)}, path_prefix=bindir)
    finally:
        sock.close()
    assert r.returncode == 0, r.stdout
    calls = (tmp_path / "curl.log").read_text().splitlines()
    assert len(calls) == 2
    assert calls[0].endswith("/containers/my-plex/pause") and calls[1].endswith("/containers/my-plex/unpause")
    assert "Paused Plex container: my-plex" in r.stdout and "Resumed Plex container: my-plex" in r.stdout
    assert backed_up_rows(tmp_path) == 500


def test_pause_mode_without_socket_still_makes_a_safe_copy(plex, tmp_path):
    bindir = _fake_curl(tmp_path)
    r = run(BACKUP, tmp_path, {"DB_SAFETY": "pause_container", "DOCKER_SOCK": str(tmp_path / "none.sock")},
            path_prefix=bindir)
    assert r.returncode == 0, r.stdout
    assert "using safe copy without pausing" in r.stdout
    assert not (tmp_path / "curl.log").exists()


def test_pause_mode_resumes_even_when_the_copy_fails(plex, tmp_path):
    root, _ = plex
    (root / "Plug-in Support" / "Databases" / "broken.db").write_bytes(b"junk" * 100)
    bindir = _fake_curl(tmp_path)
    sock, path = _fake_socket(tmp_path)
    try:
        r = run(BACKUP, tmp_path, {"DB_SAFETY": "pause_container", "DOCKER_SOCK": str(path)}, path_prefix=bindir)
    finally:
        sock.close()
    assert r.returncode == 3
    assert (tmp_path / "curl.log").read_text().splitlines()[-1].endswith("/unpause")


def test_forced_snapshot_and_local_retention(plex, tmp_path):
    snaps = tmp_path / "backups" / "plex-snapshots"
    for d in ("2026-01-04", "2026-01-11", "2026-01-18"):
        (snaps / d).mkdir(parents=True)
    r = run(BACKUP, tmp_path, {"FORCE_SNAPSHOT": "1"})
    assert r.returncode == 0 and "Sunday detected - creating weekly snapshot" in r.stdout
    assert len(list(snaps.iterdir())) == 4

    r = run(CLEANUP, tmp_path)
    assert r.returncode == 0, r.stdout
    assert "=== Plex Snapshot Cleanup - " in r.stdout and " ====" in r.stdout
    left = sorted(p.name for p in snaps.iterdir())
    assert len(left) == 2 and "2026-01-04" not in left and "2026-01-11" not in left


def test_cleanup_rsync_delete_trick_removes_only_old_snapshots(tmp_path):
    """The NAS branch deletes with rsync filters; check the same filter against a local target."""
    target = tmp_path / "target"
    for d in ("2026-01-04", "2026-01-11", "keep-me"):
        (target / d).mkdir(parents=True)
        (target / d / "f").write_text("x")
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["rsync", "-r", "--delete", "--include=/2026-01-04/***", "--exclude=*",
                    f"{empty}/", f"{target}/"], check=True)
    assert sorted(p.name for p in target.iterdir()) == ["2026-01-11", "keep-me"]


def test_log_markers_match_the_parser(plex, tmp_path):
    from app.services.log_parser import parse_marker_lines
    r = run(BACKUP, tmp_path)
    entries = parse_marker_lines(r.stdout)
    assert entries and entries[-1]["status"] == "success" and entries[-1]["db_safe"] is True
