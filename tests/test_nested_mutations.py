"""Nested vault mutation consumers: recursive fallback, archive subpaths,
exact path-bound questions and MCP restore/list/forget semantics."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from birkin_mnemosyne import VaultMemory, consolidation, frontmatter, mnemosyne
from birkin_mnemosyne.consolidation import Answer, Consolidation, NoteSnapshot, Question
from birkin_mnemosyne.mnemosyne import ARCHIVE_ZONE, Mnemosyne
from birkin_mnemosyne.review_journal import ReviewError


def _session(vault: Path, steps):
    pytest.importorskip("mcp")
    from mcp import Client

    from birkin_mnemosyne._mcp_app import create_server

    async def run():
        async with Client(create_server(vault)) as client:
            return await steps(client)
    return asyncio.run(run())


def call(vault: Path, name: str, args: dict[str, Any] | None = None):
    async def steps(client):
        return await client.call_tool(name, args or {})
    return _session(vault, steps)


def ok(vault: Path, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    r = call(vault, name, args)
    assert not r.is_error, r.content
    return r.structured_content


def err(vault: Path, name: str, args: dict[str, Any] | None = None) -> str:
    r = call(vault, name, args)
    assert r.is_error, r.structured_content
    return r.content[0].text


def remember(vault: Path, title: str, body: str, **kw) -> dict[str, Any]:
    return ok(vault, "memory_remember", {"title": title, "body": body, **kw})


def images(vault: Path) -> dict[str, bytes]:
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*.md")}


def _write(vault: Path, rel: str, body: str = "shared fixture body") -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ---------------- recursive cold fallback -----------------------------------


def test_cold_fallback_reaches_nested_notes_but_skips_hidden_and_cache(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "a/b/deep.md",
           "---\ntitle: Deep\ntype: fact\n---\nnested payload\n")
    _write(vault, ".trash/foo.md", "x")
    _write(vault, ".obsidian/x.md", "x")
    _write(vault, "node_modules/cache.md", "x")
    _write(vault, "__pycache__/byte.md", "x")
    m = VaultMemory({"vault_path": str(vault)})
    assert "nested payload" in m.get_note("Deep")
    assert m.get_note("foo") is None
    assert m.get_note("x") is None
    assert m.get_note("cache") is None
    assert m.get_note("byte") is None


def test_cold_fallback_never_follows_symlinked_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("secret outside file", encoding="utf-8")
    (vault / "link.md").symlink_to(outside / "leak.md")
    (vault / "dirlink").symlink_to(outside, target_is_directory=True)
    m = VaultMemory({"vault_path": str(vault)})
    assert m.get_note("leak") is None
    assert m.get_note("link") is None
    assert m.list_notes() == []


def test_purge_reaches_nested_notes_but_not_hidden_or_cache(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "knowledge/old.md",
           "---\ntype: topic\nexpires_at: 2000-01-01\n---\nstale\n")
    _write(vault, "a/b/deep.md",
           "---\ntype: topic\nexpires_at: 2000-01-01\n---\nstale\n")
    _write(vault, ".trash/t.md",
           "---\ntype: topic\nexpires_at: 2000-01-01\n---\nstale\n")
    _write(vault, "node_modules/c.md",
           "---\ntype: topic\nexpires_at: 2000-01-01\n---\nstale\n")
    m = VaultMemory({"vault_path": str(vault)})
    assert m.purge_expired() == 2
    assert not (vault / "knowledge" / "old.md").exists()
    assert not (vault / "a" / "b" / "deep.md").exists()
    assert (vault / ".trash" / "t.md").exists()
    assert (vault / "node_modules" / "c.md").exists()


# ---------------- nested placement and archive subpaths ---------------------


def test_new_notes_accept_nested_and_human_zone_parents(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    m = VaultMemory({"vault_path": str(vault)})
    p1 = m.write_note("Deep note", "nested body", zone="projects/2024")
    assert p1.relative_to(vault).as_posix() == "projects/2024/deep-note.md"
    p2 = m.write_note("Human folder", "body", zone="Deep Work/Team")
    assert p2.relative_to(vault).as_posix() == "Deep Work/Team/human-folder.md"
    assert m.search("nested body")[0]["zone"] == "projects/2024"
    assert m.list_notes()[0]["path"].is_file()


def test_rezone_to_archive_preserves_complete_source_subpath(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    m = VaultMemory({"vault_path": str(vault)})
    m.write_note("Filed", "body", zone="projects/2024/roadmap")
    m.rezone("Filed", ARCHIVE_ZONE)
    p = vault / "_archive" / "projects" / "2024" / "roadmap" / "filed.md"
    assert p.is_file()
    entry = Mnemosyne(vault).entries()["filed"]
    assert entry["zone"] == "_archive/projects/2024/roadmap"
    assert m.list_notes() == []
    assert "Filed" not in m.render()
    hits = m.dex.search("body", zone=ARCHIVE_ZONE)
    assert [h["slug"] for h in hits] == ["filed"]


def test_zone_cap_ignores_archive_descendants(tmp_path: Path) -> None:
    from birkin_mnemosyne.mnemosyne import MAX_ZONES
    vault = tmp_path / "vault"
    m = VaultMemory({"vault_path": str(vault)})
    for i in range(MAX_ZONES):
        m.write_note(f"Cap {i}", "x", zone=f"z{i}", source="seed")
    with pytest.raises(ValueError, match="zone cap"):
        m.write_note("Too many", "x", zone="brand-new", source="seed")
    m.rezone("Cap 0", ARCHIVE_ZONE)
    m.write_note("Fits now", "x", zone="replacement", source="seed")
    assert (vault / "replacement" / "fits-now.md").is_file()


# ---------------- consolidation: nested archive and exact binding -----------


def _seed_nested_duplicates(vault: Path):
    m = VaultMemory({"vault_path": str(vault)})
    m.write_note("Rule one", "Review every release before publishing.",
                 zone="a/b", source="chat:one")
    m.write_note("Rule two", "Review every release before publishing.",
                 zone="a/b", source="chat:two")
    return m, Consolidation(vault)


def test_nested_drop_archives_under_complete_subpath_and_undo_restores(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _, service = _seed_nested_duplicates(vault)
    before = images(vault)
    question, = service.questions()
    assert question.first.path.startswith("a/b/")
    retired = question.second.path
    receipt = service.apply(question, Answer(question.id, "keep-first"))
    archived = vault / "_archive" / retired
    assert archived.is_file()
    assert archived.read_bytes() == before[retired]
    assert not (vault / retired).exists()
    service.undo(receipt.transaction_id)
    assert images(vault) == before
    assert (vault / retired).read_bytes() == before[retired]


def test_nested_merge_keeps_survivor_and_archives_full_subpath(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _, service = _seed_nested_duplicates(vault)
    before = images(vault)
    question, = service.questions()
    receipt = service.apply(
        question, Answer(question.id, "merge",
                         "Review releases; approved.",
                         survivor="second"))
    survivor = question.second.path
    retired = question.first.path
    assert (vault / "_archive" / retired).read_bytes() == before[retired]
    assert "Review releases; approved." in (vault / survivor).read_text("utf-8")
    service.undo(receipt.transaction_id)
    assert images(vault) == before


def test_questions_exclude_archive_descendants(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    m, service = _seed_nested_duplicates(vault)
    question, = service.questions()
    m.rezone("Rule two", ARCHIVE_ZONE)
    assert service.questions() == ()
    archived = vault / "_archive" / question.second.path
    assert archived.is_file()


def _snapshot_of(vault: Path, rel: str) -> NoteSnapshot:
    raw = (vault / rel).read_bytes()
    _, body = frontmatter.parse(raw.decode("utf-8"))
    return NoteSnapshot(rel, rel.rsplit("/", 1)[-1].removesuffix(".md"),
                        hashlib.sha256(raw).hexdigest(), body.strip(), ())


def _paired(vault: Path, rel_a: str, rel_b: str) -> Question:
    a, b = _snapshot_of(vault, rel_a), _snapshot_of(vault, rel_b)
    return Question(consolidation._question_id(a, b), a, b, "duplicate", 1.0)


def test_path_bound_question_keeps_exact_path_after_duplicate_winner_changes(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _, service = _seed_nested_duplicates(vault)
    question, = service.questions()
    offered = vault / question.first.path
    collision = _write(vault, f"newer/copies/{offered.name}", "unrelated newer note")
    stamp = offered.stat().st_mtime + 1000
    os.utime(collision, (stamp, stamp))
    service.dex.refresh()
    assert service.dex.entries()[offered.stem]["rel"] == collision.relative_to(vault).as_posix()
    before = images(vault)
    receipt = service.apply(question, Answer(question.id, "drop-first"))
    assert (vault / "_archive" / question.first.path).read_bytes() == before[question.first.path]
    assert collision.read_bytes() == b"unrelated newer note"
    assert not offered.exists()
    service.undo(receipt.transaction_id)
    assert images(vault) == before


@pytest.mark.parametrize("linked_parent", [False, True])
def test_path_bound_question_refuses_symlink_replacements(
        tmp_path: Path, linked_parent: bool) -> None:
    vault = tmp_path / "vault"
    _, service = _seed_nested_duplicates(vault)
    question, = service.questions()
    offered = vault / question.first.path
    if linked_parent:
        relocated = vault / "relocated"
        shutil.move(str(offered.parent), relocated)
        offered.parent.symlink_to(relocated, target_is_directory=True)
    else:
        target = vault / "replacement.md"
        target.write_bytes(offered.read_bytes())
        offered.unlink()
        offered.symlink_to(target)
    before = images(vault)
    with pytest.raises(ReviewError):
        service.apply(question, Answer(question.id, "drop-first"))
    assert images(vault) == before


def test_path_bound_question_refuses_archived_or_hidden_snapshots(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    m, service = _seed_nested_duplicates(vault)
    question, = service.questions()
    m.rezone("Rule one", ARCHIVE_ZONE)
    with pytest.raises(ReviewError):
        service.apply(question, Answer(question.id, "keep-second"))
    _write(vault, ".trash/ghost.md", "ghost body")
    _write(vault, "live.md", "live body")
    forged = _paired(vault, ".trash/ghost.md", "live.md")
    with pytest.raises(ReviewError):
        service.apply(forged, Answer(forged.id, "keep-second"))
    assert (vault / ".trash" / "ghost.md").is_file()


def test_retire_questions_never_offer_archive_descendants(tmp_path: Path) -> None:
    from birkin_mnemosyne.capacity import CapacityBudget
    vault = tmp_path / "vault"
    m = VaultMemory({"vault_path": str(vault)})
    m.write_note("Old address", "Lived on Elm street.", zone="home",
                 links=["New address"], source="seed")
    m.write_note("New address", "Lives on Oak avenue.", zone="home",
                 links=["Old address"], source="seed")
    m.write_note("Third address", "Lives on Pine lane.", zone="home",
                 links=["New address"], source="seed")
    m.rezone("Old address", ARCHIVE_ZONE)
    service = Consolidation(vault)
    questions = service.retire_questions(10, CapacityBudget(1, None))
    assert questions
    assert all("_archive" not in q.note.path for q in questions)


# ---------------- MCP: forget / list / restore ------------------------------


def _mcp_seed_nested(vault: Path) -> None:
    remember(vault, "Budget plan", "annual budget figures",
             zone="finance", labels=["project:Alpha"])
    remember(vault, "Deep rule", "nested policy body",
             zone="work/2024", labels=["topic:Inside"])


@pytest.mark.parametrize("mutation", ["memory_forget", "memory_curate"])
def test_same_mcp_connection_sees_archive_before_scan_ttl(
        tmp_path: Path, monkeypatch, mutation: str) -> None:
    monkeypatch.setattr(mnemosyne, "_clock", lambda: 100.0)
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)

    async def steps(client):
        before = await client.call_tool("memory_search", {"query": "nested policy"})
        assert not before.is_error
        assert [hit["slug"] for hit in before.structured_content["results"]] == ["deep-rule"]
        arguments = (
            {"note": "deep-rule", "confirm": True}
            if mutation == "memory_forget" else
            {"plan": {"plan_version": 1, "summary": "Archive the nested fixture",
                      "ops": [{"op": "archive", "slug": "deep-rule"}]}, "apply": True}
        )
        changed = await client.call_tool(mutation, arguments)
        assert not changed.is_error, changed.content
        assert (vault / "_archive/work/2024/deep-rule.md").is_file()
        after = await client.call_tool("memory_search", {"query": "nested policy"})
        assert not after.is_error
        assert after.structured_content["results"] == []

    _session(vault, steps)


def test_mcp_list_excludes_archive_descendants_and_scopes_archive(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)
    ok(vault, "memory_forget", {"note": "deep-rule", "confirm": True})
    listed = ok(vault, "memory_list")["notes"]
    assert [n["slug"] for n in listed] == ["budget-plan"]
    assert ok(vault, "memory_list")["label_counts"] == {"project:Alpha": 1}
    archived = ok(vault, "memory_list", {"zone": "_archive"})["notes"]
    assert [n["slug"] for n in archived] == ["deep-rule"]
    assert archived[0]["zone"] == "_archive/work/2024"
    assert ok(vault, "memory_search", {"query": "nested"})["results"] == []
    hits = ok(vault, "memory_search",
              {"query": "nested", "zone": "_archive"})["results"]
    assert [h["slug"] for h in hits] == ["deep-rule"]
    assert (vault / "_archive" / "work" / "2024" / "deep-rule.md").is_file()


def test_mcp_forget_refuses_already_forgotten_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)
    ok(vault, "memory_forget", {"note": "budget-plan", "confirm": True})
    message = err(vault, "memory_forget",
                  {"note": "budget-plan", "confirm": True})
    assert "already forgotten" in message


def test_mcp_restore_default_inbox_and_explicit_nested_target(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)
    ok(vault, "memory_forget", {"note": "deep-rule", "confirm": True})
    out = ok(vault, "memory_restore", {"note": "deep-rule"})
    assert out["zone"] == "inbox" and out["path"] == "deep-rule.md"
    assert (vault / "deep-rule.md").is_file()
    assert "not archived" in err(vault, "memory_restore", {"note": "deep-rule"})
    ok(vault, "memory_forget", {"note": "deep-rule", "confirm": True})
    out = ok(vault, "memory_restore",
             {"note": "deep-rule", "zone": "projects/2024"})
    assert out["path"] == "projects/2024/deep-rule.md"
    assert (vault / "projects" / "2024" / "deep-rule.md").is_file()


def test_mcp_restore_refuses_archive_targets_and_unsafe_zones(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)
    ok(vault, "memory_forget", {"note": "Deep rule", "confirm": True})
    assert "restore target" in err(vault, "memory_restore",
                                   {"note": "deep-rule", "zone": "_archive"})
    assert "_archive" in err(vault, "memory_restore",
                             {"note": "deep-rule", "zone": "work/_ArChIvE"})
    assert "invalid zone" in err(vault, "memory_restore",
                                 {"note": "deep-rule", "zone": "a\\b"})
    assert "invalid zone" in err(vault, "memory_restore",
                                 {"note": "deep-rule", "zone": "C:\\x"})


def test_mcp_remember_accepts_nested_zone_and_refuses_unsafe(
        tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    out = remember(vault, "Nested new", "body", zone="projects/2024")
    assert out["path"] == "projects/2024/nested-new.md"
    message = err(vault, "memory_remember",
                  {"title": "Bad", "body": "x", "zone": "a\\b"})
    assert "invalid zone" in message
    message = err(vault, "memory_remember",
                  {"title": "Bad", "body": "x", "zone": "node_modules"})
    assert "invalid zone" in message
    message = err(vault, "memory_remember",
                  {"title": "Bad", "body": "x", "zone": "work/_archive"})
    assert "_archive" in message
    assert list(vault.rglob("bad.md")) == []


def test_mcp_get_note_never_reaches_cache_or_hidden_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _mcp_seed_nested(vault)
    _write(vault, "node_modules/secret.md",
           "---\ntitle: Secret\ntype: fact\n---\ncache payload\n")
    _write(vault, ".trash/ghost.md",
           "---\ntitle: Ghost\ntype: fact\n---\nhidden payload\n")
    assert "no note" in err(vault, "memory_get_note", {"note": "secret"})
    assert "no note" in err(vault, "memory_get_note", {"note": "ghost"})
    assert ok(vault, "memory_get_note", {"note": "budget-plan"})["title"] \
        == "Budget plan"
