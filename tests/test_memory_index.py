"""Durable routing is never an ordinary note or an evictable search result."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from birkin_mnemosyne import (
    Answer,
    Consolidation,
    MemoryIndex,
    MemoryIndexError,
    StartupReader,
    VaultMemory,
    evaluate_plan,
)
from birkin_mnemosyne.capacity import DEFAULT_BUDGET, capacity_report
from birkin_mnemosyne.memory_index import INDEX_SOURCE
from birkin_mnemosyne.review_journal import Change, ReviewError, commit
from birkin_mnemosyne.vault_lock import VaultLock


def seed(root, count=1, **kwargs):
    index = MemoryIndex(root, **kwargs)
    for number in range(count):
        path = root / f"topic-{number}.md"
        path.write_bytes(f"# Topic {number}\nRule: keep {number}.\r\n".encode())
        index.register(f"When doing task {number}", path.name)
    return index


def test_disabled_reads_do_not_create_state(tmp_path):
    index = MemoryIndex(tmp_path)
    assert not index.read().enabled
    assert index.render() == ""
    assert list(tmp_path.iterdir()) == []


def test_registration_is_additive_idempotent_and_survives_restart(tmp_path):
    index = seed(tmp_path, 12)
    original = index.path.read_bytes()
    index.register("When doing task 0", "topic-0.md")
    assert index.path.read_bytes() == original
    restarted = MemoryIndex(tmp_path).read()
    assert len(restarted.entries) == 12
    assert all(f"When doing task {i} -> topic-{i}.md" in restarted.context for i in range(12))


def test_over_budget_keeps_every_entry_and_counts_warning(tmp_path):
    index = seed(tmp_path, 12)
    view = index.register("When doing task 0", "topic-0.md", max_tokens=1)
    assert view.over_budget and view.warnings
    assert view.estimated_tokens == (len(view.context.encode("utf-8")) + 3) // 4
    assert len(view.entries) == 12
    for i in range(12):
        assert f"When doing task {i} -> topic-{i}.md" in view.context


def test_exact_trigger_opens_only_its_complete_document(tmp_path):
    index = seed(tmp_path, 3)
    result = index.open("when doing task 1")
    assert result.matched_by == "exact"
    assert [(d.path, d.content) for d in result.documents] == [
        ("topic-1.md", "# Topic 1\nRule: keep 1.\r\n")]


def test_one_trigger_can_open_multiple_documents_without_duplicates(tmp_path):
    index = seed(tmp_path, 2)
    index.register("release", "topic-0.md")
    index.register("release", "topic-1.md")
    result = index.open("release")
    assert [d.path for d in result.documents] == ["topic-0.md", "topic-1.md"]


def test_unmatched_trigger_falls_back_to_search(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Telescope", "Calibration uses a silver collimator.")
    result = MemoryIndex(tmp_path).open("collimator")
    assert result.matched_by == "search"
    assert result.documents[0].path == "knowledge/telescope.md"
    assert "silver collimator" in result.documents[0].content
    assert MemoryIndex(tmp_path).open("qxzunrecorded").documents == ()


def test_note_identifier_resolves_before_storage(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Tea order", "Serve jasmine.")
    view = MemoryIndex(tmp_path).register("ordering tea", "tea-order")
    assert view.entries[0].document == "knowledge/tea-order.md"


@pytest.mark.parametrize("document", [
    "../outside.md", ".hidden.md", "topic/../outside.md",
    "/outside.md", "C:\\outside.md", "_archive/old.md", "topic//other.md",
])
def test_unsafe_paths_fail_without_creating_index(tmp_path, document):
    with pytest.raises(MemoryIndexError):
        MemoryIndex(tmp_path).register("work", document)
    assert not (tmp_path / ".mnemosyne-memory-index").exists()


@pytest.mark.parametrize("trigger", [
    "", " ", "hello\nworld", "hello\x00world", " hello", "hello\u2028world",
])
def test_invalid_trigger_cannot_modify_existing_entries(tmp_path, trigger):
    index = seed(tmp_path)
    before = index.path.read_bytes()
    with pytest.raises(MemoryIndexError):
        index.register(trigger, "topic-0.md")
    assert index.path.read_bytes() == before


@pytest.mark.parametrize("budget", [0, -1, True, 1.5])
def test_invalid_budget_cannot_modify_existing_entries(tmp_path, budget):
    index = seed(tmp_path)
    before = index.path.read_bytes()
    with pytest.raises(MemoryIndexError):
        index.register("task", "topic-0.md", max_tokens=budget)
    assert index.path.read_bytes() == before


def test_enabled_missing_state_fails_after_restart(tmp_path):
    index = seed(tmp_path)
    index.path.unlink()
    with pytest.raises(MemoryIndexError):
        MemoryIndex(tmp_path).render()


def test_required_mode_detects_missing_marker(tmp_path):
    with pytest.raises(MemoryIndexError):
        MemoryIndex(tmp_path, required=True).render()


def test_live_reader_remembers_index_was_enabled(tmp_path):
    index = seed(tmp_path)
    index.path.unlink()
    index.directory.rmdir()
    with pytest.raises(MemoryIndexError):
        index.render()


@pytest.mark.parametrize("record", [
    "{}", "null", '{"version":1,"max_tokens":2000,"entries":[],"entries":[]}',
    '{"version":1,"max_tokens":true,"entries":[]}',
    '{"version":1,"max_tokens":2000,"entries":[{}]}',
])
def test_invalid_state_never_becomes_empty_success(tmp_path, record):
    index = seed(tmp_path)
    index.path.write_text(record, encoding="utf-8")
    with pytest.raises(MemoryIndexError):
        MemoryIndex(tmp_path).read()


def test_concurrent_additions_never_lose_entries(tmp_path):
    (tmp_path / "topic.md").write_text("Retain all mappings.", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda i: MemoryIndex(tmp_path).register(f"task {i}", "topic.md"),
            range(16),
        ))
    assert {e.trigger for e in MemoryIndex(tmp_path).read().entries} == {
        f"task {i}" for i in range(16)}


def test_dangling_exact_mapping_fails_instead_of_searching_elsewhere(tmp_path):
    index = seed(tmp_path)
    (tmp_path / "topic-0.md").unlink()
    with pytest.raises(MemoryIndexError):
        index.open("When doing task 0")


def test_generic_lifecycle_operations_cannot_touch_index_state(tmp_path):
    index = seed(tmp_path, 2)
    memory = VaultMemory({"vault_path": str(tmp_path)})
    expired = memory.write_note("Expired", "expire")
    expired.write_bytes(b"---\ntitle: Expired\nexpires_at: 2000-01-01\n---\nexpire\n")
    before = index.path.read_bytes()
    memory.purge_expired()
    memory.reindex()
    memory.rezone("topic-0", "work")
    for target in ("index", ".mnemosyne-memory-index/index.json"):
        with pytest.raises(ValueError):
            memory.rezone(target, "_archive")
    assert index.path.read_bytes() == before
    assert len(json.loads(before)["entries"]) == 2


def test_startup_and_zero_limit_digest_include_every_registered_entry(tmp_path):
    index = seed(tmp_path, 16)
    index.register("When doing task 0", "topic-0.md", max_tokens=1)
    digest = VaultMemory({"vault_path": str(tmp_path)}).render(limit=0)
    bundle = StartupReader(tmp_path).read([])
    payload = json.loads(bundle.context)
    context = "".join(b["text"] for b in payload["blocks"])
    assert bundle.coverage.complete
    assert bundle.estimated_tokens == (len(bundle.context.encode("utf-8")) + 3) // 4
    assert {f["path"] for f in payload["files"]} == {INDEX_SOURCE}
    for i in range(16):
        mapping = f"When doing task {i} -> topic-{i}.md"
        assert mapping in digest
        assert mapping in context
        assert f"Rule: keep {i}." not in context


def test_verifier_rejects_a_dropped_entry_even_with_a_rewritten_certificate(tmp_path):
    seed(tmp_path, 2)
    reader = StartupReader(tmp_path)
    payload = json.loads(reader.read([]).context)
    block = next(b for b in payload["blocks"] if "When doing task 1" in b["text"])
    block["text"] = block["text"].replace(
        "- When doing task 1 -> topic-1.md\n", "")
    from birkin_mnemosyne.startup_coverage import digest
    block["sha256"] = digest(block["text"].encode())
    assert not reader.verify(json.dumps(payload), []).complete


def test_startup_index_uses_vault_when_identity_root_is_separate(tmp_path):
    vault, identity = tmp_path / "vault", tmp_path / "identity"
    vault.mkdir()
    identity.mkdir()
    seed(vault)
    (identity / "MODE.md").write_text("Global guard.", encoding="utf-8")
    bundle = StartupReader(identity, memory_index_root=vault).read(["MODE.md"])
    assert {f["path"] for f in json.loads(bundle.context)["files"]} == {
        "MODE.md", INDEX_SOURCE}
    assert "When doing task 0" in bundle.context


def test_startup_refuses_missing_required_index(tmp_path):
    (tmp_path / "MODE.md").write_text("Global guard.", encoding="utf-8")
    with pytest.raises(MemoryIndexError):
        StartupReader(tmp_path, require_index=True).read(["MODE.md"])


def test_capacity_reports_complete_index_cost_and_never_retires_entries(tmp_path):
    index = seed(tmp_path, 3)
    index.register("When doing task 0", "topic-0.md", max_tokens=1)
    before = index.path.read_bytes()
    memory = VaultMemory({"vault_path": str(tmp_path)})
    report = capacity_report(memory.dex, DEFAULT_BUDGET)
    assert report["always_loaded"]["index_entries"] == 3
    assert report["always_loaded"]["estimated_tokens"] == index.read().estimated_tokens
    assert report["always_loaded"]["over_budget"]
    assert report["warnings"]
    assert index.path.read_bytes() == before


def test_curation_and_consolidation_do_not_own_routing_state(tmp_path):
    index = seed(tmp_path)
    memory = VaultMemory({"vault_path": str(tmp_path)})
    for name in ("First rule", "Second rule"):
        memory.write_note(name, "Backups need a verified restore receipt.")
    before = index.path.read_bytes()
    outcome = evaluate_plan(tmp_path, {
        "plan_version": 1,
        "ops": [{"op": "archive", "slug": "index"},
                {"op": "rezone", "slug": ".mnemosyne-memory-index/index.json", "zone": "work"}],
    }, apply=True)
    assert not outcome.accepted
    service = Consolidation(tmp_path)
    question = next(q for q in service.questions()
                    if {q.first.title, q.second.title} == {"First rule", "Second rule"})
    receipt = service.apply(question, Answer(
        question.id, "merge", "Backups need a verified restore receipt."))
    service.undo(receipt.transaction_id)
    assert index.path.read_bytes() == before
    assert index.read().entries[0].document == "topic-0.md"


def test_direct_review_journal_refuses_index_replacement(tmp_path):
    index = seed(tmp_path)
    before = index.path.read_bytes()
    relative = index.path.relative_to(tmp_path).as_posix()
    with VaultLock(tmp_path).hold(), pytest.raises(ReviewError):
        commit(tmp_path, "forged", "merge", "", "first",
               (Change(relative, relative, before, b"{}"),))
    assert index.path.read_bytes() == before


def test_symlink_cannot_redirect_index_state(tmp_path):
    index = seed(tmp_path)
    target = tmp_path / "outside.json"
    target.write_bytes(index.path.read_bytes())
    index.path.unlink()
    try:
        index.path.symlink_to(target)
    except OSError:
        # Windows runners may forbid creating symlinks; the path predicate is
        # exercised separately by the path-confined startup reader suite.
        pytest.skip("this OS account cannot create symlinks")
    with pytest.raises(MemoryIndexError):
        index.read()
