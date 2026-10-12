"""Cross-platform archive and discovery boundaries for nested vault paths."""

from pathlib import Path
import subprocess
import sys

import pytest

from birkin_mnemosyne.mnemosyne import Mnemosyne, normalize_zone
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.onboarding_notes import inventory
from birkin_mnemosyne.vault_paths import archived_zone


@pytest.mark.parametrize("zone", ["_ARCHIVE/sub", "work/_ArChIvE"])
def test_new_note_zone_rejects_case_variant_archive_components(zone: str) -> None:
    with pytest.raises(ValueError, match="archive"):
        normalize_zone(zone)
    assert normalize_zone(zone, allow_archive=True) == zone


@pytest.mark.parametrize(
    ("zone", "expected"),
    [("_ARCHIVE/sub", True), ("work/_ArChIvE", True), ("work/_archived", False)],
)
def test_archive_components_are_case_insensitive(zone: str, expected: bool) -> None:
    assert archived_zone(zone) is expected


@pytest.mark.parametrize("zone", ["_ARCHIVE/sub", "work/_ArChIvE"])
def test_default_search_excludes_case_variant_archives(
    tmp_path: Path, zone: str,
) -> None:
    archived = tmp_path / zone / "retired.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("quartz retired fixture", encoding="utf-8")
    engine = Mnemosyne(tmp_path)
    assert engine.search("quartz") == []
    assert [hit["slug"] for hit in engine.search("quartz", include_archive=True)] == [
        "retired",
    ]


@pytest.mark.parametrize("zone", ["_ARCHIVE/sub", "work/_ArChIvE"])
def test_inventory_and_index_exclude_case_variant_archives(
    tmp_path: Path, zone: str,
) -> None:
    archived = tmp_path / zone / "retired.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("retired fixture", encoding="utf-8")
    assert inventory(tmp_path) == ()
    assert check_index(tmp_path).documents == 0
    with pytest.raises(MemoryIndexError, match="unsafe document path"):
        MemoryIndex(tmp_path).document_path(f"{zone}/retired.md")


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows junction")
def test_recursive_scan_does_not_follow_windows_junction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.md").write_text("outside fixture", encoding="utf-8")
    junction = vault / "linked"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        check=True, capture_output=True, text=True,
    )
    try:
        assert Mnemosyne(vault).entries() == {}
        assert check_index(vault).documents == 0
        with pytest.raises(MemoryIndexError, match="refusing linked source"):
            inventory(vault)
    finally:
        junction.rmdir()
