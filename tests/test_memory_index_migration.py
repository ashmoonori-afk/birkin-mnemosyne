"""Every source byte and line remains reachable after an explicit split."""

from __future__ import annotations

import base64
import json

import pytest

from birkin_mnemosyne import (
    MemoryIndex,
    MemoryIndexError,
    StartupReader,
    check_index,
    format_coverage,
    split_note,
)
from birkin_mnemosyne import memory_index_migration as migration
from birkin_mnemosyne import review_journal as journal
from birkin_mnemosyne.review_journal import ReviewError, undo_receipt

SOURCE = (
    "\ufeff---\r\ntitle: Original\r\n---\r\n\r\n# Rules\r\n"
    "Owner: Fictional operator\r\n\r\n## Deploy\r\n"
    "Rule: keep approval.\r\n### Exception\r\n"
    "Rule: emergency changes still need approval.\r\n"
    "```markdown\r\n## Example only\r\nRule: illustrative, not live.\r\n```\r\n"
    "## 연락\r\nRule: 비동기 메시지\r\n\r\nLast line without newline"
).encode("utf-8")


def note(root, raw=SOURCE):
    path = root / "memory.md"
    path.write_bytes(raw)
    return path


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_preview_is_read_only_and_maps_every_original_line(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    report = split_note(tmp_path, "memory.md")
    assert not report.applied and report.coverage_receipt is None
    assert tree(tmp_path) == before
    lines = SOURCE.decode("utf-8").splitlines(keepends=True)
    assert [row.line for row in report.coverage] == list(range(1, len(lines) + 1))
    assert [row.text for row in report.coverage] == lines
    assert "Example only" not in {topic.trigger for topic in report.topics}
    table = format_coverage(report)
    assert len(table.splitlines()) == len(lines) + 2
    assert all(row.document in table for row in report.coverage)


def test_applied_split_is_byte_exact_indexed_and_backed_up(tmp_path):
    path = note(tmp_path)
    report = split_note(tmp_path, "memory.md", apply=True)
    index = MemoryIndex(tmp_path)
    recovered = b"".join(
        (tmp_path / topic.document).read_bytes()[topic.prefix_bytes:]
        for topic in report.topics
    )
    assert recovered == SOURCE
    assert path.read_bytes() != SOURCE
    assert {(entry.trigger, entry.document) for entry in index.read().entries} == {
        (topic.trigger, topic.document) for topic in report.topics}
    for row in report.coverage:
        lines = (tmp_path / row.document).read_bytes().decode("utf-8").splitlines(keepends=True)
        assert lines[row.document_line - 1] == row.text
    backup = json.loads((tmp_path / report.backup_journal).read_bytes())
    assert base64.b64decode(backup["changes"][0]["before"]) == SOURCE
    assert check_index(tmp_path).ok
    bundle = StartupReader(tmp_path).read(["memory.md"])
    assert bundle.coverage.complete
    assert "emergency changes still need approval" not in bundle.context
    opened = index.open("Exception")
    assert "emergency changes still need approval" in opened.documents[0].content
    assert "# Rules" in opened.documents[0].content
    assert "## Deploy" in opened.documents[0].content


@pytest.mark.parametrize("raw", [b"", b"Only one rule.", b"\xef\xbb\xbf", b"\r\n\r\n"])
def test_empty_or_unsectioned_sources_are_not_lost(tmp_path, raw):
    note(tmp_path, raw)
    report = split_note(tmp_path, "memory.md", apply=True)
    assert b"".join((tmp_path / t.document).read_bytes()[t.prefix_bytes:]
                    for t in report.topics) == raw
    assert "".join(row.text for row in report.coverage).encode("utf-8") == raw
    assert check_index(tmp_path).ok


def test_destination_collision_refuses_before_any_write(tmp_path):
    note(tmp_path)
    preview = split_note(tmp_path, "memory.md")
    collision = tmp_path / preview.topics[-1].document
    collision.parent.mkdir()
    collision.write_bytes(b"Existing user document.")
    before = tree(tmp_path)
    with pytest.raises(MemoryIndexError, match="already exists"):
        split_note(tmp_path, "memory.md", apply=True)
    after = tree(tmp_path)
    assert {k: v for k, v in after.items() if k != ".mnemosyne-mcp.lock"} == before


def test_topic_write_failure_keeps_original_source(tmp_path, monkeypatch):
    path = note(tmp_path)
    original_write = migration.atomic_create_bytes
    calls = 0

    def fail_second_topic(target, raw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected topic write failure")
        original_write(target, raw)
    monkeypatch.setattr(migration, "atomic_create_bytes", fail_second_topic)
    with pytest.raises(OSError, match="injected"):
        split_note(tmp_path, "memory.md", apply=True)
    assert path.read_bytes() == SOURCE
    assert check_index(tmp_path).orphan_documents


def test_concurrent_external_source_edit_is_not_overwritten(tmp_path, monkeypatch):
    path = note(tmp_path)
    original_commit = migration.commit

    def change_before_commit(*args):
        path.write_bytes(b"New owner text.")
        return original_commit(*args)
    monkeypatch.setattr(migration, "commit", change_before_commit)
    with pytest.raises(ReviewError, match="precondition"):
        split_note(tmp_path, "memory.md", apply=True)
    assert path.read_bytes() == b"New owner text."
    assert check_index(tmp_path).errors


def test_original_can_be_restored_without_removing_any_index_entry(tmp_path):
    path = note(tmp_path)
    report = split_note(tmp_path, "memory.md", apply=True)
    index = MemoryIndex(tmp_path)
    before = index.path.read_bytes()
    transaction = json.loads((tmp_path / report.backup_journal).read_bytes())["transaction_id"]
    undo_receipt(tmp_path, transaction)
    assert path.read_bytes() == SOURCE
    assert index.path.read_bytes() == before
    assert check_index(tmp_path).ok


def test_checker_names_orphans_and_dangling_entries_without_writes(tmp_path):
    note(tmp_path, b"Main rule.")
    orphan = tmp_path / "orphan.md"
    orphan.write_bytes(b"Unindexed rule.")
    index = MemoryIndex(tmp_path)
    index.register("main task", "memory.md")
    (tmp_path / "memory.md").unlink()
    before = tree(tmp_path)
    checked = check_index(tmp_path)
    assert not checked.ok
    assert checked.orphan_documents == ("orphan.md",)
    assert [(e.trigger, e.document) for e in checked.dangling_entries] == [
        ("main task", "memory.md")]
    assert tree(tmp_path) == before


@pytest.mark.parametrize("mutation", ["topic", "route", "receipt", "source"])
def test_checker_rejects_lost_coverage(tmp_path, mutation):
    path = note(tmp_path)
    report = split_note(tmp_path, "memory.md", apply=True)
    if mutation == "topic":
        (tmp_path / report.topics[-1].document).write_bytes(b"Lost original rules.")
    elif mutation == "route":
        index = MemoryIndex(tmp_path)
        data = json.loads(index.path.read_bytes())
        data["entries"].pop()
        index.path.write_bytes(json.dumps(data).encode())
    elif mutation == "receipt":
        (tmp_path / report.coverage_receipt).write_bytes(b"{invalid")
    else:
        path.write_bytes(path.read_bytes() + b"\nNew unindexed rule.\n")
    checked = check_index(tmp_path)
    assert not checked.ok
    assert checked.errors


def test_archive_and_hidden_documents_are_not_orphan_candidates(tmp_path):
    for folder in ("_archive", ".private"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "old.md").write_bytes(b"Not an active topic.")
    assert check_index(tmp_path).orphan_documents == ()


def test_unsafe_source_and_invalid_budget_do_not_change_notes(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    for document, maximum in (("../outside.md", None), ("memory.md", 0)):
        with pytest.raises(MemoryIndexError):
            split_note(tmp_path, document, apply=True, max_tokens=maximum)
    assert {k: v for k, v in tree(tmp_path).items()
            if k != ".mnemosyne-mcp.lock"} == before


def test_registered_source_cannot_hide_a_missing_receipt(tmp_path):
    note(tmp_path)
    MemoryIndex(tmp_path).register("all rules", "memory.md")
    report = split_note(tmp_path, "memory.md", apply=True)
    (tmp_path / report.coverage_receipt).unlink()
    (tmp_path / report.topics[-1].document).write_bytes(b"Unrelated replacement.")
    checked = check_index(tmp_path)
    assert not checked.ok
    assert checked.errors


def test_source_edit_during_journal_preparation_survives(tmp_path, monkeypatch):
    path = note(tmp_path)
    original_save = journal._save
    external = b"Owner revision after the journal was prepared."

    def save_then_edit(target, manifest):
        original_save(target, manifest)
        if manifest["state"] == "prepared":
            path.write_bytes(external)
    monkeypatch.setattr(journal, "_save", save_then_edit)
    with pytest.raises(ReviewError):
        split_note(tmp_path, "memory.md", apply=True)
    assert path.read_bytes() == external
    assert external in tree(tmp_path).values()
    assert check_index(tmp_path).errors


@pytest.mark.parametrize("destination", ["topic", "receipt"])
def test_destination_arriving_after_preflight_is_preserved(tmp_path, monkeypatch, destination):
    path = note(tmp_path)
    original_create = migration.atomic_create_bytes
    arrivals = []
    external = b"Existing owner data must not be overwritten."

    def create_after_arrival(target, raw):
        if not arrivals and (target.suffix == ".json") == (destination == "receipt"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(external)
            arrivals.append(target)
        original_create(target, raw)
    monkeypatch.setattr(migration, "atomic_create_bytes", create_after_arrival)
    with pytest.raises(FileExistsError):
        split_note(tmp_path, "memory.md", apply=True)
    assert len(arrivals) == 1 and arrivals[0].read_bytes() == external
    assert path.read_bytes() == SOURCE


def test_notice_requires_its_own_receipt_not_another_valid_receipt(tmp_path):
    note(tmp_path)
    (tmp_path / "other.md").write_bytes(b"# Other\nRule: separate.")
    MemoryIndex(tmp_path).register("all rules", "memory.md")
    first = split_note(tmp_path, "memory.md", apply=True)
    other = split_note(tmp_path, "other.md", apply=True)
    (tmp_path / first.coverage_receipt).write_bytes(
        (tmp_path / other.coverage_receipt).read_bytes())
    assert not check_index(tmp_path).ok


@pytest.mark.parametrize("arrival", ["replacement", "captured-edit"])
def test_late_source_revision_survives_final_publication(tmp_path, monkeypatch, arrival):
    path = note(tmp_path)
    create = journal.atomic_create_bytes
    external = b"Owner revision at final publication."

    def write_external_then_publish(target, raw, **kwargs):
        if target == path:
            if arrival == "replacement":
                target.write_bytes(external)
            else:
                captured = next((tmp_path / ".mnemosyne-reviews").rglob("source.snapshot"))
                captured.write_bytes(external)
        create(target, raw, **kwargs)
    monkeypatch.setattr(journal, "atomic_create_bytes", write_external_then_publish)
    if arrival == "replacement":
        with pytest.raises(ReviewError):
            split_note(tmp_path, "memory.md", apply=True)
        assert path.read_bytes() == external
    else:
        with pytest.raises(ReviewError):
            split_note(tmp_path, "memory.md", apply=True)
        assert external in [
            p.read_bytes() for p in (tmp_path / ".mnemosyne-reviews").rglob("*.snapshot")]
    assert external in tree(tmp_path).values()


def test_error_after_notice_publication_restores_the_original(tmp_path, monkeypatch):
    path = note(tmp_path)
    create = journal.atomic_create_bytes
    failed = False

    def publish_then_fail(target, raw, **kwargs):
        nonlocal failed
        create(target, raw, **kwargs)
        if target == path and not failed:
            failed = True
            raise OSError("injected error after publication")
    monkeypatch.setattr(journal, "atomic_create_bytes", publish_then_fail)
    with pytest.raises(ReviewError):
        split_note(tmp_path, "memory.md", apply=True)
    assert failed
    assert path.read_bytes() == SOURCE
