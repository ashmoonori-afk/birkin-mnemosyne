"""Optional ``paths`` on memory_startup_read/verify over a real MCP client."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client

from birkin_mnemosyne._mcp_app import create_server
from birkin_mnemosyne.handoffs import HandoffStore

SCOPE = {"project_key": "example/project", "task_key": "release"}


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


def _no_default_scope(monkeypatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_PROJECT_KEY", raising=False)
    monkeypatch.delenv("MNEMOSYNE_TASK_KEY", raising=False)


def test_startup_schemas_do_not_require_paths(tmp_path):
    async def steps(client):
        return (await client.list_tools()).tools
    tools = {t.name: t for t in _session(tmp_path, steps)}
    read_schema = tools["memory_startup_read"].input_schema
    assert "paths" in read_schema["properties"]
    assert "paths" not in read_schema.get("required", [])
    verify_schema = tools["memory_startup_verify"].input_schema
    assert "paths" in verify_schema["properties"]
    assert set(verify_schema["required"]) == {"context"}


def test_keys_only_read_after_capture_is_complete(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    HandoffStore(tmp_path).enable()
    receipt = ok(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "checkpoint-1", "work": "KEYS_ONLY_SENTINEL"})
    startup = ok(tmp_path, "memory_startup_read", SCOPE)
    assert startup["complete"] is True
    assert receipt["path"] in startup["context"]
    assert "KEYS_ONLY_SENTINEL" in startup["context"]


def test_task_only_read_on_index_vault(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    (tmp_path / "topic.md").write_text("# Topic\nRule one.\n", encoding="utf-8")
    ok(tmp_path, "memory_index_register", {
        "trigger": "When checking the release", "document": "topic.md"})
    startup = ok(tmp_path, "memory_startup_read", {"task": "Check the release"})
    assert startup["complete"] is True
    assert "Rule one." in startup["context"]


def test_no_arg_read_on_empty_vault_errors(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    message = err(tmp_path, "memory_startup_read", {})
    assert "supply a nonempty list of startup paths" in message


def test_verify_with_keys_and_context_no_paths(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    HandoffStore(tmp_path).enable()
    ok(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "checkpoint-1", "work": "VERIFY_SENTINEL"})
    startup = ok(tmp_path, "memory_startup_read", SCOPE)
    checked = ok(tmp_path, "memory_startup_verify",
                 {"context": startup["context"], **SCOPE})
    assert checked["complete"] is True
