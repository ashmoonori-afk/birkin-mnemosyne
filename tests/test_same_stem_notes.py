"""Same-stem notes in different folders are all indexed and searchable."""

from __future__ import annotations

import os
from pathlib import Path

from birkin_mnemosyne.mnemosyne import Mnemosyne, path_key


def _write(vault: Path, rel: str, text: str, mtime: float) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_every_same_stem_card_is_indexed(tmp_path: Path) -> None:
    _write(tmp_path, "people/alice/card.md", "alice gardener\n", 100)
    _write(tmp_path, "people/bob/card.md", "bob astronomer\n", 200)
    _write(tmp_path, "card.md", "root card cartographer\n", 50)
    eng = Mnemosyne(tmp_path)
    entries = eng.entries()
    assert entries["card"]["rel"] == "people/bob/card.md"
    assert entries["people/alice/card"]["rel"] == "people/alice/card.md"
    assert entries["./card"]["rel"] == "card.md"
    assert eng.search("gardener")[0]["rel"] == "people/alice/card.md"
    assert eng.search("cartographer")[0]["rel"] == "card.md"
    assert eng.resolve_rel("people/alice/card") == "people/alice/card.md"


def test_path_key_never_equals_a_stem() -> None:
    assert path_key("a/b/card.md") == "a/b/card"
    assert path_key("card.md") == "./card"


def test_note_written_updates_losing_path_and_rekeys_newest(tmp_path: Path) -> None:
    _write(tmp_path, "a/card.md", "first version\n", 100)
    _write(tmp_path, "b/card.md", "winner text\n", 200)
    eng = Mnemosyne(tmp_path)
    eng.refresh()
    loser = _write(tmp_path, "a/card.md", "edited zebra\n", 150)
    eng.note_written(loser)
    assert eng.search("zebra")[0]["rel"] == "a/card.md"
    assert eng.entries()["card"]["rel"] == "b/card.md"
    newest = _write(tmp_path, "a/card.md", "now newest walrus\n", 300)
    eng.note_written(newest)
    entries = eng.entries()
    assert entries["card"]["rel"] == "a/card.md"
    assert entries["b/card"]["rel"] == "b/card.md"
    assert eng.search("walrus")[0]["rel"] == "a/card.md"


def test_refresh_promotes_remaining_file_after_winner_is_deleted(tmp_path: Path) -> None:
    _write(tmp_path, "a/card.md", "remaining gardener\n", 100)
    winner = _write(tmp_path, "b/card.md", "newer astronomer\n", 200)
    eng = Mnemosyne(tmp_path, semantic=False)
    assert len(eng.entries()) == 2
    winner.unlink()
    eng.refresh()
    assert {key: entry["rel"] for key, entry in eng.entries().items()} == {
        "card": "a/card.md",
    }
    assert eng.search("gardener")[0]["rel"] == "a/card.md"
    assert eng.search("astronomer") == []


def test_refresh_tracks_renamed_same_stem_file_without_stale_key(tmp_path: Path) -> None:
    older = _write(tmp_path, "a/card.md", "gardener\n", 100)
    _write(tmp_path, "b/card.md", "astronomer\n", 200)
    eng = Mnemosyne(tmp_path, semantic=False)
    assert len(eng.entries()) == 2
    older.rename(tmp_path / "a/profile.md")
    eng.refresh()
    assert {key: entry["rel"] for key, entry in eng.entries().items()} == {
        "profile": "a/profile.md", "card": "b/card.md",
    }
    assert eng.search("gardener")[0]["rel"] == "a/profile.md"
