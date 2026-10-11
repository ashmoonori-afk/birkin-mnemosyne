"""MCP handoff capture/read/fold and scoped startup over a real MCP client."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client

from birkin_mnemosyne._mcp_app import create_server
from birkin_mnemosyne.handoff_records import HandoffScope
from birkin_mnemosyne.handoffs import HandoffConfig, HandoffStore
from birkin_mnemosyne.startup import StartupReader

SCOPE = {"project_key": "mn-070", "task_key": "handoff"}
FULL = {
    "capture_id": "checkpoint-1",
    "work": "MCP_ONLY_SENTINEL",
    "next_step": "Run the host proof.",
    "decisions": ["Keep complete context."],
    "open_items": ["Verify the new process."],
    "open_questions": ["Which gate remains?"],
    "links": ["https://example.invalid/42"],
}


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


def _enable(vault: Path) -> HandoffConfig:
    return HandoffStore(vault).enable()


def _handoff_images(vault: Path) -> dict[str, bytes]:
    root = vault / ".mnemosyne-handoffs"
    if not root.exists():
        return {}
    return {str(path.relative_to(vault)): path.read_bytes()
            for path in root.rglob("*.md")}


def _no_default_scope(monkeypatch) -> None:
    monkeypatch.delenv("MNEMOSYNE_PROJECT_KEY", raising=False)
    monkeypatch.delenv("MNEMOSYNE_TASK_KEY", raising=False)


def test_handoff_tool_surface_schemas_and_annotations(tmp_path):
    async def steps(client):
        return (await client.list_tools()).tools
    tools = {t.name: t for t in _session(tmp_path, steps)}
    names = {"memory_handoff_capture", "memory_handoff_read",
             "memory_handoff_fold"}
    assert names <= set(tools)
    capture_schema = tools["memory_handoff_capture"].input_schema
    assert {"project_key", "task_key", "capture_id", "work", "decisions",
            "open_items", "open_questions", "next_step", "links",
            "event", "session_id", "source"} <= capture_schema["properties"].keys()
    assert set(capture_schema["required"]) == {"capture_id", "work"}
    read_annotations = tools["memory_handoff_read"].annotations
    assert read_annotations is not None and read_annotations.read_only_hint is True
    capture_annotations = tools["memory_handoff_capture"].annotations
    assert capture_annotations is not None
    assert capture_annotations.read_only_hint is False
    assert capture_annotations.idempotent_hint is True
    fold_schema = tools["memory_handoff_fold"].input_schema
    assert fold_schema["properties"]["apply"]["default"] is False
    assert fold_schema["properties"]["keep"]["default"] == 3
    assert tools["memory_handoff_fold"].annotations.read_only_hint is False


def test_handoff_capture_and_read_round_trip(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    receipt = ok(tmp_path, "memory_handoff_capture", {**SCOPE, **FULL})
    assert receipt["created"] is True and len(receipt["sha256"]) == 64
    assert receipt["warnings"] == []
    read = ok(tmp_path, "memory_handoff_read", SCOPE)
    assert read["count"] == 1 and read["warnings"] == []
    latest = read["latest"]
    assert latest["capture_id"] == "checkpoint-1"
    assert latest["scope"] == {"project_key": "mn-070", "task_key": "handoff"}
    assert latest["fields"] == {
        "work": "MCP_ONLY_SENTINEL", "next_step": "Run the host proof.",
        "decisions": ["Keep complete context."],
        "open_items": ["Verify the new process."],
        "open_questions": ["Which gate remains?"],
        "links": ["https://example.invalid/42"]}
    assert latest["kind"] == "capture" and latest["event"] == "explicit"
    assert latest["session_id"] == "" and latest["source"] == "api"


def test_handoff_capture_is_idempotent_and_rejects_conflict(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    payload = {**SCOPE, **FULL}
    first = ok(tmp_path, "memory_handoff_capture", payload)
    before = _handoff_images(tmp_path)
    retried = ok(tmp_path, "memory_handoff_capture", payload)
    assert retried["path"] == first["path"]
    assert retried["created"] is False
    assert _handoff_images(tmp_path) == before
    message = err(tmp_path, "memory_handoff_capture",
                  {**payload, "work": "conflict"})
    assert "already holds different content" in message
    assert _handoff_images(tmp_path) == before


def test_handoff_oversized_record_warns_without_truncation(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    large = "large handoff " * 900
    receipt = ok(tmp_path, "memory_handoff_capture",
                 {**SCOPE, "capture_id": "large", "work": large})
    assert receipt["warnings"], "oversized record must warn without truncation"
    latest = ok(tmp_path, "memory_handoff_read", SCOPE)["latest"]
    assert latest["fields"]["work"] == large


def test_handoff_scope_defaults_and_project_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MNEMOSYNE_PROJECT_KEY", "default-project")
    monkeypatch.setenv("MNEMOSYNE_TASK_KEY", "default-task")
    _enable(tmp_path)
    ok(tmp_path, "memory_handoff_capture", {
        "capture_id": "environment-default", "work": "ENVIRONMENT_ONLY"})
    store = HandoffStore(tmp_path)
    assert store.latest(HandoffScope("default-project", "default-task")) is not None
    ok(tmp_path, "memory_handoff_capture", {
        "project_key": "override-project", "capture_id": "override",
        "work": "OVERRIDE_ONLY"})
    assert store.latest(HandoffScope("override-project")) is not None
    assert store.latest(HandoffScope("override-project", "default-task")) is None


def test_handoff_missing_project_is_a_clear_tool_error(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    message = err(tmp_path, "memory_handoff_capture", {
        "capture_id": "no-scope", "work": "x"})
    assert "project_key or MNEMOSYNE_PROJECT_KEY is required" in message
    message = err(tmp_path, "memory_handoff_read", {})
    assert "project_key or MNEMOSYNE_PROJECT_KEY is required" in message
    message = err(tmp_path, "memory_handoff_capture", {
        "task_key": "orphan", "capture_id": "no-scope", "work": "x"})
    assert "task_key requires project_key" in message
    assert _handoff_images(tmp_path) == {}


def test_handoff_scoped_startup_includes_latest(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    ok(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "startup-bound", "work": "SENTINEL_WORK"})
    startup = ok(tmp_path, "memory_startup_read", {**SCOPE, "paths": []})
    context = startup["context"]
    assert isinstance(context, str) and "SENTINEL_WORK" in context
    assert startup["complete"] is True
    reader = StartupReader(tmp_path, require_index=True)
    assert reader.verify(context, [], project_key=SCOPE["project_key"],
                         task_key=SCOPE["task_key"]).complete
    checked = ok(tmp_path, "memory_startup_verify", {
        **SCOPE, "paths": [], "context": context})
    assert checked["complete"] is True
    plain = ok(tmp_path, "memory_startup_read", {"paths": []})
    assert "SENTINEL_WORK" not in plain["context"]
    assert ".mnemosyne-handoffs" not in plain["context"]


def test_handoff_fold_preview_apply_and_undo(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    for number in range(6):
        ok(tmp_path, "memory_handoff_capture", {
            **SCOPE, "capture_id": f"fold-{number}",
            "work": f"fold work {number}"})
    store = HandoffStore(tmp_path)
    before = {note.path: note.raw for note in store.records(HandoffScope(**SCOPE))}
    snapshot = _handoff_images(tmp_path)
    preview = ok(tmp_path, "memory_handoff_fold", {**SCOPE, "keep": 3})
    assert preview["state"] == "preview"
    assert len(preview["plan_id"]) == 64
    assert preview["accepted"] != []
    assert _handoff_images(tmp_path) == snapshot
    message = err(tmp_path, "memory_handoff_fold",
                  {**SCOPE, "keep": 3, "apply": True})
    assert "plan_id" in message
    message = err(tmp_path, "memory_handoff_fold", {
        **SCOPE, "keep": 3, "apply": True, "plan_id": "0" * 64})
    assert "stale" in message
    assert _handoff_images(tmp_path) == snapshot
    applied = ok(tmp_path, "memory_handoff_fold", {
        **SCOPE, "keep": 3, "apply": True, "plan_id": preview["plan_id"]})
    assert applied["state"] == "committed" and applied["transaction_id"]
    assert {note.path: note.raw
            for note in store.records(HandoffScope(**SCOPE))} != before
    undone = ok(tmp_path, "memory_review_undo", {
        "transaction_id": applied["transaction_id"], "confirm": True})
    assert undone["dry_run"] is False
    assert {note.path: note.raw
            for note in store.records(HandoffScope(**SCOPE))} == before


def test_handoff_malformed_input_writes_nothing(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    assert "nonblank" in err(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "blank", "work": "   "})
    assert "nonblank" in err(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "blank-entry", "work": "ok",
        "decisions": [" "]})
    assert "explicit" in err(tmp_path, "memory_handoff_capture", {
        **SCOPE, "capture_id": "bad-event", "work": "ok",
        "event": "fabricated"})
    assert ok(tmp_path, "memory_handoff_read", SCOPE) == {
        "count": 0, "latest": None, "warnings": []}
    assert _handoff_images(tmp_path) == {}


def test_handoff_read_reports_empty_scope_without_error(tmp_path, monkeypatch):
    _no_default_scope(monkeypatch)
    _enable(tmp_path)
    assert ok(tmp_path, "memory_handoff_read", SCOPE) == {
        "count": 0, "latest": None, "warnings": []}