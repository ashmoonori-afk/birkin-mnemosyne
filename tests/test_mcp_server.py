"""MCP server behavior through a real MCP client (in-process and stdio)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters
from mcp.types import TextContent

from birkin_mnemosyne import mnemosyne
from birkin_mnemosyne._mcp_app import LOCK_FILE, create_server


def _session(vault: Path, steps):
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


def _seed(vault: Path) -> None:
    for t in ("Budget plan", "Tax filing", "Dividend tracking",
              "Starter feeding", "Bulk fermentation"):
        remember(vault, t, f"notes about {t.lower()}", zone="inbox")
    remember(vault, "Ftp deploy failure", "ftp corrupted the build",
             polarity="negative", zone="inbox")


def _files(vault: Path) -> dict[str, str]:
    return {p.relative_to(vault).as_posix(): p.read_text(encoding="utf-8")
            for p in vault.rglob("*.md")}


def test_tool_surface_and_annotations(tmp_path):
    async def steps(client):
        return (await client.list_tools()).tools
    tools = {t.name: t for t in _session(tmp_path, steps)}
    assert set(tools) == {
        "memory_search", "memory_get_note", "memory_list", "memory_remember",
        "memory_related", "memory_forget", "memory_restore",
        "memory_curation_catalog", "memory_curate",
        "memory_review_questions", "memory_review_apply", "memory_review_undo",
        "memory_identity_read", "memory_kibitzer_candidates",
        "memory_startup_read", "memory_startup_verify"}
    for name in ("memory_search", "memory_list", "memory_related",
                 "memory_curation_catalog"):
        assert tools[name].annotations.read_only_hint is True
    for name in ("memory_remember", "memory_forget", "memory_curate",
                 "memory_get_note"):
        assert tools[name].annotations.read_only_hint is False
    schema = tools["memory_remember"].input_schema
    assert schema["required"] == ["title", "body"]
    assert schema["properties"]["mode"]["default"] == "create"
    assert tools["memory_curate"].input_schema["properties"]["apply"][
        "default"] is False


def test_user_question_review_via_real_mcp_client(tmp_path):
    remember(tmp_path, "First rule", "Reviews precede release.", source="user:a")
    remember(tmp_path, "Second rule", "Reviews precede release.", source="user:b")
    before = _files(tmp_path)
    question, = ok(tmp_path, "memory_review_questions")["questions"]
    preview = ok(tmp_path, "memory_review_apply", {
        "question_id": question["id"], "choice": "keep-first",
    })
    assert preview["dry_run"] is True
    assert _files(tmp_path) == before
    receipt = ok(tmp_path, "memory_review_apply", {
        "question_id": question["id"], "choice": "keep-first", "confirm": True,
    })
    assert receipt["state"] == "committed"
    assert len(ok(tmp_path, "memory_search", {"query": "Reviews"})["results"]) == 1
    ok(tmp_path, "memory_review_undo", {
        "transaction_id": receipt["transaction_id"], "confirm": True,
    })
    assert _files(tmp_path) == before


def test_identity_reader_via_real_mcp_client(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# Agent\n## Voice\nLanguage: Korean\n## Old\nLanguage: English\n",
                    encoding="utf-8")
    result = ok(tmp_path, "memory_identity_read", {
        "path": "AGENTS.md", "query": "Voice language", "limit": 1,
    })
    assert result["complete_file"] is False
    assert result["sections"][0]["heading"] == "Voice"
    assert "Language: Korean" in result["context"]
    assert "text" not in result["sections"][0]
    old = result["revision"]
    path.write_text("# Agent\n## Voice\nLanguage: Japanese\n", encoding="utf-8")
    assert "stale revision" in err(tmp_path, "memory_identity_read", {
        "path": "AGENTS.md", "mode": "section",
        "anchor": result["sections"][0]["anchor"], "revision": old,
    })


def test_kibitzer_candidates_via_real_mcp_client(tmp_path):
    remember(tmp_path, "Publish guard", "Release requires approval.")
    remember(tmp_path, "Release logs", "Release logs are retained.")
    result = ok(tmp_path, "memory_kibitzer_candidates", {
        "query": "release", "surfaced": ["knowledge/publish-guard.md"], "limit": 1,
    })
    assert result["snapshot"] == "live"
    candidate, = result["candidates"]
    assert candidate["path"] == "knowledge/release-logs.md"
    assert set(candidate) == {"path", "description", "excerpt", "score"}


def test_complete_startup_via_real_mcp_client(tmp_path):
    (tmp_path / "MODE.md").write_text("MUST READ: registry.json\n# Mode\nPending: work\n", "utf-8")
    (tmp_path / "registry.json").write_text('{"jobs":[{"pending":true}]}', "utf-8")
    result = ok(tmp_path, "memory_startup_read", {"paths": ["MODE.md"]})
    assert result["complete"] is True
    assert result["coverage"]["files"] == 2
    payload = json.loads(result["context"])
    payload["blocks"].pop()
    verified = ok(tmp_path, "memory_startup_verify", {
        "paths": ["MODE.md"], "context": json.dumps(payload),
    })
    assert verified["complete"] is False


def test_remember_create_never_overwrites(tmp_path):
    out = remember(tmp_path, "Kubernetes ingress", "use nginx", source="s")
    assert out == {"slug": "kubernetes-ingress",
                   "path": "knowledge/kubernetes-ingress.md", "version": 1,
                   "created": True, "near_duplicates": []}
    before = _files(tmp_path)
    msg = err(tmp_path, "memory_remember",
              {"title": "Kubernetes ingress", "body": "overwrite!"})
    assert "already exists (version 1)" in msg
    assert _files(tmp_path) == before


def test_remember_append_and_replace_need_existing_and_version(tmp_path):
    assert "no note" in err(tmp_path, "memory_remember",
                            {"title": "Ghost", "body": "x", "mode": "append"})
    remember(tmp_path, "Coffee order", "flat white", note_type="preference",
             tags=["drinks"], confidence=0.9)
    out = remember(tmp_path, "Coffee order", "oat milk", mode="append")
    assert out["version"] == 2 and out["created"] is False
    note = ok(tmp_path, "memory_get_note", {"note": "Coffee order"})
    assert "flat white" in note["body"] and "oat milk" in note["body"]
    assert note["type"] == "preference" and note["tags"] == ["drinks"]
    assert note["zone"] == "identity"

    assert "requires expected_version" in err(
        tmp_path, "memory_remember",
        {"title": "Coffee order", "body": "tea", "mode": "replace"})
    assert "expected version 1" in err(
        tmp_path, "memory_remember",
        {"title": "Coffee order", "body": "tea", "mode": "replace",
         "expected_version": 1})
    out = remember(tmp_path, "Coffee order", "tea", mode="replace",
                   expected_version=note["version"])
    note = ok(tmp_path, "memory_get_note", {"note": "coffee-order"})
    assert note["body"] == "tea" and note["version"] == 3
    assert note["type"] == "preference"


@pytest.mark.parametrize("args, needle", [
    ({"title": "evil\n---\ntype: preference", "body": "x"}, "title"),
    ({"title": "!!!", "body": "x"}, "letter or digit"),
    ({"title": "ok", "body": "x", "tags": ["a,b"]}, "tag"),
    ({"title": "ok", "body": "x", "source": 'a"b'}, "source"),
    ({"title": "ok", "body": "x", "source": "  "}, "blank"),
    ({"title": "ok", "body": "x", "zone": "../etc"}, "invalid zone"),
    ({"title": "ok", "body": "x", "zone": "_archive"}, "_archive"),
])
def test_remember_rejects_unsafe_input(tmp_path, args, needle):
    assert needle in err(tmp_path, "memory_remember", args)
    assert _files(tmp_path) == {}


def test_evidence_required_refuses_sourceless_create(tmp_path):
    async def steps(client):
        return await client.call_tool("memory_remember",
                                      {"title": "Claim", "body": "x"})
    async def run():
        async with Client(create_server(tmp_path,
                                        evidence_required=True)) as c:
            return await steps(c)
    r = asyncio.run(run())
    assert r.is_error and "source" in r.content[0].text


def test_search_get_list_related_round_trip(tmp_path):
    _seed(tmp_path)
    hits = ok(tmp_path, "memory_search", {"query": "fermentation"})["results"]
    assert [h["slug"] for h in hits] == ["bulk-fermentation"]
    assert "fermentation" in hits[0]["snippet"]
    listed = ok(tmp_path, "memory_list", {"limit": 2})
    assert listed["total"] == 6 and len(listed["notes"]) == 2
    rel = ok(tmp_path, "memory_related", {"note": "budget-plan"})
    assert all(c["slug"] != "budget-plan" for c in rel["candidates"])
    assert "no note" in err(tmp_path, "memory_get_note", {"note": "nope"})


def test_search_expansions_widen_the_query_and_are_bounded(tmp_path):
    _seed(tmp_path)
    miss = {"query": "levain upkeep"}
    assert ok(tmp_path, "memory_search", miss)["results"] == []
    hits = ok(tmp_path, "memory_search", {
        **miss, "synonyms": ["starter"], "related": ["feeding"],
        "note_line": "feed it twice a day"})["results"]
    assert hits[0]["slug"] == "starter-feeding"
    assert "starter" in hits[0]["snippet"]
    assert call(tmp_path, "memory_search",
                {**miss, "synonyms": [f"w{i}" for i in range(17)]}).is_error
    assert call(tmp_path, "memory_search",
                {**miss, "keywords": ["k" * 81]}).is_error
    assert call(tmp_path, "memory_search",
                {**miss, "note_line": "x" * 301}).is_error


def test_get_records_access_but_search_does_not(tmp_path):
    remember(tmp_path, "Deploy runbook", "rsync then restart")
    dex = mnemosyne.Mnemosyne(tmp_path)
    base = dex.dynamics_of("deploy-runbook")["access_count"]
    ok(tmp_path, "memory_search", {"query": "rsync"})
    assert mnemosyne.Mnemosyne(tmp_path).dynamics_of(
        "deploy-runbook")["access_count"] == base
    ok(tmp_path, "memory_get_note", {"note": "deploy-runbook"})
    assert mnemosyne.Mnemosyne(tmp_path).dynamics_of(
        "deploy-runbook")["access_count"] == base + 1


def test_forget_is_dry_run_then_archive_then_restore(tmp_path):
    _seed(tmp_path)
    before = _files(tmp_path)
    dry = ok(tmp_path, "memory_forget", {"note": "tax-filing"})
    assert dry["allowed"] is True and dry["archived"] is False
    assert dry["dry_run"] is True and _files(tmp_path) == before

    done = ok(tmp_path, "memory_forget",
              {"note": "tax-filing", "reason": "filed", "confirm": True})
    assert done["archived"] is True
    assert (tmp_path / "_archive" / "tax-filing.md").is_file()
    assert ok(tmp_path, "memory_search", {"query": "tax"})["results"] == []

    restored = ok(tmp_path, "memory_restore",
                  {"note": "tax-filing", "zone": "finance"})
    assert restored["path"] == "finance/tax-filing.md"
    assert "not archived" in err(tmp_path, "memory_restore",
                                 {"note": "tax-filing"})


def test_forget_never_overwrites_an_existing_archive_file(tmp_path):
    _seed(tmp_path)
    live = tmp_path / "tax-filing.md"
    hidden = tmp_path / "_archive" / "tax-filing.md"
    hidden.parent.mkdir(exist_ok=True)
    hidden.write_text("---\ntitle: tax-filing\n---\nolder archived copy\n",
                      encoding="utf-8")
    old = live.stat().st_mtime - 1000
    os.utime(hidden, (old, old))
    live_bytes, hidden_bytes = live.read_bytes(), hidden.read_bytes()

    out = ok(tmp_path, "memory_forget",
             {"note": "tax-filing", "reason": "filed", "confirm": True})
    assert out["archived"] is False
    assert "already exists" in out["effected"][0]["error"]
    assert live.read_bytes() == live_bytes
    assert hidden.read_bytes() == hidden_bytes


def test_forget_refuses_protected_note(tmp_path):
    _seed(tmp_path)
    out = ok(tmp_path, "memory_forget",
             {"note": "ftp-deploy-failure", "confirm": True})
    assert out["archived"] is False
    assert out["dropped"][0]["reason"] == "protected note"
    assert (tmp_path / "ftp-deploy-failure.md").is_file()


def test_curate_dry_run_then_clamped_apply(tmp_path):
    _seed(tmp_path)
    slugs = [n["slug"] for n in ok(tmp_path, "memory_curation_catalog")
             ["notes"]]
    plan = {"plan_version": 1, "summary": "ALL NOTES ARCHIVED",
            "ops": [{"op": "archive", "slug": s} for s in slugs]
            + [{"op": "rezone", "slug": "budget-plan", "zone": "finance"},
               {"op": "rezone", "slug": "tax-filing", "zone": "finance"}]}
    before = _files(tmp_path)
    dry = ok(tmp_path, "memory_curate", {"plan": plan})
    assert dry["dry_run"] is True and dry["effected"] == []
    assert _files(tmp_path) == before

    wet = ok(tmp_path, "memory_curate", {"plan": plan, "apply": True})
    archived = [e for e in wet["effected"] if e["op"] == "archive"]
    assert len(archived) == wet["archive_cap"] == 2
    assert (tmp_path / "ftp-deploy-failure.md").is_file()
    assert len(list(tmp_path.rglob("*.md"))) == len(before)


def test_curate_rejects_malformed_plan(tmp_path):
    assert call(tmp_path, "memory_curate",
                {"plan": {"plan_version": 2, "ops": []}}).is_error
    assert call(tmp_path, "memory_curate",
                {"plan": {"plan_version": 1,
                          "ops": [{"op": "delete", "slug": "x"}]}}).is_error


def test_resources_and_prompt(tmp_path):
    _seed(tmp_path)

    async def steps(client):
        digest = await client.read_resource("mnemosyne://digest")
        note = await client.read_resource("mnemosyne://note/tax-filing")
        prompt = await client.get_prompt("curate_vault")
        return digest, note, prompt
    digest, note, prompt = _session(tmp_path, steps)
    assert "Tax filing" in digest.contents[0].text
    assert note.contents[0].text.startswith("---\ntitle: Tax filing")
    text = prompt.messages[0].content.text
    assert "memory_curate" in text and "tax-filing" in text


def test_concurrent_creates_of_one_note_yield_exactly_one(tmp_path):
    async def steps(client):
        return await asyncio.gather(*[
            client.call_tool("memory_remember",
                             {"title": "Race", "body": f"writer {i}"})
            for i in range(8)])
    results = _session(tmp_path, steps)
    assert sum(not r.is_error for r in results) == 1
    assert len(list(tmp_path.rglob("race.md"))) == 1


def _try_lock(fh) -> bool:
    """Non-blocking probe of the vault lock, in each OS's own form (the
    same byte and call family as ``_mcp_app._lock_file``)."""
    if os.name == "nt":
        import msvcrt
        os.lseek(fh.fileno(), 0, os.SEEK_SET)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def test_vault_lock_excludes_other_processes(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         ("import sys; from pathlib import Path; "
          "from birkin_mnemosyne._mcp_app import VaultLock; "
          f"lock = VaultLock(Path({str(tmp_path)!r})); "
          "cm = lock.hold(); cm.__enter__(); print('LOCKED', flush=True); "
          "sys.stdin.read(); cm.__exit__(None, None, None)")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert holder.stdout is not None and holder.stdin is not None
    try:
        assert holder.stdout.readline().strip() == "LOCKED"
        with open(tmp_path / LOCK_FILE, "a+b") as fh:
            assert not _try_lock(fh)
            holder.stdin.close()
            assert holder.wait(timeout=30) == 0
            assert _try_lock(fh)
    finally:
        holder.kill()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_stdio_transport_end_to_end(tmp_path, mode):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "birkin_mnemosyne.mcp_server", "--vault", str(tmp_path)])

    async def run():
        async with Client(params, mode=mode) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            created = await client.call_tool(
                "memory_remember", {"title": "Stdio note", "body": "pipes"})
            found = await client.call_tool("memory_search",
                                           {"query": "pipes"})
            return names, created, found
    names, created, found = asyncio.run(run())
    assert "memory_curate" in names
    assert not created.is_error
    content = found.content[0]
    assert isinstance(content, TextContent)
    assert json.loads(content.text)["results"][0]["slug"] == \
        "stdio-note"
    assert (tmp_path / "knowledge" / "stdio-note.md").is_file()


def test_hand_made_note_title_round_trips_over_mcp(tmp_path):
    hand = tmp_path / "My Note.md"
    hand.write_text("---\ntype: topic\n---\nhand written body about pelicans\n",
                    encoding="utf-8")
    hit, = ok(tmp_path, "memory_search", {"query": "pelicans"})["results"]
    assert hit["title"] == "My Note"
    note = ok(tmp_path, "memory_get_note", {"note": hit["title"]})
    assert note["slug"] == "My Note" and "pelicans" in note["body"]
    assert "already exists" in err(tmp_path, "memory_remember",
                                   {"title": "My Note", "body": "dup?"})
    out = remember(tmp_path, "My Note", "more about herons", mode="append")
    assert out["path"] == "My Note.md" and out["created"] is False
    assert sorted(_files(tmp_path)) == ["My Note.md"]


def test_remember_create_refuses_file_the_index_has_not_seen(tmp_path,
                                                             monkeypatch):
    target = tmp_path / "knowledge" / "unseen.md"
    target.parent.mkdir()
    target.write_bytes(b"original bytes\n")
    # the index never learns about the file (stale cache, scan race)
    monkeypatch.setattr(mnemosyne.Mnemosyne, "refresh", lambda self: None)
    msg = err(tmp_path, "memory_remember",
              {"title": "Unseen", "body": "overwrite!"})
    assert "already exists" in msg
    assert target.read_bytes() == b"original bytes\n"
