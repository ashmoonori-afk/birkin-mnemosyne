from __future__ import annotations

import errno
import json
import multiprocessing
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from birkin_mnemosyne import (
    Answer,
    Consolidation,
    ReviewError,
    VaultMemory,
    consolidation,
    review_journal,
    vault_lock,
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


@pytest.mark.parametrize(("choice", "survivor", "retired"), [
    ("keep-first", "first", "second"),
    ("keep-second", "second", "first"),
    ("current-first", "first", "second"),
    ("current-second", "second", "first"),
    ("drop-first", "second", "first"),
    ("drop-second", "first", "second"),
])
def test_explicit_retirement_is_exactly_reversible(tmp_path, choice, survivor, retired):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    receipt = service.apply(question, Answer(question.id, choice))
    assert receipt.state == "committed"
    assert len(service.dex.search("release")) == 1
    archived = list((tmp_path / "_archive").glob("*.md"))
    survivor_note, retired_note = getattr(question, survivor), getattr(question, retired)
    assert (tmp_path / survivor_note.path).read_bytes() == before[survivor_note.path]
    assert not (tmp_path / retired_note.path).exists()
    assert archived == [tmp_path / "_archive" / Path(retired_note.path).name]
    assert archived[0].read_bytes() == before[retired_note.path]
    assert {note["path"] for note in VaultMemory({"vault_path": str(tmp_path)}).list_notes()} \
        == {tmp_path / survivor_note.path}
    manifest = json.loads((tmp_path / receipt.journal_path).read_text("utf-8"))
    assert manifest["choice"] == choice
    assert manifest["question_id"] == question.id
    service.undo(receipt.transaction_id)
    assert images(tmp_path) == before
    assert len(Consolidation(tmp_path).dex.search("release")) == 2


@pytest.mark.parametrize("survivor", ["first", "second"])
def test_merge_preserves_survivor_metadata_and_both_sources(tmp_path, survivor):
    memory, service, question = seed(tmp_path)
    before = images(tmp_path)
    receipt = service.apply(question, Answer(
        question.id, "merge", "Review releases; the user approved this merge.",
        survivor=survivor,
    ))
    survivor_note = getattr(question, survivor)
    retired_note = question.second if survivor == "first" else question.first
    meta = service.dex.note_meta(Path(survivor_note.path).stem)
    assert meta["polarity"] == ("negative" if survivor == "first" else "positive")
    text = memory.get_note(survivor_note.title)
    assert "Review releases; the user approved this merge." in text
    assert ('"chat:first", "chat:second"' if survivor == "first" else
            '"chat:second", "chat:first"') in text
    assert ('tags: ["guard"]' in text) == (survivor == "first")
    assert not (tmp_path / retired_note.path).exists()
    assert (tmp_path / "_archive" / Path(retired_note.path).name).read_bytes() \
        == before[retired_note.path]
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


@pytest.mark.parametrize("boundary", ["recovery-phase", "archive-unlink", "final-receipt"])
def test_undo_retries_exact_restoration_after_io_failure(tmp_path, monkeypatch, boundary):
    _, service, question = seed(tmp_path)
    before = images(tmp_path)
    receipt = service.apply(question, Answer(
        question.id, "merge", "Explicit merged fact.",
    ))
    journal = tmp_path / receipt.journal_path
    post_images = images(tmp_path)
    archive = tmp_path / "_archive" / Path(question.second.path).name
    unlink, save = Path.unlink, review_journal._save

    def failing_unlink(path, *args, **kwargs):
        if path == archive:
            raise PermissionError("injected archive unlink failure")
        return unlink(path, *args, **kwargs)

    def failing_save(path, manifest):
        if boundary == "recovery-phase" or manifest["state"] == "undone" or (
            manifest["state"] == "recovery-required" and images(tmp_path) == before
        ):
            raise OSError("injected final journal write failure")
        save(path, manifest)

    with monkeypatch.context() as fault:
        if boundary == "archive-unlink":
            fault.setattr(Path, "unlink", failing_unlink)
        else:
            fault.setattr(review_journal, "_save", failing_save)
        with pytest.raises((ReviewError, OSError)):
            service.undo(receipt.transaction_id)
    if boundary == "archive-unlink":
        assert (tmp_path / question.second.path).read_bytes() == before[question.second.path]
        assert archive.read_bytes() == before[question.second.path]
    elif boundary == "final-receipt":
        assert images(tmp_path) == before
    else:
        assert images(tmp_path) == post_images
        assert json.loads(journal.read_text("utf-8"))["state"] == "committed"
    if boundary != "recovery-phase":
        assert json.loads(journal.read_text("utf-8"))["state"] == "recovery-required"
    restored = service.undo(receipt.transaction_id)
    assert restored.state == "undone"
    assert images(tmp_path) == before
    assert json.loads(journal.read_text("utf-8"))["state"] == "undone"


@pytest.mark.parametrize("edited", ["source", "archive"])
def test_recovery_refuses_unrelated_edit_before_any_restoration(tmp_path, monkeypatch, edited):
    _, service, question = seed(tmp_path)
    receipt = service.apply(question, Answer(question.id, "merge", "Merged fact."))
    archive = tmp_path / "_archive" / Path(question.second.path).name
    unlink = Path.unlink

    def failing_unlink(path, *args, **kwargs):
        if path == archive:
            raise PermissionError("injected archive unlink failure")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "unlink", failing_unlink)
        with pytest.raises(ReviewError, match="recovery required"):
            service.undo(receipt.transaction_id)
    target = tmp_path / question.second.path if edited == "source" else archive
    target.write_bytes(b"Unrelated user edit")
    before = images(tmp_path)
    journal = tmp_path / receipt.journal_path
    manifest = journal.read_bytes()
    writes = []
    write = review_journal.atomic_write_bytes

    def observed_write(path, data):
        writes.append(path)
        write(path, data)

    monkeypatch.setattr(review_journal, "atomic_write_bytes", observed_write)
    with pytest.raises(ReviewError, match="post-image"):
        service.undo(receipt.transaction_id)
    assert writes == []
    assert images(tmp_path) == before
    assert journal.read_bytes() == manifest


