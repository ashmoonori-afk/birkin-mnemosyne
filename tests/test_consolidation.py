from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from birkin_mnemosyne import (
    Answer,
    Consolidation,
    ReviewError,
    VaultMemory,
    review_journal,
)


def seed(vault: Path):
    memory = VaultMemory({"vault_path": str(vault)})
    memory.write_note("First policy", "Review every release before publishing.",
                      source="chat:first", tags=["guard"], polarity="negative")
    memory.write_note("Second policy", "Review every release before publishing.",
                      source="chat:second")
    service = Consolidation(vault)
    return memory, service, service.questions()[0]


def images(vault: Path):
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*.md")}


def test_discovery_does_not_change_notes(tmp_path):
    memory, _, _ = seed(tmp_path)
    before = images(tmp_path)
    questions = Consolidation(tmp_path).questions()
    assert len(questions) == 1
    assert questions[0].reason == "duplicate"
    assert questions[0].first.sources == ("chat:first",)
    assert images(tmp_path) == before
    assert len(memory.list_notes()) == 2


@pytest.mark.parametrize("choice", [
    "keep-first", "keep-second", "current-first", "current-second",
    "drop-first", "drop-second",
])
def test_explicit_retirement_is_exactly_reversible(tmp_path, choice):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    receipt = service.apply(question, Answer(question.id, choice))
    assert receipt.state == "committed"
    assert len(service.dex.search("release")) == 1
    archived = list((tmp_path / "_archive").glob("*.md"))
    assert len(archived) == 1
    manifest = json.loads((tmp_path / receipt.journal_path).read_text("utf-8"))
    assert manifest["choice"] == choice
    assert manifest["question_id"] == question.id
    service.undo(receipt.transaction_id)
    assert images(tmp_path) == before
    assert len(Consolidation(tmp_path).dex.search("release")) == 2


def test_merge_preserves_survivor_metadata_and_both_sources(tmp_path):
    memory, service, question = seed(tmp_path)
    before = images(tmp_path)
    receipt = service.apply(question, Answer(
        question.id, "merge", "Review releases; the user approved this merge.",
    ))
    meta = service.dex.note_meta("first-policy")
    assert meta["polarity"] == "negative"
    text = memory.get_note("First policy")
    assert '"chat:first", "chat:second"' in text
    assert "tags: [guard]" in text
    service.undo(receipt.transaction_id)
    assert images(tmp_path) == before


def test_keep_both_records_answer_without_retirement(tmp_path):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    service.apply(question, Answer(question.id, "keep-both"))
    assert images(tmp_path) == before


def test_stale_answer_does_not_overwrite_edit(tmp_path):
    memory, service, question = seed(tmp_path)
    memory.write_note("Second policy", "Release requires two reviewers.")
    before = images(tmp_path)
    with pytest.raises(ReviewError, match="stale"):
        service.apply(question, Answer(question.id, "keep-first"))
    assert images(tmp_path) == before


def test_forged_question_binding_is_rejected(tmp_path):
    _, service, question = seed(tmp_path)
    with pytest.raises(ReviewError, match="bind"):
        service.apply(question, Answer("not-offered", "keep-first"))
    assert len(service.dex.search("release")) == 2


def test_forged_question_body_cannot_misrepresent_snapshot(tmp_path):
    _, service, question = seed(tmp_path)
    forged = replace(question, first=replace(question.first, body="Invented fact."))
    before = images(tmp_path)
    with pytest.raises(ReviewError, match="snapshot"):
        service.apply(forged, Answer(question.id, "keep-first"))
    assert images(tmp_path) == before


def test_archive_collision_preserves_unrelated_file(tmp_path):
    _, service, question = seed(tmp_path)
    archive = tmp_path / "_archive" / Path(question.second.path).name
    archive.parent.mkdir()
    archive.write_bytes(b"Unrelated archived original")
    before = images(tmp_path)
    with pytest.raises(ReviewError):
        service.apply(question, Answer(question.id, "keep-first"))
    assert images(tmp_path) == before


