"""Applied handoff folds, immutable retries and exact journal undo."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from birkin_mnemosyne import HandoffError, HandoffStore, ReviewError
from birkin_mnemosyne.handoff_records import scope_directory
from birkin_mnemosyne.handoff_retention import HandoffRetention
from birkin_mnemosyne.review_journal import undo_receipt
from test_handoff_retention import _capture, _fields, _scope, _stamp, _state, _scope_dir, _no_reviews


def test_apply_refuses_a_stale_plan_after_new_capture(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(4):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    retention = HandoffRetention(vault)
    result = retention.preview(scope, keep=2)
    _capture(store, scope, "late work", "cap-late", _stamp(4, 30))
    with pytest.raises(ReviewError, match="stale"):
        retention.apply(scope, result.plan_id, keep=2)
    with pytest.raises(ReviewError, match="stale"):
        retention.apply(scope, result.plan_id, keep=1)
    assert _no_reviews(vault)


def test_apply_refuses_when_an_accepted_source_is_corrupted(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(4):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    retention = HandoffRetention(vault)
    result = retention.preview(scope, keep=2)
    (vault / result.accepted[0].path).write_bytes(b"tampered bytes")
    with pytest.raises(HandoffError, match="handoff"):
        retention.apply(scope, result.plan_id, keep=2)
    assert _no_reviews(vault)


def test_apply_with_no_accepted_sources_writes_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(2):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    before = _state(vault)[0]
    retention = HandoffRetention(vault)
    preview = retention.preview(scope, keep=3)
    assert preview.accepted == () and preview.rejected == ()
    result = retention.apply(scope, preview.plan_id, keep=3)
    assert result.state == "noop"
    assert result.transaction_id is None
    assert _state(vault)[0] == before


# ---------------- apply: fold, idempotent retry, undo ------------------------


def test_fold_then_undo_restores_exact_bytes_and_keeps_summary_staged(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    receipts = [_capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
                for i in range(5)]
    before = _state(vault)[0]
    retention = HandoffRetention(vault)
    preview = retention.preview(scope, keep=3)
    assert len(preview.accepted) == 2
    applied = retention.apply(scope, preview.plan_id, keep=3)
    assert applied.state == "committed"
    assert applied.transaction_id is not None
    scope_dir = _scope_dir(vault, scope)
    archive = scope_dir / "archive"
    for receipt in receipts[:2]:
        name = Path(receipt.path).name
        assert not (vault / receipt.path).exists()
        assert (archive / name).read_bytes() == before[receipt.path]
    for receipt in receipts[2:]:
        assert (vault / receipt.path).read_bytes() == before[receipt.path]
    assert store.latest(scope).sha256 == receipts[4].sha256
    summaries = [p for p in scope_dir.glob("*.md") if "--summary--" in p.name]
    assert len(summaries) == 1
    assert hashlib.sha256(summaries[0].read_bytes()).hexdigest() == \
        preview.summary_sha256
    assert summaries[0].read_bytes() == preview.summary.encode("utf-8")
    staging = vault / ".mnemosyne-reviews" / f"fold-{preview.plan_id}.summary.md"
    assert not staging.exists()
    journal = vault / ".mnemosyne-reviews" / f"{applied.transaction_id}.json"
    manifest = json.loads(journal.read_text(encoding="utf-8"))
    assert manifest["state"] == "committed"
    assert manifest["question_id"] == \
        f"handoff:fold:{scope_directory(scope)}:{preview.plan_id}"
    assert "--summary--" in manifest["changes"][-1]["target"]
    assert len(manifest["changes"]) == len(preview.accepted) + 1

    receipt = undo_receipt(vault, applied.transaction_id)
    assert receipt.state == "undone"
    for receipt in receipts:
        assert (vault / receipt.path).read_bytes() == before[receipt.path]
    assert not summaries[0].exists()
    assert staging.read_bytes() == preview.summary.encode("utf-8")
    assert store.latest(scope).sha256 == receipts[4].sha256


def test_committed_retry_is_idempotent_only_while_images_agree(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    receipts = [_capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
                for i in range(4)]
    retention = HandoffRetention(vault)
    preview = retention.preview(scope, keep=2)
    first = retention.apply(scope, preview.plan_id, keep=2)
    assert first.state == "committed"
    reviews_dir = vault / ".mnemosyne-reviews"
    before_count = len(list(reviews_dir.glob("*.json")))
    retry = retention.apply(scope, preview.plan_id, keep=2)
    assert retry.state == "idempotent"
    assert retry.transaction_id == first.transaction_id
    assert len(list(reviews_dir.glob("*.json"))) == before_count
    archived = (_scope_dir(vault, scope) / "archive" /
                Path(receipts[0].path).name)
    archived.write_bytes(b"tampered")
    with pytest.raises(ReviewError, match="images changed"):
        retention.apply(scope, preview.plan_id, keep=2)
    assert len(list(reviews_dir.glob("*.json"))) == before_count


def test_apply_refuses_a_pending_fold_until_undone(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    for i in range(4):
        _capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
    retention = HandoffRetention(vault)
    preview = retention.preview(scope, keep=2)
    qid = f"handoff:fold:{scope_directory(scope)}:{preview.plan_id}"
    for state in ("prepared", "recovery-required"):
        txid = hashlib.sha256(state.encode("utf-8")).hexdigest()[:32]
        manifest = {
            "version": 1, "transaction_id": txid, "question_id": qid,
            "choice": "fold", "merged_body": "", "survivor": "",
            "state": state, "changes": [],
        }
        journal = vault / ".mnemosyne-reviews" / f"{txid}.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ReviewError, match="undo"):
            retention.apply(scope, preview.plan_id, keep=2)


def test_after_undo_old_plan_is_refused_and_fresh_preview_applies(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    receipts = [_capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
                for i in range(5)]
    retention = HandoffRetention(vault)
    first_preview = retention.preview(scope, keep=3)
    first = retention.apply(scope, first_preview.plan_id, keep=3)
    assert first.state == "committed"
    first_txid = first.transaction_id
    assert first_txid is not None
    _ = undo_receipt(vault, first_txid)
    # the old plan is bound to an undone fold: reusing it must fail
    with pytest.raises(ReviewError, match="stale"):
        retention.apply(scope, first_preview.plan_id, keep=3)
    # a fresh preview is not permanently rejected: it binds the undone state
    fresh = retention.preview(scope, keep=3)
    assert fresh.plan_id != first_preview.plan_id
    assert [s.path for s in fresh.accepted] == \
        [s.path for s in first_preview.accepted]
    second = retention.apply(scope, fresh.plan_id, keep=3)
    assert second.state == "committed"
    assert second.transaction_id != first.transaction_id
    assert store.latest(scope).sha256 == receipts[4].sha256


# ---------------- summary content and scope isolation ------------------------


def test_archived_capture_retry_returns_the_original(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    store = HandoffStore(vault)
    scope = _scope()
    receipts = [_capture(store, scope, f"work {i}", f"cap-{i}", _stamp(1 + i))
                for i in range(4)]
    retention = HandoffRetention(vault)
    preview = retention.preview(scope, keep=2)
    applied = retention.apply(scope, preview.plan_id, keep=2)
    assert applied.state == "committed"
    before = _state(vault)[0]
    retry = store.capture(scope, _fields("work 0"), capture_id="cap-0",
                          now=_stamp(1))
    assert retry.archived is True
    assert retry.created is False
    assert retry.sha256 == receipts[0].sha256
    assert _state(vault)[0] == before
