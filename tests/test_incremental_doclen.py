"""Exact accounting and persisted-search parity through real vault mutations."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pytest

from birkin_mnemosyne import mnemosyne

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
QUERIES = ("orchard retention", "\uae40\uc7a5 \ubc30\ucd94",
           "\u8c5a\u9aa8\u30b9\u30fc\u30d7", "\u642c\u5bb6\u51c6\u5907",
           "orchard \ubc30\ucd94", "", "notfound")
Operation = Literal["insert", "edit", "delete", "external-insert", "external-edit",
                    "rezone", "reload", "rebuild", "empty-refresh", "empty-rebuild"]


class FullRecompute(mnemosyne.Mnemosyne):
    """Reference path: derive the average from all entries after each mutation."""

    def _adjust_doclen(self, old_length: int, new_length: int,
                       count_delta: int) -> None:
        pass

    def refresh(self) -> None:
        super().refresh()
        self._recompute_avgdl()

    def note_written(self, path: Path) -> None:
        super().note_written(path)
        self._recompute_avgdl()


def note(vault: Path, name: str, body: str) -> Path:
    path = vault / f"{name}.md"
    path.write_text(
        f"---\ntitle: {name}\ncreated: 2025-01-01\nupdated: 2025-01-01\n"
        f"tags: [orchard]\n---\n\n{body}\n", encoding="utf-8")
    os.utime(path, (1_750_000_000, 1_750_000_000))
    return path


def assert_accounting(engine: mnemosyne.Mnemosyne) -> None:
    """Inspect current state without triggering a repairing refresh."""
    assert engine._notes is not None
    total = sum(entry["doclen"] for entry in engine._notes.values())
    count = len(engine._notes)
    assert engine._total_doclen == total
    assert engine._doc_count == count
    assert engine._avgdl == (total / count if count else 0.0)


def mutate(engine: mnemosyne.Mnemosyne, operation: Operation) -> None:
    """Drive one mutation, using different sizes to force external detection."""
    vault = engine.vault
    match operation:
        case "insert":
            engine.note_written(note(vault, "c", QUERIES[2] + " retention " * 10))
        case "edit":
            engine.note_written(note(vault, "a", QUERIES[1] * 30))
        case "delete":
            (vault / "a.md").unlink()
            engine.refresh()
        case "external-insert":
            note(vault, "c", "orchard " * 20)
            engine.refresh()
        case "external-edit":
            note(vault, "a", "retention " * 40)
            engine.refresh()
        case "rezone":
            engine.rezone("a", "food")
        case "rebuild":
            engine.rebuild()
        case "empty-refresh" | "empty-rebuild":
            (vault / "a.md").unlink()
            (vault / "b.md").unlink()
            if operation == "empty-refresh":
                engine.refresh()
            else:
                engine.rebuild()
        case "reload":
            engine.refresh()
        case unreachable:
            raise AssertionError(unreachable)


@pytest.mark.parametrize("operation", [
    "insert", "edit", "delete", "external-insert", "external-edit",
    "rezone", "reload", "rebuild", "empty-refresh", "empty-rebuild",
])
def test_mutations_preserve_exact_search_and_cache(
        tmp_path: Path, operation: Operation) -> None:
    # Given: identical metadata in independent real vaults with mixed-script lengths.
    vaults = [tmp_path / "incremental", tmp_path / "reference"]
    for vault in vaults:
        vault.mkdir()
        note(vault, "a", " ".join(QUERIES[:4]))
        note(vault, "b", "retention")
    engine = mnemosyne.Mnemosyne(vaults[0], semantic=False)
    reference = FullRecompute(vaults[1], semantic=False)
    engine.rebuild()
    reference.rebuild()
    if operation == "reload":
        engine = mnemosyne.Mnemosyne(vaults[0], semantic=False)
        reference = FullRecompute(vaults[1], semantic=False)
    # When: the public mutation or cache reload completes.
    mutate(engine, operation)
    mutate(reference, operation)
    # Then: integer totals, all unrounded search fields and compressed bytes agree.
    assert_accounting(engine)
    assert engine._avgdl == reference._avgdl
    for query in QUERIES:
        assert json.dumps(engine.search(query, now=NOW), sort_keys=True) == json.dumps(
            reference.search(query, now=NOW), sort_keys=True)
    assert (vaults[0] / mnemosyne.INDEX_FILE).read_bytes() == (
        vaults[1] / mnemosyne.INDEX_FILE).read_bytes()


@pytest.mark.parametrize("targeted", [True, False])
def test_failed_parse_retains_entries_totals_and_cache(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, targeted: bool) -> None:
    # Given: a loaded entry followed by an unreadable replacement.
    path = note(tmp_path, "a", "orchard")
    engine = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    engine.rebuild()
    before = (engine._total_doclen, engine._doc_count, engine._avgdl,
              dict(engine._notes or {}), (tmp_path / mnemosyne.INDEX_FILE).read_bytes())
    note(tmp_path, "a", "retention " * 20)
    monkeypatch.setattr(mnemosyne, "_note_entry", lambda path, rel: None)
    # When: parsing fails in either public update path.
    if targeted:
        engine.note_written(path)
    else:
        engine.refresh()
    # Then: the previous index and its accounting remain intact.
    assert (engine._total_doclen, engine._doc_count, engine._avgdl,
            engine._notes, (tmp_path / mnemosyne.INDEX_FILE).read_bytes()) == before


def test_loaded_mutations_do_not_resum_all_lengths(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a loaded engine with the full-pass initialization guarded.
    note(tmp_path, "a", "orchard")
    engine = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    engine.rebuild()

    def forbidden() -> None:
        raise AssertionError("loaded mutation recomputed every document length")

    monkeypatch.setattr(engine, "_recompute_avgdl", forbidden)
    # When: successive writes and refresh removal mutate the index.
    engine.note_written(note(tmp_path, "a", "orchard retention " * 5))
    engine.note_written(note(tmp_path, "b", "orchard"))
    (tmp_path / "a.md").unlink()
    engine.refresh()
    # Then: persistence and search still work without the full pass.
    assert_accounting(engine)
    assert [hit["slug"] for hit in engine.search("orchard", now=NOW)] == ["b"]


def test_zero_length_note_counts_toward_average(tmp_path: Path) -> None:
    # Given: a single Han character contributes no BM25 document length.
    path = tmp_path / "zero.md"
    path.write_text("---\ntitle: \u8eca\n---\n\u8eca\n", encoding="utf-8")
    engine = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    engine.rebuild()
    # When: a nonzero-length entry is inserted.
    engine.note_written(note(tmp_path, "a", "orchard retention"))
    # Then: zero-length documents are counted, rather than ignored in the divisor.
    assert engine._notes is not None and engine._notes["zero"]["doclen"] == 0
    assert_accounting(engine)
    assert engine._doc_count == 2
