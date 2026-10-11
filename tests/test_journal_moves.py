"""Pure-move journal races and checked inverse moves against real files."""

from __future__ import annotations

import errno
import json
import os
import stat
from pathlib import Path

import pytest

from birkin_mnemosyne import journal_moves, review_journal
from birkin_mnemosyne.review_journal import Change, ReviewError, commit, undo_receipt

ORIGINAL = b"---\ntitle: Original\ntype: topic\n---\nORIGINAL_SOURCE\n"
ARRIVAL = b"---\ntitle: Arrival\ntype: topic\n---\nLATE_OWNER_EDIT\n"

def images(vault: Path):
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*.md")}


def snapshot_files(vault: Path):
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*") if p.is_file()
            and any(".sources" in part for part in p.parts)}


def journal(vault: Path) -> dict[str, object]:
    return json.loads(next((vault / ".mnemosyne-reviews").glob("*.json")
                           ).read_text("utf-8"))


def journal_id(vault: Path) -> str:
    transaction_id = journal(vault)["transaction_id"]
    assert isinstance(transaction_id, str)
    return transaction_id


def move_change() -> Change:
    return Change("note.md", "_archive/note.md", ORIGINAL, ORIGINAL)


def seed(vault: Path) -> tuple[Path, Path]:
    source = vault / "note.md"
    target = vault / "_archive" / "note.md"
    source.write_bytes(ORIGINAL)
    target.parent.mkdir()
    return source, target


def after_prepared_save(monkeypatch, vault, mutate) -> None:
    """Inject one deterministic external edit right after the prepared save."""
    real_save = review_journal._save

    def observed_save(path, manifest):
        real_save(path, manifest)
        if manifest["state"] == "prepared":
            mutate(vault)

    monkeypatch.setattr(review_journal, "_save", observed_save)


