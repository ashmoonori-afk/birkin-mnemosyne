"""Consistency warnings reuse the read-only audit without weakening routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin_mnemosyne import MemoryIndex, MemoryIndexError, split_note
from birkin_mnemosyne.memory_index_integrity import check_index, consistency_warnings
from birkin_mnemosyne.startup import StartupReader


def test_warnings_report_every_alias_when_document_is_renamed(tmp_path: Path) -> None:
    # Given two distinct routes to one document that was renamed.
    document = tmp_path / "original.md"
    document.write_bytes(b"Complete rules.")
    index = MemoryIndex(tmp_path)
    index.register("release", document.name)
    original = index.register("deploy", document.name)
    document.rename(tmp_path / "renamed.md")
    before = {p.relative_to(tmp_path): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}

    # When the enabled-index warning hook audits current disk state.
    warnings = consistency_warnings(index)

    # Then both aliases remain and the new path needs its own route.
    checked = check_index(tmp_path)
    assert checked.dangling_entries == original.entries
    assert checked.orphan_documents == ("renamed.md",)
    assert len(checked.warnings) == 3
    for entry, warning in zip(original.entries, checked.warnings):
        assert repr(entry.trigger) in warning
        assert repr(entry.document) in warning
    assert repr("renamed.md") in checked.warnings[-1]
    assert len(warnings) == 2
    assert index.read().entries == original.entries
    assert {p.relative_to(tmp_path): p.read_bytes()
            for p in tmp_path.rglob("*") if p.is_file()} == before


def test_warnings_ignore_internal_and_transient_files_when_scanning(tmp_path: Path) -> None:
    # Given an enabled route plus visible notes and excluded storage.
    (tmp_path / "registered.md").write_bytes(b"Registered.")
    index = MemoryIndex(tmp_path)
    index.register("registered", "registered.md")
    for relative in (
        "root.md", "knowledge/note.md", ".hidden.md",
        ".mnemosyne-reviews/captured.md", ".trash/deleted.md",
        "_archive/old.md", "knowledge/.temporary.md",
        "knowledge/_archive/old.md", "knowledge/nested/deep.md",
        "knowledge/note.md.tmp", "knowledge/source.snapshot", "data.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Not all files are active Markdown notes.")
    (tmp_path / "linked.md").symlink_to(tmp_path / "root.md")
    (tmp_path / "linked-zone").symlink_to(tmp_path / "knowledge", target_is_directory=True)

    # When the existing lint audit scans the vault.
    checked = check_index(tmp_path)

    # Then visible regular Markdown notes at every supported path depth are candidates.
    assert checked.orphan_documents == (
        "knowledge/nested/deep.md", "knowledge/note.md", "root.md",
    )
    assert checked.documents == 4
    assert len(checked.warnings) == 3


def test_warnings_ignore_managed_sources_when_split_receipt_is_valid(tmp_path: Path) -> None:
    # Given a split source replaced by a verified routing notice.
    (tmp_path / "source.md").write_bytes(b"# Rules\n\n## Deploy\nKeep approvals.\n")
    split_note(tmp_path, "source.md", apply=True)

    # When consistency is checked through the startup integration hook.
    warnings = consistency_warnings(MemoryIndex(tmp_path))

    # Then the managed source does not require a redundant INDEX entry.
    assert warnings == ()


def test_warnings_stay_disabled_when_vault_has_no_index(tmp_path: Path) -> None:
    # Given a legacy vault with an unindexed document.
    (tmp_path / "legacy.md").write_bytes(b"Legacy note.")
    before = tuple(tmp_path.iterdir())

    # When the startup integration hook checks for warnings.
    warnings = consistency_warnings(MemoryIndex(tmp_path))

    # Then opt-in behavior is preserved without creating state.
    assert warnings == ()
    assert tuple(tmp_path.iterdir()) == before


def test_warnings_preserve_required_guard_when_marker_is_missing(tmp_path: Path) -> None:
    # Given a reader that requires INDEX state across restarts.
    index = MemoryIndex(tmp_path, required=True)

    # When consistency is checked, then missing state still fails loudly.
    with pytest.raises(MemoryIndexError):
        consistency_warnings(index)


@pytest.mark.parametrize("damage", ["missing", "invalid-encoding"])
def test_complete_reads_fail_when_warned_target_cannot_read(
    tmp_path: Path, damage: str,
) -> None:
    # Given an enabled route whose body cannot be read completely.
    document = tmp_path / "deploy.md"
    document.write_bytes(b"Keep approvals.")
    index = MemoryIndex(tmp_path)
    index.register("deploy", document.name)
    if damage == "missing":
        document.unlink()
    else:
        document.write_bytes(b"\xff")
    assert consistency_warnings(index)

    # When a complete task read selects that route, then it cannot succeed.
    with pytest.raises((OSError, UnicodeError, MemoryIndexError)):
        StartupReader(tmp_path).read([], task="deploy")


def test_warnings_include_integrity_errors_when_index_is_malformed(tmp_path: Path) -> None:
    # Given enabled but malformed authoritative state.
    (tmp_path / "note.md").write_bytes(b"Rules.")
    index = MemoryIndex(tmp_path)
    index.register("rules", "note.md")
    index.path.write_bytes(b"{invalid")

    # When the lint path audits the vault.
    checked = check_index(tmp_path)

    # Then malformed state is a reported error, not silent empty success.
    assert checked.errors
    assert len(checked.warnings) == 1
    assert not checked.ok


def test_startup_warning_count_is_bounded_when_many_documents_are_unindexed(
    tmp_path: Path,
) -> None:
    # Given one registered document and many independent unindexed notes.
    (tmp_path / "registered.md").write_bytes(b"Registered.")
    index = MemoryIndex(tmp_path)
    index.register("registered", "registered.md")
    for number in range(30):
        (tmp_path / f"orphan-{number}.md").write_bytes(b"Unindexed.")

    # When the startup hook summarizes drift.
    warnings = consistency_warnings(index)

    # Then startup is compact but lint retains every orphan.
    assert len(warnings) == 1
    checked = check_index(tmp_path)
    assert len(checked.orphan_documents) == 30
    assert len(checked.warnings) == 30


def test_startup_read_and_verify_surface_drift_without_dropping_routes(tmp_path: Path) -> None:
    document = tmp_path / "old.md"
    document.write_bytes(b"Complete rules.")
    index = MemoryIndex(tmp_path)
    original = index.register("release", document.name)
    document.rename(tmp_path / "renamed.md")
    orphan = tmp_path / "rules" / "nested" / "orphan.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"Unindexed rules.")
    reader = StartupReader(tmp_path)

    result = reader.read([], task="arithmetic")
    verification = reader.verify(result.context, [], task="arithmetic")

    assert result.coverage.complete and verification.complete
    assert result.coverage.warnings == verification.warnings == consistency_warnings(index)
    assert len(verification.warnings) == 2
    assert index.read().entries == original.entries
    assert check_index(tmp_path).orphan_documents == ("renamed.md", "rules/nested/orphan.md")


def test_cached_startup_context_reports_fresh_unindexed_document_warning(tmp_path: Path) -> None:
    (tmp_path / "registered.md").write_bytes(b"Rules.")
    index = MemoryIndex(tmp_path)
    index.register("registered", "registered.md")
    reader = StartupReader(tmp_path)
    before = reader.read([])
    assert before.coverage.warnings == ()
    (tmp_path / "unindexed.md").write_bytes(b"New rules.")

    after = reader.read([])

    assert after.cache_hit and after.context == before.context
    assert after.coverage.warnings == consistency_warnings(index)
    assert len(after.coverage.warnings) == 1
    verification = reader.verify(before.context, [])
    assert verification.complete and verification.warnings == after.coverage.warnings