@pytest.mark.parametrize("malformation", [
    "json", "encoding", "manifest", "changes", "record", "base64",
])
def test_malformed_journal_is_a_review_error_without_note_writes(
    tmp_path, malformation,
):
    _, service, question = seed(tmp_path)
    receipt = service.apply(question, Answer(question.id, "keep-first"))
    journal = tmp_path / receipt.journal_path
    manifest = json.loads(journal.read_text("utf-8"))
    if malformation == "json":
        data = b"{"
    elif malformation == "encoding":
        data = b"\xff"
    elif malformation == "manifest":
        data = b"[]"
    else:
        if malformation == "changes":
            manifest.pop("changes")
        elif malformation == "record":
            manifest["changes"][0]["source"] = 42
        else:
            manifest["changes"][0]["before"] = "not base64!"
        data = json.dumps(manifest).encode("utf-8")
    journal.write_bytes(data)
    before = images(tmp_path)
    with pytest.raises(ReviewError, match="malformed journal"):
        service.undo(receipt.transaction_id)
    assert images(tmp_path) == before
    assert journal.read_bytes() == data


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


@pytest.fixture
def paused_transaction(monkeypatch):
    prepared, release = Event(), Event()
    save = review_journal._save

    def paused_save(path, manifest):
        save(path, manifest)
        if manifest["state"] == "prepared":
            prepared.set()
            assert release.wait(timeout=10)

    monkeypatch.setattr(review_journal, "_save", paused_save)
    yield prepared, release
    release.set()


def observe_transaction_exit(monkeypatch, finished):
    class ObservedTransactionLock(vault_lock.VaultLock):
        @contextmanager
        def hold(self):
            with super().hold():
                try:
                    yield
                finally:
                    # The protected body has exited; the real lock is released
                    # by the enclosing context, never by this observation.
                    finished.set()

    monkeypatch.setattr(consolidation, "VaultLock", ObservedTransactionLock)