def test_move_keeps_source_mode_and_retains_captured_source(tmp_path):
    source, target = seed(tmp_path)
    source.chmod(0o640)
    expected_mode = stat.S_IMODE(source.stat().st_mode)
    before = images(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert receipt.state == "committed"
    assert stat.S_IMODE(target.stat().st_mode) == expected_mode
    assert not source.exists()
    assert target.read_bytes() == ORIGINAL
    captured = list((tmp_path / ".mnemosyne-reviews").rglob("source.snapshot"))
    assert len(captured) == 1
    assert captured[0].read_bytes() == ORIGINAL
    restored = undo_receipt(tmp_path, receipt.transaction_id)
    assert restored.state == "undone"
    assert images(tmp_path) == before
    assert not (tmp_path / "_archive" / "note.md").exists()


def test_forward_target_arrival_stays_untouched_and_requires_recovery(tmp_path, monkeypatch):
    source, target = seed(tmp_path)
    inode: dict[str, int | None] = {"value": None}

    def mutate(vault):
        target.write_bytes(ARRIVAL)
        inode["value"] = target.stat().st_ino

    after_prepared_save(monkeypatch, tmp_path, mutate)
    with pytest.raises(ReviewError, match="recovery required"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert inode["value"] is not None
    assert source.read_bytes() == ORIGINAL
    assert target.read_bytes() == ARRIVAL
    assert target.stat().st_ino == inode["value"]
    assert journal(tmp_path)["state"] == "recovery-required"
    with pytest.raises(ReviewError, match="post-image"):
        undo_receipt(tmp_path, journal_id(tmp_path))
    assert source.read_bytes() == ORIGINAL
    assert target.read_bytes() == ARRIVAL
    assert target.stat().st_ino == inode["value"]


def test_forward_target_arrival_with_identical_bytes_is_not_overwritten(
    tmp_path, monkeypatch,
):
    source, target = seed(tmp_path)
    inode: dict[str, int | None] = {"value": None}
    before = images(tmp_path)

    def mutate(vault):
        target.write_bytes(ORIGINAL)
        inode["value"] = target.stat().st_ino

    after_prepared_save(monkeypatch, tmp_path, mutate)
    with pytest.raises(ReviewError, match="recovery required"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert inode["value"] is not None
    assert source.read_bytes() == ORIGINAL
    assert target.read_bytes() == ORIGINAL
    assert target.stat().st_ino == inode["value"]
    assert images(tmp_path) == {**before, "_archive/note.md": ORIGINAL}
    assert journal(tmp_path)["state"] == "recovery-required"


def test_forward_source_edit_is_retained_and_not_committed(tmp_path, monkeypatch):
    source, _target = seed(tmp_path)

    def mutate(vault):
        source.write_bytes(ARRIVAL)

    after_prepared_save(monkeypatch, tmp_path, mutate)
    with pytest.raises(ReviewError, match="recovery required"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    files = snapshot_files(tmp_path)
    assert journal(tmp_path)["state"] == "recovery-required"
    assert ARRIVAL in files.values(), "the late source edit must be retained"
    assert images(tmp_path)["_archive/note.md"] == ORIGINAL
    with pytest.raises(ReviewError, match="captured source changed"):
        undo_receipt(tmp_path, journal_id(tmp_path))
    assert snapshot_files(tmp_path) == files


def test_undo_source_arrival_after_prevalidation_is_preserved(tmp_path, monkeypatch):
    source, target = seed(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    real_restore = review_journal._restore

    def restore_with_arrival(vault, changes, captures):
        source.write_bytes(ARRIVAL)
        real_restore(vault, changes, captures)

    with monkeypatch.context() as injected:
        injected.setattr(review_journal, "_restore", restore_with_arrival)
        with pytest.raises(ReviewError, match="recovery required"):
            undo_receipt(tmp_path, receipt.transaction_id)
    assert source.read_bytes() == ARRIVAL, "the arrival owns the original path"
    assert target.read_bytes() == ORIGINAL, "the archive was not retracted"
    assert journal(tmp_path)["state"] == "recovery-required"
    with pytest.raises(ReviewError, match="post-image"):
        undo_receipt(tmp_path, receipt.transaction_id)
    assert source.read_bytes() == ARRIVAL
    assert target.read_bytes() == ORIGINAL


def test_interrupted_publication_rolls_back_without_touching_target(tmp_path, monkeypatch):
    source, target = seed(tmp_path)
    real_create = journal_moves.atomic_create_bytes

    def failing_create(destination, data, **kwargs):
        if destination == target:
            raise OSError(errno.EIO, "injected public target failure")
        return real_create(destination, data, **kwargs)

    monkeypatch.setattr(journal_moves, "atomic_create_bytes", failing_create)
    with pytest.raises(ReviewError, match="rolled back"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert journal(tmp_path)["state"] == "rolled-back"
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()


def test_interrupted_capture_rolls_back_and_retains_published_target(
    tmp_path, monkeypatch,
):
    source, target = seed(tmp_path)
    real_rename = os.rename

    def failing_rename(src, dst, *args, **kwargs):
        if os.fspath(src) == os.fspath(source):
            raise OSError(errno.EACCES, "injected source capture failure")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", failing_rename)
    with pytest.raises(ReviewError, match="rolled back"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert journal(tmp_path)["state"] == "rolled-back"
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()
    retained = list((tmp_path / ".mnemosyne-reviews").rglob("target.snapshot"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == ORIGINAL


def test_no_hardlink_partial_move_publication_stays_recovery_required(
    tmp_path, monkeypatch,
):
    source, target = seed(tmp_path)

    def no_link(src, dst, *args, **kwargs):
        raise OSError(errno.EPERM, "hard links not supported", str(dst))

    real_write = os.write
    partial = {"fired": False}

    def failing_write(fd, data):
        if not partial["fired"] and target.exists():
            partial["fired"] = True
            real_write(fd, data[:3])
            raise OSError(errno.EIO, "injected partial exclusive copy")
        return real_write(fd, data)

    monkeypatch.setattr(os, "link", no_link)
    monkeypatch.setattr(os, "write", failing_write)
    with pytest.raises(ReviewError, match="recovery required"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert partial["fired"]
    assert journal(tmp_path)["state"] == "recovery-required"
    assert source.read_bytes() == ORIGINAL
    assert target.read_bytes() == ORIGINAL[:3]
    with pytest.raises(ReviewError, match="post-image"):
        undo_receipt(tmp_path, journal_id(tmp_path))
    assert source.read_bytes() == ORIGINAL


def test_undo_retry_after_interrupted_target_detachment_finishes_restoration(
    tmp_path, monkeypatch,
):
    source, target = seed(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    real_rename = os.rename

    def failing_rename(source_path, destination, *args, **kwargs):
        if Path(source_path) == target:
            raise PermissionError("injected archive detachment failure")
        return real_rename(source_path, destination, *args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(os, "rename", failing_rename)
        with pytest.raises(ReviewError, match="recovery required"):
            undo_receipt(tmp_path, receipt.transaction_id)
    assert journal(tmp_path)["state"] == "recovery-required"
    assert source.read_bytes() == ORIGINAL
    assert target.read_bytes() == ORIGINAL
    retained = list((tmp_path / ".mnemosyne-reviews").rglob("source.snapshot"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == ORIGINAL
    restored = undo_receipt(tmp_path, receipt.transaction_id)
    assert restored.state == "undone"
    assert images(tmp_path) == {move_change().source: ORIGINAL}
    assert not target.exists()


def test_undo_retry_after_final_save_failure_recognizes_intact_source(
    tmp_path, monkeypatch,
):
    source, target = seed(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    real_save = review_journal._save
    tripped = {"fired": False}

    def failing_save(path, manifest):
        if manifest["state"] == "undone" and not tripped["fired"]:
            tripped["fired"] = True
            raise OSError("injected terminal journal write failure")
        real_save(path, manifest)

    monkeypatch.setattr(review_journal, "_save", failing_save)
    with pytest.raises(ReviewError, match="recovery required"):
        undo_receipt(tmp_path, receipt.transaction_id)
    assert tripped["fired"]
    assert journal(tmp_path)["state"] == "recovery-required"
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()
    retained = list((tmp_path / ".mnemosyne-reviews").rglob("target.snapshot"))
    assert len(retained) == 1
    assert retained[0].read_bytes() == ORIGINAL
    restored = undo_receipt(tmp_path, receipt.transaction_id)
    assert restored.state == "undone"
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()


def test_undo_refuses_changed_retained_capture_before_any_write(tmp_path, monkeypatch):
    source, target = seed(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    real_save = review_journal._save

    def failing_save(path, manifest):
        if manifest["state"] == "undone":
            raise OSError("injected terminal journal write failure")
        return real_save(path, manifest)

    with monkeypatch.context() as injected:
        injected.setattr(review_journal, "_save", failing_save)
        with pytest.raises(ReviewError, match="recovery required"):
            undo_receipt(tmp_path, receipt.transaction_id)
    retained = next((tmp_path / ".mnemosyne-reviews").rglob("target.snapshot"))
    retained.unlink()
    retained.write_bytes(b"tampered retained capture")
    journal_bytes = next((tmp_path / ".mnemosyne-reviews").glob("*.json")).read_bytes()
    with pytest.raises(ReviewError, match="captured archive changed"):
        undo_receipt(tmp_path, receipt.transaction_id)
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()
    assert retained.read_bytes() == b"tampered retained capture"
    assert next((tmp_path / ".mnemosyne-reviews").glob("*.json")).read_bytes() \
        == journal_bytes


def test_legacy_receipt_without_captures_is_still_undoable(tmp_path):
    source, target = seed(tmp_path)
    before = images(tmp_path)
    receipt = commit(tmp_path, "race", "retire", "", "", (move_change(),))
    captures = Path(tmp_path) / ".mnemosyne-reviews" / f"{receipt.transaction_id}.sources"
    for path in sorted(captures.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path != captures:
            path.rmdir()
    restored = undo_receipt(tmp_path, receipt.transaction_id)
    assert restored.state == "undone"
    assert images(tmp_path) == before
    assert source.read_bytes() == ORIGINAL
    assert not target.exists()


def test_prepared_manifest_failure_mutates_nothing(tmp_path, monkeypatch):
    source, target = seed(tmp_path)
    before = images(tmp_path)

    def failing_save(path, manifest):
        if manifest["state"] == "prepared":
            raise OSError("injected prepared journal write failure")

    monkeypatch.setattr(review_journal, "_save", failing_save)
    with pytest.raises(OSError, match="prepared"):
        commit(tmp_path, "race", "retire", "", "", (move_change(),))
    assert images(tmp_path) == before
    assert not target.exists()
    assert not (tmp_path / ".mnemosyne-reviews").exists()
