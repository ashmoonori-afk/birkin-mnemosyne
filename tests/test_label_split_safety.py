"""Receipt-bound split bytes survive label previews and checked application."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin_mnemosyne.labeling import plan_labels, run_labeling
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.memory_index_migration import SplitReport, split_note
from birkin_mnemosyne.review_journal import Manifest, ReviewError, undo_receipt

decode_manifest: Callable[[str], Manifest] = json.loads


def split_vault(root: Path, *, restored: bool = False) -> SplitReport:
    _ = (root / "policy.md").write_bytes(
        b"# Policy\r\nKeep approval.\r\n## Deploy\r\nKeep rollback."
    )
    split = split_note(root, "policy.md", apply=True)
    if restored:
        assert split.backup_journal is not None
        manifest = decode_manifest((root / split.backup_journal).read_text("utf-8"))
        _ = undo_receipt(root, manifest["transaction_id"])
    _ = (root / "ordinary.md").write_bytes(b"---\ntitle: Ordinary\n---\nNotes.\n")
    _ = MemoryIndex(root).register("Ordinary", "ordinary.md")
    assert check_index(root).ok
    return split


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_labels_preserve_split_topics_and_restored_sources(
    tmp_path: Path, restored: bool, explicit: bool,
) -> None:
    # Given valid split coverage, including the supported undone-source state.
    split = split_vault(tmp_path, restored=restored)
    assert split.coverage_receipt is not None
    protected = ("policy.md", *(topic.document for topic in split.topics),
                 split.coverage_receipt)
    before = {name: (tmp_path / name).read_bytes() for name in protected}

    # When default annotation or explicit replacement names protected paths.
    plan = plan_labels(
        tmp_path, paths=(*protected[:-1], "ordinary.md") if explicit else None,
        labels=("project:Changed",) if explicit else None,
    )
    report = run_labeling(plan, apply=True)

    # Then only the ordinary note changes and original reconstruction survives.
    assert report.ok and report.changed == 1
    assert tuple(note.path for note in plan.notes) == ("ordinary.md",)
    assert {name: (tmp_path / name).read_bytes() for name in protected} == before
    assert check_index(tmp_path).ok


def test_apply_refuses_new_split_authority_without_note_or_route_drift(
    tmp_path: Path,
) -> None:
    # Given a valid restored source and fully registered topic files.
    split = split_vault(tmp_path, restored=True)
    assert split.coverage_receipt is not None
    receipt = tmp_path / split.coverage_receipt
    authority = receipt.read_bytes()
    _ = MemoryIndex(tmp_path).register("Policy source", "policy.md")
    receipt.unlink()
    assert check_index(tmp_path).ok
    plan = plan_labels(tmp_path)

    # When only the valid protection receipt appears after preview.
    _ = receipt.write_bytes(authority)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*")
              if p.is_file() and p.name != ".mnemosyne-mcp.lock"}
    with pytest.raises(ReviewError, match="label selection changed"):
        _ = run_labeling(plan, apply=True)

    # Then protected notes and the remaining eligible note are all untouched.
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*")
            if p.is_file() and p.name != ".mnemosyne-mcp.lock"} == before
    assert check_index(tmp_path).ok


@pytest.mark.parametrize("after_preview", [False, True])
def test_invalid_split_authority_refuses_annotation(
    tmp_path: Path, after_preview: bool,
) -> None:
    # Given a valid split with an unrelated ordinary annotation pending.
    split = split_vault(tmp_path)
    plan = plan_labels(tmp_path)
    assert split.coverage_receipt is not None
    _ = (tmp_path / split.coverage_receipt).write_bytes(b'{"version":1}\n')
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*")
              if p.is_file() and p.name != ".mnemosyne-mcp.lock"}

    # When corrupted coverage is encountered in preview or checked apply.
    with pytest.raises(MemoryIndexError, match="coverage"):
        if after_preview:
            _ = run_labeling(plan, apply=True)
        else:
            _ = plan_labels(tmp_path)

    # Then no label mutation or extra journal is published.
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*")
            if p.is_file() and p.name != ".mnemosyne-mcp.lock"} == before
