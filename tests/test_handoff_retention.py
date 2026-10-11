"""Curation-gated retention: fold preview/apply over the real gate and journal.

The unchanged ``curation_gate.validate_clamp`` decides every fold against a
fresh complete snapshot — normal notes plus all managed active records across
scopes — so these tests prove the global cap, protection semantics, read-only
preview, stale-plan refusal, exact fold/undo bytes, idempotent committed
retry and the fresh-preview-after-undo invariant through the public API.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PureWindowsPath

import pytest

from birkin_mnemosyne import (
    HANDOFFS_DIRECTORY,
    HandoffError,
    HandoffFields,
    HandoffScope,
    HandoffStore,
    VaultMemory,
    mnemosyne,
)
from birkin_mnemosyne.handoff_records import scope_directory
from birkin_mnemosyne.handoff_retention import HandoffRetention


def _scope(project: str = "mn-070", task: str | None = "handoff") -> HandoffScope:
    return HandoffScope(project, task)


def _fields(work: str, **overrides) -> HandoffFields:
    values = {
        "work": work,
        "next_step": "wire retention",
        "decisions": (f"decide {work}",),
        "open_items": (f"item {work}",),
        "open_questions": (),
        "links": (),
    }
    values.update(overrides)
    return HandoffFields(**values)


def _stamp(hour: int, minute: int = 0) -> str:
    return f"2026-10-11T{hour:02d}:{minute:02d}:00.000000Z"


def _capture(store: HandoffStore, scope: HandoffScope, work: str,
             capture_id: str, stamp: str, **overrides):
    return store.capture(scope, _fields(work, **overrides),
                         capture_id=capture_id, now=stamp)


def _state(root: Path) -> tuple[dict[str, bytes], dict[str, int]]:
    """Every file's bytes and mtime_ns, so a no-write preview is provable."""
    data: dict[str, bytes] = {}
    mtimes: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        data[rel] = path.read_bytes()
        mtimes[rel] = stat.st_mtime_ns
    return data, mtimes


def _archive_cap(active: int) -> int:
    return min(max(2, math.ceil(0.20 * max(1, active))), max(0, active - 1))


def _scope_dir(vault: Path, scope: HandoffScope) -> Path:
    return vault / HANDOFFS_DIRECTORY / scope_directory(scope)


def _no_reviews(vault: Path) -> bool:
    reviews = vault / ".mnemosyne-reviews"
    return not reviews.exists() or not any(reviews.glob("*.json"))


def test_snapshot_uses_receipt_paths_with_windows_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    receipt = _capture(HandoffStore(vault), _scope(), "work", "one", _stamp(1))
    relative_to = Path.relative_to

    def windows_relative(path: Path, other: Path) -> PureWindowsPath:
        return PureWindowsPath(*relative_to(path, other).parts)

    with monkeypatch.context() as patch:
        patch.setattr(type(tmp_path), "relative_to", windows_relative)
        images, mtimes = _state(vault)

    note = vault / receipt.path
    assert images[receipt.path] == note.read_bytes()
    assert mtimes[receipt.path] == note.stat().st_mtime_ns


# ---------------- preview: read-only and deterministic ----------------------


