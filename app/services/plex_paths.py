"""Find and check the Plex Media Server data folder.

Docker images (linuxserver/plex and plexinc/pms-docker) both keep it at
<config>/Library/Application Support/Plex Media Server, so mounting the host's
Plex config folder at /plex gives /plex/Library/Application Support/Plex Media Server.
Some people mount the inner folder directly, so /plex itself is checked too.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

INNER = Path("Library") / "Application Support" / "Plex Media Server"

# (root to look in, label shown in the wizard)
CANDIDATES = [
    ("/plex", "Docker mount (/plex)"),
    ("/config", "Docker mount (/config)"),
    ("/var/lib/plexmediaserver", "Native (deb/rpm)"),
    ("/var/snap/plexmediaserver/common", "Native (snap)"),
    ("/opt/plexmediaserver", "Native (/opt)"),
    ("/volume1/PlexMediaServer/AppData/Plex Media Server", "Synology DSM 7"),
    ("/volume1/Plex", "Synology DSM 6"),
]

# Top-level folders, by backup item, for size estimates (mirrors scripts/backup-plex.sh).
ITEM_PATHS = {
    "databases": ["Plug-in Support/Databases"],
    "preferences": ["Preferences.xml"],
    "plugins": ["Plug-ins", "Scanners", "Plug-in Support/Data", "Plug-in Support/Preferences"],
    "metadata": ["Metadata", "Media", "Plug-in Support/Metadata Combination"],
}


def _looks_like_plex(path: Path) -> bool:
    return (path / "Preferences.xml").is_file() or (path / "Plug-in Support" / "Databases").is_dir()


def resolve(root: str) -> Optional[Path]:
    """Return the real Plex data folder at or under root, or None."""
    base = Path(root)
    for p in (base, base / INNER):
        try:
            if _looks_like_plex(p):
                return p
        except OSError:
            continue
    return None


def detect(candidates=None) -> List[Dict[str, str]]:
    """Every Plex data folder found among the known locations."""
    found, seen = [], set()
    for root, label in candidates or CANDIDATES:
        p = resolve(root)
        if p and str(p) not in seen:
            seen.add(str(p))
            found.append({"path": str(p), "label": label})
    return found


def validate(path: str) -> Dict:
    """Check a Plex data folder. Returns {ok, path, problems, databases}."""
    problems = []
    p = resolve(path) if path else None
    if not path:
        problems.append("No path given.")
    elif p is None:
        problems.append("No Plex data found here (looked for Preferences.xml and Plug-in Support/Databases).")
    dbs = []
    if p is not None:
        db_dir = p / "Plug-in Support" / "Databases"
        if not db_dir.is_dir():
            problems.append("Plug-in Support/Databases is missing.")
        elif not os.access(db_dir, os.R_OK | os.X_OK):
            problems.append("Databases folder is not readable. Match PUID/PGID to your Plex container.")
        else:
            dbs = sorted(f.name for f in db_dir.glob("*.db"))
            if not dbs:
                problems.append("No .db files in Plug-in Support/Databases.")
            unreadable = [n for n in dbs if not os.access(db_dir / n, os.R_OK)]
            if unreadable:
                problems.append("Cannot read: " + ", ".join(unreadable) + ". Match PUID/PGID to your Plex container.")
    return {"ok": not problems, "path": str(p) if p else path, "problems": problems, "databases": dbs}


def _du(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def item_sizes(plex_path: str) -> Dict[str, int]:
    """Bytes per backup item (walks the tree; Metadata can take a while)."""
    p = resolve(plex_path)
    if p is None:
        return {}
    return {item: sum(_du(p / rel) for rel in rels if (p / rel).exists()) for item, rels in ITEM_PATHS.items()}
