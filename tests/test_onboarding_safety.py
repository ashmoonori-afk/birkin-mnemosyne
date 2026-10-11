"""Existing receipts, partial writes and owner arrivals remain recoverable."""

import json
from pathlib import Path

import pytest

from birkin_mnemosyne import onboarding, review_journal
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.memory_index_migration import split_note
from birkin_mnemosyne.onboarding import run_init
from birkin_mnemosyne.onboarding_plan import plan_init
from birkin_mnemosyne.review_journal import Manifest, ReviewError, undo_receipt


def seed(root: Path) -> bytes:
    raw = b"# Policy\r\nKeep approval.\r\n## Deploy\r\nKeep rollback."
    _ = (root / "policy.md").write_bytes(raw)
    return raw


@pytest.mark.parametrize("restored", [False, True])
def test_existing_split_receipt_bytes_are_never_normalized(
    tmp_path: Path, restored: bool,
) -> None:
    # Given existing byte coverage in notice or restored-original state.
    _ = seed(tmp_path)
    split = split_note(tmp_path, "policy.md", apply=True)
    assert split.backup_journal is not None
    if restored:
        record = json.loads((tmp_path / split.backup_journal).read_bytes())
        _ = undo_receipt(tmp_path, record["transaction_id"])
    protected = ("policy.md", *(topic.document for topic in split.topics))
    before = {relative: (tmp_path / relative).read_bytes() for relative in protected}

    # When initialization is explicitly applied.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then all bound byte images and their exact coverage survive.
    assert report.ok and check_index(tmp_path).ok
    assert {relative: (tmp_path / relative).read_bytes() for relative in protected} == before
    assert all(not item.frontmatter_additions for item in report.sources if item.path in protected)


def test_partial_catalogue_failure_can_retry_without_duplicate_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a failed catalogue publication after raw imports were created.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    raw = seed(external)
    create = onboarding.atomic_create_bytes

    def fail_catalogue(path: Path, data: bytes) -> None:
        if path.parent.name == "onboarding-topics":
            raise OSError("injected catalogue publication failure")
        create(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(onboarding, "atomic_create_bytes", fail_catalogue)
        with pytest.raises(OSError):
            _ = run_init(plan_init(root, import_dir=external), apply=True)
    imported = tuple((root / "imports").rglob("policy.md"))
    assert len(imported) == 1 and imported[0].read_bytes() == raw

    # When a fresh plan retries the remaining additive work.
    report = run_init(plan_init(root, import_dir=external), apply=True)

    # Then the existing import is reused, not copied again or lost.
    assert report.ok and len(tuple((root / "imports").rglob("policy.md"))) == 1
    assert imported[0].read_bytes().endswith(raw)
    assert (external / "policy.md").read_bytes() == raw


def test_arriving_catalogue_owner_bytes_are_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an owner arrival at the exclusive publication boundary.
    raw = seed(tmp_path)
    plan = plan_init(tmp_path)
    create = onboarding.atomic_create_bytes
    owner = b"Owner data arriving after preflight."
    arrival = tmp_path / plan.catalogues[0].path

    def arrive_then_create(path: Path, data: bytes) -> None:
        if path == arrival:
            path.parent.mkdir(parents=True, exist_ok=True)
            _ = path.write_bytes(owner)
        create(path, data)

    monkeypatch.setattr(onboarding, "atomic_create_bytes", arrive_then_create)

    # When apply encounters the concurrently occupied destination.
    with pytest.raises(FileExistsError):
        _ = run_init(plan, apply=True)

    # Then both the owner arrival and original source survive.
    assert arrival.read_bytes() == owner
    assert (tmp_path / "policy.md").read_bytes() == raw


def test_prepared_normalization_journal_blocks_retry_until_checked_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a journal prepared before a handled publication interruption.
    raw = seed(tmp_path)
    save = review_journal._save

    def save_then_fail(path: Path, manifest: Manifest) -> None:
        save(path, manifest)
        if manifest["state"] == "prepared":
            raise OSError("injected interruption after preparation")

    with monkeypatch.context() as patch:
        patch.setattr(review_journal, "_save", save_then_fail)
        with pytest.raises(OSError):
            _ = run_init(plan_init(tmp_path), apply=True)
    journal = next((tmp_path / ".mnemosyne-reviews").glob("*.json"))
    record = json.loads(journal.read_bytes())
    assert record["state"] == "prepared"
    blocked = plan_init(tmp_path)
    assert blocked.state.recovery

    # When apply is retried before recovery is authorized.
    with pytest.raises(ReviewError):
        _ = run_init(blocked, apply=True)

    # Then no new journal/source mutation occurs and checked undo remains usable.
    assert len(tuple((tmp_path / ".mnemosyne-reviews").glob("*.json"))) == 1
    assert (tmp_path / "policy.md").read_bytes() == raw
    _ = undo_receipt(tmp_path, record["transaction_id"])
    assert run_init(plan_init(tmp_path), apply=True).ok


def test_existing_dangling_alias_is_retained_and_apply_reports_drift(tmp_path: Path) -> None:
    # Given a previously registered alias whose target was removed by its owner.
    _ = seed(tmp_path)
    index = MemoryIndex(tmp_path)
    previous = index.register("old alias", "policy.md").entries
    (tmp_path / "policy.md").unlink()

    # When the empty active vault is initialized.
    report = run_init(plan_init(tmp_path), apply=True)

    # Then drift is reported without dropping the old route.
    assert not report.ok and report.verification == "failed" and report.warnings
    assert index.read().entries == previous


def test_edited_import_destination_is_refused_without_replacement(tmp_path: Path) -> None:
    # Given an imported destination edited by its owner after successful apply.
    external, root = tmp_path / "external", tmp_path / "vault"
    external.mkdir()
    original = seed(external)
    first = run_init(plan_init(root, import_dir=external), apply=True)
    destination = root / first.import_documents[0]
    owner = b"Owner revision of the imported note."
    _ = destination.write_bytes(owner)

    # When the same import is planned again.
    with pytest.raises(MemoryIndexError):
        _ = plan_init(root, import_dir=external)

    # Then neither source nor owner destination is changed.
    assert destination.read_bytes() == owner
    assert (external / "policy.md").read_bytes() == original


def test_large_topic_map_and_small_budget_retain_every_route(tmp_path: Path) -> None:
    # Given a larger structural topic and an existing alias.
    folder = tmp_path / "knowledge"
    folder.mkdir()
    for number in range(30):
        _ = (folder / f"policy-{number}.md").write_bytes(f"Keep rule {number}.".encode())
    index = MemoryIndex(tmp_path)
    previous = index.register("old alias", "knowledge/policy-0.md").entries

    # When initialization uses a deliberately tiny warning budget.
    report = run_init(plan_init(tmp_path, max_tokens=1), apply=True)

    # Then the complete grouped map is retained and size is only a warning.
    view = index.read()
    assert report.ok and view.mode == "grouped" and report.warnings
    assert set(previous).issubset(view.entries)
    assert {f"knowledge/policy-{number}.md" for number in range(30)}.issubset(
        {entry.document for entry in view.entries})
    expanded = tuple(entry for topic in view.topics for entry in index.read(topic=topic.topic).entries)
    assert set(expanded) == set(view.entries)