def test_separate_public_writer_waits_for_transaction(
    tmp_path, monkeypatch, paused_transaction,
):
    _, service, question = seed(tmp_path)
    writer = VaultMemory({"vault_path": str(tmp_path)})
    prepared, release = paused_transaction
    blocked, finished, entered = Event(), Event(), Event()
    state = vault_lock.VaultLock(tmp_path)._state
    real_lock = state.lock
    resolve = writer._resolve_path

    class ObservedLock:
        def __enter__(self):
            if not real_lock.acquire(blocking=False):
                blocked.set()
                real_lock.acquire()
            return self

        def __exit__(self, *_exc):
            real_lock.release()

    def observed_resolve(*args):
        entered.set()
        assert blocked.is_set(), "writer bypassed the canonical lock"
        assert finished.is_set(), "writer entered before the transaction exited"
        return resolve(*args)

    observe_transaction_exit(monkeypatch, finished)
    monkeypatch.setattr(state, "lock", ObservedLock())
    monkeypatch.setattr(writer, "_resolve_path", observed_resolve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        applying = pool.submit(service.apply, question,
                               Answer(question.id, "merge", "Reviewed merged fact."))
        try:
            assert prepared.wait(timeout=10)
            writing = pool.submit(writer.write_note, "First policy",
                                  "Concurrent post-review fact.")
            assert blocked.wait(timeout=10), "writer never attempted the held lock"
            assert not entered.is_set()
        finally:
            release.set()
        applying.result(timeout=10)
        writing.result(timeout=10)
    assert entered.is_set()
    text = VaultMemory({"vault_path": str(tmp_path)}).get_note("First policy")
    assert "Concurrent post-review fact." in text


def process_writer(vault, signals, finished):
    """Observe a genuine contended OS acquisition in a spawned writer."""
    writer = VaultMemory({"vault_path": str(vault)})
    lock = vault_lock._lock_file
    resolve = writer._resolve_path
    contended = False

    def observed_lock(fd):
        nonlocal contended
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            contended = True
            signals.send("blocked")
        else:
            vault_lock._unlock_file(fd)
            signals.send("uncontended")
        lock(fd)

    def observed_resolve(*args):
        signals.send("entered")
        assert contended, "writer bypassed the canonical OS lock"
        assert finished.is_set(), "writer entered before the transaction exited"
        return resolve(*args)

    with signals, pytest.MonkeyPatch.context() as patch:
        patch.setattr(vault_lock, "_lock_file", observed_lock)
        patch.setattr(writer, "_resolve_path", observed_resolve)
        writer.write_note("First policy", "Concurrent process fact.")
        signals.send("done")


def test_separate_process_writer_waits_for_transaction(
    tmp_path, monkeypatch, paused_transaction,
):
    _, service, question = seed(tmp_path)
    prepared, release = paused_transaction
    context = multiprocessing.get_context("spawn")
    finished = context.Event()
    observe_transaction_exit(monkeypatch, finished)
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=process_writer, args=(tmp_path, sending, finished))
    with receiving, sending, ThreadPoolExecutor(max_workers=1) as pool:
        applying = pool.submit(service.apply, question,
                               Answer(question.id, "merge", "Reviewed merged fact."))
        try:
            assert prepared.wait(timeout=10)
            process.start()
            sending.close()
            assert receiving.poll(10), "process never attempted the held OS lock"
            assert receiving.recv() == "blocked"
            release.set()
            applying.result(timeout=10)
            assert receiving.poll(10), "process never entered the critical section"
            assert receiving.recv() == "entered"
            assert receiving.poll(10), "process did not finish its write"
            assert receiving.recv() == "done"
            process.join(timeout=10)
            assert process.exitcode == 0
        finally:
            release.set()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
                process.close()
    text = VaultMemory({"vault_path": str(tmp_path)}).get_note("First policy")
    assert "Concurrent process fact." in text


def test_unrelated_shared_topic_and_empty_notes_are_not_questions(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Rail tickets", "Rail tickets require a reservation.")
    memory.write_note("Rail history", "Rail engines were steam powered.")
    memory.write_note("Empty", "")
    assert Consolidation(tmp_path).questions() == ()


def test_lock_retry_waits_through_contention_without_raising():
    attempts = 0
    sleeps: list[float] = []

    def try_lock():
        nonlocal attempts
        attempts += 1
        if attempts <= 15:
            raise OSError(13, "contended")

    vault_lock._acquire_with_retry(try_lock, sleeps.append)
    assert attempts == 16
    assert len(sleeps) == 15
    assert all(0 < delay <= 0.5 for delay in sleeps)


def test_lock_retry_reraises_non_contention_errors_immediately():
    attempts = 0

    def try_lock():
        nonlocal attempts
        attempts += 1
        raise OSError(errno.EBADF, "bad file descriptor")

    def sleep(delay):
        raise AssertionError("slept on a non-contention error")

    with pytest.raises(OSError) as raised:
        vault_lock._acquire_with_retry(try_lock, sleep)
    assert raised.value.errno == errno.EBADF
    assert attempts == 1


def test_undecodable_note_is_skipped_and_reported(tmp_path):
    _, service, question = seed(tmp_path)
    bad = tmp_path / Path(question.first.path).parent / "latin1-note.md"
    bad.write_bytes(b"---\ntitle: Latin one\n---\n\ncaf\xe9 menu for review\n")
    before = bad.read_bytes()
    service = Consolidation(tmp_path)
    questions = service.questions()
    assert [q.id for q in questions] == [question.id]
    assert service.skipped == (bad.relative_to(tmp_path).as_posix(),)
    assert bad.read_bytes() == before
    assert Consolidation(tmp_path).skipped == ()


def test_non_numeric_version_merges_as_version_one(tmp_path):
    memory, service, question = seed(tmp_path)
    path = tmp_path / question.first.path
    text = path.read_text("utf-8")
    drafted = re.sub(r"(?m)^version:.*$", "version: draft", text)
    assert drafted != text
    path.write_text(drafted, "utf-8")
    question = service.questions()[0]
    service.apply(question, Answer(
        question.id, "merge", "Merged despite a draft version.", survivor="first",
    ))
    merged = memory.get_note(question.first.title)
    assert "version: 1\n" in merged
    assert "version: draft" not in merged
