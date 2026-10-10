"""MCP adapters for the always-loaded memory INDEX, through a real MCP client.

Registration is additive (no remove/replace/delete tool); reads and the server
initialization instructions carry every entry, and an enabled-but-missing or
corrupt state fails instead of silently emptying the INDEX."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR

from birkin_mnemosyne import MemoryIndex, MemoryIndexError
from birkin_mnemosyne._mcp_app import INSTRUCTIONS, create_server
from birkin_mnemosyne.memory_index import INDEX_SOURCE


def _session(vault: Path, steps, **kwargs):
    async def run():
        async with Client(create_server(vault, **kwargs)) as client:
            return await steps(client)
    return asyncio.run(run())


def call(vault: Path, name: str, args: dict[str, Any] | None = None, **kwargs):
    async def steps(client):
        return await client.call_tool(name, args or {})
    return _session(vault, steps, **kwargs)


def ok(vault: Path, name: str, args: dict[str, Any] | None = None,
       **kwargs) -> dict[str, Any]:
    r = call(vault, name, args, **kwargs)
    assert not r.is_error, r.content
    return r.structured_content


def err(vault: Path, name: str, args: dict[str, Any] | None = None) -> str:
    r = call(vault, name, args)
    assert r.is_error, r.structured_content
    return r.content[0].text


def register(vault: Path, trigger: str, document: str,
             **extra) -> dict[str, Any]:
    return ok(vault, "memory_index_register",
              {"trigger": trigger, "document": document, **extra})


def _enabled(vault: Path, count: int, *, max_tokens: int | None = None) -> None:
    for number in range(count):
        (vault / f"topic-{number}.md").write_text(
            f"# Topic {number}\nRule {number}.\n", encoding="utf-8")
    for number in range(count):
        register(vault, f"When task {number}", f"topic-{number}.md")
    if max_tokens is not None:
        register(vault, "When task 0", "topic-0.md", max_tokens=max_tokens)


def _instructions(vault: Path, **kwargs) -> str:
    async def steps(client):
        return client.instructions
    return _session(vault, steps, **kwargs)


@pytest.mark.parametrize("raw", [b"# Topic\nRule one.\n", b"# Topic\r\nRule one.\r\n"])
def test_index_register_read_open_round_trip(tmp_path, raw):
    (tmp_path / "topic.md").write_bytes(raw)
    registered = register(tmp_path, "When reviewing", "topic.md")
    assert registered["enabled"] is True
    assert registered["entries"] == [
        {"trigger": "When reviewing", "document": "topic.md"}]
    assert registered["over_budget"] is False
    assert registered["warnings"] == []

    read = ok(tmp_path, "memory_index_read")
    assert read["entries"] == registered["entries"]
    assert read["context"] == registered["context"]

    opened = ok(tmp_path, "memory_open_trigger", {"query": "when reviewing"})
    assert opened["matched_by"] == "exact"
    assert [(d["path"], d["content"]) for d in opened["documents"]] == [
        ("topic.md", raw.decode("utf-8"))]


def test_registration_is_idempotent_and_has_no_removal_tool(tmp_path):
    (tmp_path / "topic.md").write_text("# Topic\nRule one.\n", encoding="utf-8")
    register(tmp_path, "When reviewing", "topic.md")
    before = (tmp_path / ".mnemosyne-memory-index" / "index.json").read_bytes()
    again = register(tmp_path, "When reviewing", "topic.md")
    assert len(again["entries"]) == 1
    assert (tmp_path / ".mnemosyne-memory-index" / "index.json").read_bytes() \
        == before

    async def names(client):
        return {t.name for t in (await client.list_tools()).tools}
    tools = _session(tmp_path, names)
    assert not {n for n in tools if "remove" in n or "delete" in n
                or "replace" in n}


@pytest.mark.parametrize("trigger,document", [
    (" ", "topic.md"), ("bad\ntrigger", "topic.md"), ("ok", "missing.md"),
    ("ok", "../outside.md"),
])
def test_unsafe_registration_becomes_tool_error(tmp_path, trigger, document):
    (tmp_path / "topic.md").write_text("# Topic\nRule one.\n", encoding="utf-8")
    assert err(tmp_path, "memory_index_register",
               {"trigger": trigger, "document": document})
    assert not (tmp_path / ".mnemosyne-memory-index").exists()


def test_open_falls_back_to_search_then_none(tmp_path):
    from birkin_mnemosyne import VaultMemory
    memory = VaultMemory({"vault_path": str(tmp_path)})
    memory.write_note("Telescope", "Calibration uses a silver collimator.")
    fallback = ok(tmp_path, "memory_open_trigger", {"query": "collimator"})
    assert fallback["matched_by"] == "search"
    assert fallback["documents"][0]["path"] == "knowledge/telescope.md"
    assert "silver collimator" in fallback["documents"][0]["content"]
    empty = ok(tmp_path, "memory_open_trigger", {"query": "qxzunrecorded"})
    assert empty == {"matched_by": "none", "documents": []}


def test_startup_read_accepts_empty_paths_with_enabled_index(tmp_path):
    _enabled(tmp_path, 2)
    result = ok(tmp_path, "memory_startup_read", {"paths": []})
    assert result["complete"] is True
    assert result["coverage"]["files"] == 1
    payload = json.loads(result["context"])
    assert {f["path"] for f in payload["files"]} == {INDEX_SOURCE}
    assert result["estimated_tokens"] == (len(result["context"].encode("utf-8")) + 3) // 4
    assert "When task 1 -> topic-1.md" in result["context"]


def test_empty_startup_paths_without_index_fail(tmp_path):
    assert "nonempty list of startup paths" in err(
        tmp_path, "memory_startup_read", {"paths": []})


def test_task_startup_delivers_all_targets_and_verifies_the_same_task(tmp_path):
    _enabled(tmp_path, 5)
    task = "Review task 0."
    result = ok(tmp_path, "memory_startup_read", {"paths": [], "task": task})
    assert len(result["matched_entries"]) == 5
    payload = json.loads(result["context"])
    for number in range(5):
        body = "".join(
            block["text"] for block in payload["blocks"]
            if block["path"] == f"topic-{number}.md"
        )
        assert body == f"# Topic {number}\nRule {number}.\n"
    assert ok(tmp_path, "memory_startup_verify", {
        "paths": [], "context": result["context"], "task": task,
    })["complete"]
    assert not ok(tmp_path, "memory_startup_verify", {
        "paths": [], "context": result["context"], "task": "Task 0 review.",
    })["complete"]


def test_task_startup_rejects_blank_tasks(tmp_path):
    _enabled(tmp_path, 1)
    assert err(tmp_path, "memory_startup_read", {"paths": [], "task": " \n"})


def test_initialization_instructions_carry_complete_over_budget_index(tmp_path):
    _enabled(tmp_path, 12, max_tokens=1)
    read = ok(tmp_path, "memory_index_read")
    assert read["over_budget"] is True and read["warnings"]
    assert len(read["entries"]) == 12

    instructions = _instructions(tmp_path)
    for number in range(12):
        assert f"- When task {number} -> topic-{number}.md" in instructions


def test_initialization_instructions_omit_index_when_disabled(tmp_path):
    assert _instructions(tmp_path) == INSTRUCTIONS


def test_initialization_fails_when_required_marker_is_missing_or_corrupt(tmp_path):
    with pytest.raises(MemoryIndexError):
        create_server(tmp_path, require_memory_index=True)
    _enabled(tmp_path, 1)
    (tmp_path / ".mnemosyne-memory-index" / "index.json").write_text(
        "{not json", encoding="utf-8")
    with pytest.raises(MemoryIndexError):
        create_server(tmp_path)


def test_read_open_after_enabled_state_disappears(tmp_path):
    _enabled(tmp_path, 1)

    async def steps(client):
        (tmp_path / ".mnemosyne-memory-index" / "index.json").unlink()
        return (await client.call_tool("memory_index_read"),
                await client.call_tool("memory_open_trigger",
                                       {"query": "when task 0"}))
    read, opened = _session(tmp_path, steps)
    assert read.is_error and opened.is_error
    assert "missing or invalid" in read.content[0].text


def test_separate_identity_root_reads_index_from_vault(tmp_path):
    vault, identity = tmp_path / "vault", tmp_path / "identity"
    vault.mkdir()
    identity.mkdir()
    _enabled(vault, 1)
    (identity / "MODE.md").write_text("# Mode\nPending: work\n", encoding="utf-8")

    instructions = _instructions(vault, identity_root=identity)
    assert "- When task 0 -> topic-0.md" in instructions

    result = ok(vault, "memory_startup_read", {"paths": ["MODE.md"]},
                identity_root=identity)
    assert result["complete"] is True
    payload = json.loads(result["context"])
    assert {f["path"] for f in payload["files"]} == {"MODE.md", INDEX_SOURCE}


def test_verify_rejects_a_dropped_index_entry(tmp_path):
    from birkin_mnemosyne.startup_coverage import digest
    _enabled(tmp_path, 2)
    context = ok(tmp_path, "memory_startup_read", {"paths": []})["context"]
    payload = json.loads(context)
    block = next(b for b in payload["blocks"] if "When task 1 -> topic-1.md" in b["text"])
    block["text"] = block["text"].replace("- When task 1 -> topic-1.md\n", "")
    block["sha256"] = digest(block["text"].encode("utf-8"))
    verified = ok(tmp_path, "memory_startup_verify", {
        "paths": [], "context": json.dumps(payload)})
    assert verified["complete"] is False


def test_digest_resource_includes_the_index(tmp_path):
    _enabled(tmp_path, 2)

    async def steps(client):
        return await client.read_resource("mnemosyne://digest")
    digest_resource = _session(tmp_path, steps)
    assert "- When task 1 -> topic-1.md" in digest_resource.contents[0].text


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_reused_server_initialization_reads_current_index(tmp_path, mode):
    (tmp_path / "first.md").write_bytes(b"First complete rule.")
    (tmp_path / "second.md").write_bytes(b"Second complete rule.")
    server = create_server(tmp_path)

    async def run():
        async with Client(server, mode=mode) as client:
            result = await client.call_tool("memory_index_register", {
                "trigger": "first task", "document": "first.md"})
            assert not result.is_error
        MemoryIndex(tmp_path).register("second task", "second.md", max_tokens=1)
        async with Client(server, mode=mode) as restarted:
            assert "first task -> first.md" in restarted.instructions
            assert "second task -> second.md" in restarted.instructions
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("mutation", ["missing", "corrupt", "missing-marker"])
def test_reused_server_initialization_rejects_lost_state(tmp_path, mode, mutation):
    _enabled(tmp_path, 1)
    server = create_server(tmp_path)
    state = tmp_path / ".mnemosyne-memory-index" / "index.json"

    async def run():
        async with Client(server, mode=mode):
            pass
        if mutation == "corrupt":
            state.write_bytes(b"{invalid")
        else:
            state.unlink()
            if mutation == "missing-marker":
                state.parent.rmdir()
        with pytest.RaisesGroup(
            pytest.RaisesExc(MCPError, check=lambda error: error.code == INTERNAL_ERROR),
            flatten_subgroups=True,
        ):
            async with Client(server, mode=mode):
                pytest.fail("initialization must not succeed with lost INDEX state")
    asyncio.run(run())
