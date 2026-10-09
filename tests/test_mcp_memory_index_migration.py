"""The checker and splitter as thin MCP tools, through a real MCP client.

Preview writes nothing; apply preserves every original byte and line and
records a source backup; the checker reports orphan and dangling routes and a
removed target; unsafe or colliding splits leave the source untouched."""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client

from birkin_mnemosyne._mcp_app import create_server
from birkin_mnemosyne.memory_index import INDEX_DIRECTORY
from birkin_mnemosyne.startup_coverage import digest

SOURCE = (
    "---\ntitle: Original\n---\n\n# Rules\nOwner: Fictional operator\n\n"
    "## Deploy\nRule: keep approval.\n### Exception\n"
    "Rule: emergency changes still need approval.\n"
    "```markdown\n## Example only\nRule: illustrative, not live.\n```\n"
    "## 연락\nRule: 비동기 메시지\n\nLast line without newline"
).encode()


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


def note(root: Path, raw: bytes = SOURCE) -> Path:
    path = root / "memory.md"
    path.write_bytes(raw)
    return path


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _lines(raw: bytes) -> list[str]:
    return raw.decode("utf-8").splitlines(keepends=True)


def test_split_preview_retains_source_and_writes_no_state(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    preview = ok(tmp_path, "memory_index_split", {"document": "memory.md"})
    assert preview["applied"] is False
    assert preview["coverage_receipt"] is None
    assert preview["backup_journal"] is None
    assert preview["source_sha256"] == digest(SOURCE)
    assert preview["source_bytes"] == len(SOURCE)
    assert tree(tmp_path) == before
    assert not (tmp_path / INDEX_DIRECTORY).exists()
    lines = _lines(SOURCE)
    assert [row["line"] for row in preview["coverage"]] == list(range(1, len(lines) + 1))
    assert [row["text"] for row in preview["coverage"]] == lines


def test_split_apply_covers_every_line_and_backs_up_source(tmp_path):
    path = note(tmp_path)
    report = ok(tmp_path, "memory_index_split",
                {"document": "memory.md", "apply": True})
    assert report["applied"] is True
    assert report["coverage_receipt"] and report["backup_journal"]
    lines = _lines(SOURCE)
    assert [row["line"] for row in report["coverage"]] == list(range(1, len(lines) + 1))
    for row in report["coverage"]:
        topic = _lines((tmp_path / row["document"]).read_bytes())
        assert topic[row["document_line"] - 1] == row["text"]
    recovered = b"".join(
        (tmp_path / topic["document"]).read_bytes()[topic["prefix_bytes"]:]
        for topic in report["topics"])
    assert recovered == SOURCE
    receipt = json.loads((tmp_path / report["coverage_receipt"]).read_bytes())
    assert receipt["source_bytes"] == len(SOURCE)
    assert receipt["source_sha256"] == digest(SOURCE)
    backup = json.loads((tmp_path / report["backup_journal"]).read_bytes())
    assert base64.b64decode(backup["changes"][0]["before"]) == SOURCE
    assert path.read_bytes() != SOURCE


def test_check_reports_clean_after_split(tmp_path):
    note(tmp_path)
    ok(tmp_path, "memory_index_split", {"document": "memory.md", "apply": True})
    checked = ok(tmp_path, "memory_index_check")
    assert checked["ok"] is True
    assert checked["orphan_documents"] == []
    assert checked["dangling_entries"] == []
    assert checked["errors"] == []


def test_check_reports_a_removed_target(tmp_path):
    note(tmp_path)
    report = ok(tmp_path, "memory_index_split",
                {"document": "memory.md", "apply": True})
    (tmp_path / report["topics"][-1]["document"]).unlink()
    checked = ok(tmp_path, "memory_index_check")
    assert checked["ok"] is False
    assert checked["dangling_entries"] or checked["errors"]


def test_unsafe_split_document_preserves_source(tmp_path):
    note(tmp_path)
    before = tree(tmp_path)
    r = call(tmp_path, "memory_index_split",
             {"document": "../outside.md", "apply": True})
    assert r.is_error
    after = {k: v for k, v in tree(tmp_path).items()
             if k != ".mnemosyne-mcp.lock"}
    assert after == before
    assert not (tmp_path / INDEX_DIRECTORY).exists()


def test_split_collision_preserves_source(tmp_path):
    path = note(tmp_path)
    preview = ok(tmp_path, "memory_index_split", {"document": "memory.md"})
    collision = tmp_path / preview["topics"][-1]["document"]
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"Existing user document.")
    before = {k: v for k, v in tree(tmp_path).items()
              if k != ".mnemosyne-mcp.lock"}
    r = call(tmp_path, "memory_index_split",
             {"document": "memory.md", "apply": True})
    assert r.is_error
    assert path.read_bytes() == SOURCE
    after = {k: v for k, v in tree(tmp_path).items()
             if k != ".mnemosyne-mcp.lock"}
    assert after == before


def test_split_activation_is_remembered_by_the_live_server(tmp_path):
    note(tmp_path)

    async def steps(client):
        report = await client.call_tool(
            "memory_index_split", {"document": "memory.md", "apply": True})
        assert not report.is_error
        shutil.rmtree(tmp_path / INDEX_DIRECTORY)
        read = await client.call_tool("memory_index_read")
        startup = await client.call_tool("memory_startup_read", {"paths": ["memory.md"]})
        return read, startup
    read, startup = _session(tmp_path, steps)
    assert read.is_error
    assert startup.is_error
