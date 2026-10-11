"""Late arrivals must survive the actual public-path detachment boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from birkin_mnemosyne import journal_moves
from birkin_mnemosyne.review_journal import Change, Receipt, ReviewError, commit, undo_receipt
from birkin_mnemosyne.vault_lock import VaultLock


def _moved_note(root: Path) -> tuple[Path, Path, bytes, Receipt]:
    source, target = root / "note.md", root / "_archive" / "note.md"
    original = b"---\ntype: topic\n---\nORIGINAL_NOTE\n"
    _ = source.write_bytes(original)
    with VaultLock(root).hold():
        receipt = commit(root, "boundary", "retire", "", "",
                         (Change("note.md", "_archive/note.md", original, original),))
    return source, target, original, receipt


def test_arrival_at_archive_detachment_is_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, target, _, receipt = _moved_note(tmp_path)
    arrival = b"LATE_OWNER_ARRIVAL\n"
    injected = False
    original_unlink, original_rename = Path.unlink, os.rename

    def arrive() -> None:
        nonlocal injected
        if not injected:
            incoming = tmp_path / "incoming"
            _ = incoming.write_bytes(arrival)
            _ = incoming.replace(target)
            injected = True

    def unlink_at_boundary(path: Path, missing_ok: bool = False) -> None:
        if path == target:
            arrive()
        original_unlink(path, missing_ok=missing_ok)

    def rename_at_boundary(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(source) == target:
            arrive()
        original_rename(source, destination)

    monkeypatch.setattr(Path, "unlink", unlink_at_boundary)
    monkeypatch.setattr(os, "rename", rename_at_boundary)
    with VaultLock(tmp_path).hold(), pytest.raises(ReviewError):
        _ = undo_receipt(tmp_path, receipt.transaction_id)

    assert injected
    assert any(path.read_bytes() == arrival for path in tmp_path.rglob("*") if path.is_file())
    manifest = json.loads((tmp_path / receipt.journal_path).read_text(encoding="utf-8"))
    assert manifest["state"] == "recovery-required"


def test_successful_undo_keeps_original_private_capture(tmp_path: Path) -> None:
    source, _, original, receipt = _moved_note(tmp_path)
    captures = (tmp_path / receipt.journal_path).with_suffix(".sources")
    saved = journal_moves.find_source_capture(captures, source)
    assert saved is not None

    with VaultLock(tmp_path).hold():
        _ = undo_receipt(tmp_path, receipt.transaction_id)

    assert saved.read_bytes() == original
    assert source.read_bytes() == original