def test_preview_is_read_only_and_deterministic(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    VaultMemory({"vault_path": str(vault)}).write_note(
        "Normal note", "body text", source="test")
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(5):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    before, before_mtime = _state(vault)
    retention = HandoffRetention(vault)
    first = retention.preview(scope, keep=3)
    second = retention.preview(scope, keep=3)
    assert first.plan_id == second.plan_id
    assert first.summary == second.summary
    after, after_mtime = _state(vault)
    assert after == before
    assert after_mtime == before_mtime


def test_preview_pins_latest_and_proposes_only_the_oldest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    receipts = [_capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
                for i in range(5)]
    result = HandoffRetention(vault).preview(scope, keep=3)
    assert result.plan_archive_cap == _archive_cap(5)
    assert [s.path for s in result.accepted] == \
        [receipts[0].path, receipts[1].path]
    assert result.rejected == ()
    assert result.pinned is not None
    assert result.pinned.path == receipts[4].path
    assert result.pinned.sha256 == receipts[4].sha256


def test_gate_global_cap_counts_normal_notes_and_other_scopes(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    for i in range(8):
        memory.write_note(f"Note {i}", f"body {i}", source="test")
    store = HandoffStore(vault)
    a = _scope()
    b = _scope(task="other")
    a_receipts = [_capture(store, a, f"A {i}", f"a-{i}", _stamp(1 + i))
                  for i in range(8)]
    for i in range(3):
        _capture(store, b, f"B {i}", f"b-{i}", _stamp(20 + i))
    result = HandoffRetention(vault).preview(a, keep=3)
    # 8 normal notes + 8 A captures + 3 B captures = 19 active rows; the
    # scope-only cap over A alone would be only 2.
    assert result.plan_archive_cap == _archive_cap(19)
    assert result.plan_archive_cap == 4
    assert len(result.accepted) == result.plan_archive_cap
    assert [s.path for s in result.accepted] == \
        [r.path for r in a_receipts[:result.plan_archive_cap]]
    assert len(result.rejected) == 1
    assert "archive_capped" in result.rejected[0].reason
    assert _scope_dir(vault, b).name not in " ".join(
        s.path for s in result.accepted)


def test_linked_capture_is_protected_by_the_gate(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    linked = _capture(store, scope, "linked work", "cap-0", _stamp(1),
                      links=("https://example.invalid/handoff",))
    second = _capture(store, scope, "work 1", "cap-1", _stamp(2))
    _capture(store, scope, "work 2", "cap-2", _stamp(3))
    result = HandoffRetention(vault).preview(scope, keep=1)
    assert result.plan_archive_cap == _archive_cap(3)
    by_path = {s.path: s for s in (*result.accepted, *result.rejected)}
    assert linked.path in by_path
    assert by_path[linked.path].reason == "protected note"
    assert [s.path for s in result.accepted] == [second.path]
    assert (vault / linked.path).is_file()


def test_normal_note_protection_semantics_are_preserved(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    memory.write_note("Failure log", "ftp broke the build", source="test",
                      polarity="negative")
    memory.write_note("Owner preference", "keep colors", source="test",
                      note_type="preference")
    memory.write_note("Voice guide", "write plainly", source="test",
                      note_type="fact", zone="writing",
                      links=["Draft checklist"])
    memory.write_note("Draft checklist", "read aloud", source="test",
                      note_type="fact", zone="writing", links=["Voice guide"])
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(4):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    # settle the index cache so the committed apply's own refresh is stable
    mnemosyne.Mnemosyne(vault).refresh()
    before = _state(vault)[0]
    retention = HandoffRetention(vault)
    result = retention.preview(scope, keep=2)
    assert result.plan_archive_cap == _archive_cap(8) == 2
    assert len(result.accepted) == 2
    proposed = " ".join(s.path for s in (*result.accepted, *result.rejected))
    assert "failure-log" not in proposed
    assert "owner-preference" not in proposed
    assert "voice-guide" not in proposed and "draft-checklist" not in proposed
    assert _state(vault)[0] == before
    applied = retention.apply(scope, result.plan_id, keep=2)
    assert applied.state == "committed"
    after = _state(vault)[0]
    for rel, data in before.items():
        if not rel.startswith(HANDOFFS_DIRECTORY + "/"):
            assert after[rel] == data


# ---------------- apply: stale plans and no-write cases ----------------------


def test_summary_merges_dedups_and_dates_from_the_newest_source(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    first = _capture(store, scope, "shared work", "cap-0", _stamp(1),
                     next_step="", decisions=("d", "x"), open_items=("o1",),
                     open_questions=("q",))
    second = _capture(store, scope, "shared work", "cap-1", _stamp(2),
                      next_step="next step", decisions=("x",),
                      open_items=("o1", "o2"), open_questions=("q",))
    linked = _capture(store, scope, "linked work", "cap-2", _stamp(3),
                      links=("https://example.invalid/handoff",))
    for i in range(4):
        _capture(store, scope, f"work {i + 3}", f"cap-{i + 3}", _stamp(4 + i))
    result = HandoffRetention(vault).preview(scope, keep=1)
    assert [s.path for s in result.accepted] == \
        [first.path, second.path]
    assert linked.path in {s.path for s in result.rejected}
    assert hashlib.sha256(result.summary.encode("utf-8")).hexdigest() == \
        result.summary_sha256
    body = result.summary.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    payload = json.loads(body)
    assert payload["scope"] == {"project_key": "mn-070", "task_key": "handoff"}
    assert payload["kind"] == "summary"
    assert payload["event"] == "fold"
    assert payload["capture_id"] is None
    # a linked capture is gate-protected, so folds only merge the families
    # of accepted inputs; their links stay with the preserved active record
    assert payload["fields"] == {
        "work": "shared work",
        "next_step": "next step",
        "decisions": ["d", "x"],
        "open_items": ["o1", "o2"],
        "open_questions": ["q"],
        "links": [],
    }
    assert payload["recorded_at"] == _stamp(2)
    assert payload["provenance"] == [
        [first.path, first.sha256], [second.path, second.sha256],
    ]


def test_fold_only_proposes_the_requested_scope(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    a, b = _scope(), _scope(task="other")
    for i in range(4):
        _capture(store, a, f"A {i}", f"a-{i}", _stamp(1 + i))
    b_receipts = [_capture(store, b, f"B {i}", f"b-{i}", _stamp(20 + i))
                  for i in range(3)]
    before = _state(vault)[0]
    retention = HandoffRetention(vault)
    preview = retention.preview(a, keep=2)
    assert len(preview.accepted) == 2
    result = retention.apply(a, preview.plan_id, keep=2)
    assert result.state == "committed"
    for receipt in b_receipts:
        assert (vault / receipt.path).read_bytes() == before[receipt.path]
    assert store.latest(b).sha256 == b_receipts[2].sha256


def test_argument_validation(tmp_path: Path) -> None:
    retention = HandoffRetention(tmp_path / "vault")
    scope = _scope()
    with pytest.raises(HandoffError, match="keep"):
        retention.preview(scope, keep=0)
    with pytest.raises(HandoffError, match="plan_id"):
        retention.apply(scope, "not-a-hex-plan", keep=1)
    assert _no_reviews(tmp_path / "vault")