def test_undo_refuses_user_edit_without_partial_restore(tmp_path):
    _, service, question = seed(tmp_path)
    receipt = service.apply(question, Answer(question.id, "keep-first"))
    archive = next((tmp_path / "_archive").glob("*.md"))
    archive.write_bytes(b"User edited the archive")
    before = images(tmp_path)
    with pytest.raises(ReviewError, match="post-image"):
        service.undo(receipt.transaction_id)
    assert images(tmp_path) == before


@pytest.mark.parametrize("boundary", ["merge-write", "refresh", "final-receipt"])
def test_handled_failure_rolls_back_all_note_images(tmp_path, monkeypatch, boundary):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    write = review_journal.atomic_write_bytes
    refresh = review_journal._refresh
    tripped = False

    def failing_write(path, data):
        nonlocal tripped
        target = path.suffix == ".md" if boundary == "merge-write" else \
            path.suffix == ".json" and b'"state": "committed"' in data
        if boundary != "refresh" and target and not tripped:
            tripped = True
            raise OSError("injected transaction boundary")
        write(path, data)

    def failing_refresh(vault):
        nonlocal tripped
        if boundary == "refresh" and not tripped:
            tripped = True
            raise OSError("injected index failure")
        refresh(vault)

    monkeypatch.setattr(review_journal, "atomic_write_bytes", failing_write)
    monkeypatch.setattr(review_journal, "_refresh", failing_refresh)
    with pytest.raises(ReviewError, match="rolled back"):
        service.apply(question, Answer(question.id, "merge", "Explicit merged fact."))
    assert tripped
    assert images(tmp_path) == before
    journal = next((tmp_path / ".mnemosyne-reviews").glob("*.json"))
    assert json.loads(journal.read_text("utf-8"))["state"] == "rolled-back"


def test_recovery_required_journal_keeps_originals(tmp_path, monkeypatch):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    refresh = review_journal._refresh
    monkeypatch.setattr(review_journal, "_refresh",
                        lambda _vault: (_ for _ in ()).throw(OSError("index offline")))
    with pytest.raises(ReviewError, match="recovery required"):
        service.apply(question, Answer(question.id, "merge", "User merged fact."))
    journal = next((tmp_path / ".mnemosyne-reviews").glob("*.json"))
    assert json.loads(journal.read_text("utf-8"))["state"] == "recovery-required"
    monkeypatch.setattr(review_journal, "_refresh", refresh)
    service.undo(journal.stem)
    assert images(tmp_path) == before


def test_separate_public_writer_waits_for_transaction(tmp_path, monkeypatch):
    _, service, question = seed(tmp_path)
    prepared, release, writer_started = Event(), Event(), Event()
    save = review_journal._save

    def paused_save(path, manifest):
        save(path, manifest)
        if manifest["state"] == "prepared":
            prepared.set()
            assert release.wait(timeout=5)

    def concurrent_write():
        writer_started.set()
        VaultMemory({"vault_path": str(tmp_path)}).write_note(
            "First policy", "Concurrent post-review fact.",
        )

    monkeypatch.setattr(review_journal, "_save", paused_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        applying = pool.submit(service.apply, question,
                               Answer(question.id, "merge", "Reviewed merged fact."))
        assert prepared.wait(timeout=5)
        writing = pool.submit(concurrent_write)
        assert writer_started.wait(timeout=5)
        release.set()
        applying.result(timeout=5)
        writing.result(timeout=5)
    text = VaultMemory({"vault_path": str(tmp_path)}).get_note("First policy")
    assert "Concurrent post-review fact." in text


def test_unrelated_shared_topic_and_empty_notes_are_not_questions(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Rail tickets", "Rail tickets require a reservation.")
    memory.write_note("Rail history", "Rail engines were steam powered.")
    memory.write_note("Empty", "")
    assert Consolidation(tmp_path).questions() == ()
