"""User-provided supported files are recognized without renaming their paths."""

from pathlib import Path

import pytest

from birkin_mnemosyne import Mnemosyne, VaultMemory
from birkin_mnemosyne.import_candidates import destination_name, scan_import
from birkin_mnemosyne.kibitzer import KibitzerAdapter
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.memory_index_migration import split_note
from birkin_mnemosyne.onboarding_notes import inventory

SOURCE = b"---\ntitle: Visible note\n---\n\n## Policy\nDeployment approval required.\n"


def test_hidden_zone_notes_stay_out_of_recall_and_fallback_reads(tmp_path: Path) -> None:
    # Given private dot files inside an otherwise visible zone.
    zone = tmp_path / "knowledge"
    zone.mkdir()
    (zone / ".private.md").write_bytes(SOURCE)

    # When the user searches or uses a cold title lookup.
    memory = VaultMemory({"vault_path": str(tmp_path)})
    text = memory.get_note("private")
    hits = Mnemosyne(tmp_path).search("Deployment approval")

    # Then hidden content is not promoted into ordinary memory.
    assert text is None
    assert hits == []


@pytest.mark.parametrize("relative", ["visible.MD", "knowledge/visible.Md"])
def test_recall_and_cold_reads_find_mixed_case_markdown(tmp_path: Path, relative: str) -> None:
    # Given a user-created Markdown path at a supported vault depth.
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(SOURCE)

    # When a fresh library client reads and searches the note.
    memory = VaultMemory({"vault_path": str(tmp_path)})
    text = memory.get_note("visible")
    hits = Mnemosyne(tmp_path).search("Deployment approval")

    # Then both paths retain the original filename and complete content.
    assert text is not None and "Deployment approval required." in text
    assert len(hits) == 1 and hits[0]["rel"] == relative
    assert path.read_bytes() == SOURCE


def test_onboarding_and_integrity_inventory_mixed_case_markdown(tmp_path: Path) -> None:
    # Given an active source and a hidden source with the same extension casing.
    (tmp_path / "visible.MD").write_bytes(SOURCE)
    (tmp_path / ".hidden.MD").write_bytes(SOURCE)

    # When onboarding and INDEX integrity inspect visible Markdown.
    sources = inventory(tmp_path)
    checked = check_index(tmp_path)

    # Then only the visible file is reported with its original bytes and spelling.
    assert [(source.path, source.raw) for source in sources] == [("visible.MD", SOURCE)]
    assert checked.orphan_documents == ("visible.MD",)


def test_kibitzer_reads_mixed_case_markdown(tmp_path: Path) -> None:
    # Given a source written outside Mnemosyne.
    (tmp_path / "visible.MD").write_bytes(SOURCE)

    # When the host asks for its live documents.
    documents = KibitzerAdapter(tmp_path).documents()

    # Then the document is delivered rather than silently omitted.
    assert len(documents) == 1
    assert "Deployment approval required." in documents[0].body


def test_split_preview_accepts_mixed_case_markdown_without_changes(tmp_path: Path) -> None:
    # Given a Markdown source whose extension was capitalized by an editor.
    source = tmp_path / "visible.MD"
    source.write_bytes(SOURCE)

    # When a user previews the normal lossless split.
    report = split_note(tmp_path, source.name)

    # Then every source byte is accounted for without renaming or editing the source.
    assert report.source == source.name and report.source_bytes == len(SOURCE)
    assert report.applied is False
    assert source.read_bytes() == SOURCE


@pytest.mark.parametrize(
    ("filename", "raw", "format_"),
    [("note.MD", SOURCE, "md"), ("export.TXT", b"verbatim text", "txt"),
     ("export.JsOn", b'{"value":"preserved"}', "json")],
)
def test_imports_recognize_case_without_losing_original_bytes(
    tmp_path: Path, filename: str, raw: bytes, format_: str,
) -> None:
    # Given a supported external file with user-chosen extension casing.
    source = tmp_path / filename
    source.write_bytes(raw)

    # When importing the file directly or selecting it through a directory.
    single = scan_import(source)
    directory = scan_import(tmp_path)

    # Then both selections describe the same lossless source.
    assert single == directory and len(single) == 1
    candidate = single[0]
    assert candidate.preimage == raw and candidate.format == format_
    assert candidate.relative == filename
    assert raw in candidate.raw
    assert destination_name(filename) == (filename if format_ == "md" else filename + ".md")
