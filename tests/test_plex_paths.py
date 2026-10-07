"""Plex data folder detection for linuxserver, plexinc, native and direct mounts."""
from app.services import plex_paths

INNER = "Library/Application Support/Plex Media Server"


def make_plex(root, with_db=True, with_prefs=True):
    root.mkdir(parents=True, exist_ok=True)
    if with_prefs:
        (root / "Preferences.xml").write_text("<Preferences/>")
    dbs = root / "Plug-in Support" / "Databases"
    dbs.mkdir(parents=True, exist_ok=True)
    if with_db:
        (dbs / "com.plexapp.plugins.library.db").write_bytes(b"x" * 100)
    (root / "Metadata").mkdir(exist_ok=True)
    (root / "Metadata" / "poster.jpg").write_bytes(b"y" * 1000)
    (root / "Cache").mkdir(exist_ok=True)
    return root


def test_docker_layout_config_mounted_at_plex(tmp_path):
    # linuxserver/plex and plexinc/pms-docker: host config dir mounted at /plex
    make_plex(tmp_path / "plex" / INNER)
    assert plex_paths.resolve(str(tmp_path / "plex")) == tmp_path / "plex" / INNER


def test_inner_folder_mounted_directly(tmp_path):
    make_plex(tmp_path / "plex")
    assert plex_paths.resolve(str(tmp_path / "plex")) == tmp_path / "plex"


def test_native_layouts_detected_with_labels(tmp_path):
    make_plex(tmp_path / "var-lib" / INNER)
    make_plex(tmp_path / "snap")
    found = plex_paths.detect([
        (str(tmp_path / "missing"), "Docker mount (/plex)"),
        (str(tmp_path / "var-lib"), "Native (deb/rpm)"),
        (str(tmp_path / "snap"), "Native (snap)"),
    ])
    assert [f["label"] for f in found] == ["Native (deb/rpm)", "Native (snap)"]
    assert found[0]["path"].endswith("Plex Media Server")


def test_not_plex(tmp_path):
    (tmp_path / "random").mkdir()
    assert plex_paths.resolve(str(tmp_path / "random")) is None
    result = plex_paths.validate(str(tmp_path / "random"))
    assert not result["ok"] and "No Plex data" in result["problems"][0]


def test_validate_ok_lists_databases(tmp_path):
    make_plex(tmp_path / "plex" / INNER)
    result = plex_paths.validate(str(tmp_path / "plex"))
    assert result["ok"] and result["databases"] == ["com.plexapp.plugins.library.db"]
    assert result["path"].endswith("Plex Media Server")


def test_validate_flags_missing_databases(tmp_path):
    make_plex(tmp_path / "plex", with_db=False)
    result = plex_paths.validate(str(tmp_path / "plex"))
    assert not result["ok"] and "No .db files" in " ".join(result["problems"])


def test_validate_empty():
    assert not plex_paths.validate("")["ok"]


def test_item_sizes(tmp_path):
    make_plex(tmp_path / "plex")
    sizes = plex_paths.item_sizes(str(tmp_path / "plex"))
    assert sizes["databases"] == 100 and sizes["metadata"] == 1000 and sizes["plugins"] == 0
    assert sizes["preferences"] == len("<Preferences/>")
