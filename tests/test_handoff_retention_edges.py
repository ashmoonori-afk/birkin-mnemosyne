"""Boundary regressions for complete, reversible handoff folds."""

from pathlib import Path

import pytest

from birkin_mnemosyne.handoff_records import HandoffError, HandoffFields, HandoffScope
from birkin_mnemosyne.handoff_retention import HandoffRetention
from birkin_mnemosyne.handoffs import HandoffStore
from birkin_mnemosyne.review_journal import ReviewError


def _captures(vault: Path, count: int = 6) -> tuple[HandoffStore, HandoffScope]:
    store, scope = HandoffStore(vault), HandoffScope("project", "task")
    for number in range(count):
        _ = store.capture(scope, HandoffFields(f"work {number}"), capture_id=str(number))
    return store, scope


def test_summary_read_limit_is_checked_before_any_publication(tmp_path: Path) -> None:
    store, scope = HandoffStore(tmp_path), HandoffScope("large")
    for number in range(4):
        _ = store.capture(scope, HandoffFields(f"{number}:" + "x" * 530_000),
                          capture_id=str(number))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(HandoffError):
        _ = HandoffRetention(tmp_path).preview(scope, keep=1)
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_wikilink_in_work_is_protected_like_an_ordinary_note(tmp_path: Path) -> None:
    store, scope = HandoffStore(tmp_path), HandoffScope("linked")
    linked = store.capture(scope, HandoffFields("Continue [[permanent]]"), capture_id="linked")
    _ = store.capture(scope, HandoffFields("ordinary"), capture_id="ordinary")
    _ = store.capture(scope, HandoffFields("latest"), capture_id="latest")
    preview = HandoffRetention(tmp_path).preview(scope, keep=1)
    assert linked.path not in {source.path for source in preview.accepted}
    assert linked.path in {source.path for source in preview.rejected}


def test_empty_fold_apply_does_not_create_a_vault_or_lock(tmp_path: Path) -> None:
    vault = tmp_path / "absent-vault"
    retention, scope = HandoffRetention(vault), HandoffScope("empty")
    preview = retention.preview(scope)
    result = retention.apply(scope, preview.plan_id)
    assert result.state == "noop"
    assert not vault.exists()


def test_retry_reports_the_committed_plan_and_summary(tmp_path: Path) -> None:
    _, scope = _captures(tmp_path)
    retention = HandoffRetention(tmp_path)
    preview = retention.preview(scope, keep=1)
    first = retention.apply(scope, preview.plan_id, keep=1)
    repeated = retention.apply(scope, preview.plan_id, keep=1)
    assert repeated.transaction_id == first.transaction_id
    assert (repeated.plan_id, repeated.summary, repeated.summary_sha256, repeated.accepted) == (
        first.plan_id, first.summary, first.summary_sha256, first.accepted,
    )


def test_corrupt_fold_journal_is_not_silently_ignored(tmp_path: Path) -> None:
    _, scope = _captures(tmp_path)
    retention = HandoffRetention(tmp_path)
    preview = retention.preview(scope, keep=1)
    receipt = retention.apply(scope, preview.plan_id, keep=1)
    _ = (tmp_path / receipt.journal_path).write_bytes(b"not a valid journal")
    with pytest.raises((HandoffError, ReviewError)):
        _ = retention.preview(scope, keep=1)


def test_linked_journal_root_is_refused_before_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, scope = _captures(tmp_path)
    reviews = tmp_path / ".mnemosyne-reviews"
    reviews.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == reviews or original(path))
    with pytest.raises(HandoffError):
        _ = HandoffRetention(tmp_path).preview(scope, keep=1)
