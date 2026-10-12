"""Labels through the real MCP surface: schemas, writes, filters and counts.

Exercises memory_remember/memory_search/memory_list/memory_get_note over an
in-process MCP client (same pattern as test_mcp_server.py): stored labels are
normalized on write (namespace lowercased, value spelling kept), exposed on
read, filtered with AND semantics before ranking/pagination, and counted over
every eligible note. Malformed label input is a tool error with no writes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import Client

from birkin_mnemosyne._mcp_app import create_server


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


def _files(vault: Path) -> dict[str, bytes]:
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in vault.rglob("*.md")}


def _seed_three(vault: Path) -> None:
    remember(vault, "Alpha", "needle memory", labels=["Project:Alpha",
                                                      "topic:Storage"],
             tags=["owner"], source="manual fixture")
    remember(vault, "Foreign", "needle memory", labels=["project:Foreign",
                                                        "topic:Storage"])
    remember(vault, "OtherTopic", "needle memory",
             labels=["project:Alpha", "topic:Other"])


def test_labels_surface_on_remember_search_list_schemas(tmp_path):
    async def steps(client):
        return (await client.list_tools()).tools
    tools = {t.name: t for t in _session(tmp_path, steps)}
    for name in ("memory_remember", "memory_search", "memory_list"):
        assert "labels" in tools[name].input_schema["properties"]
    assert tools["memory_search"].annotations.read_only_hint is True
    assert tools["memory_list"].annotations.read_only_hint is True
    assert tools["memory_remember"].annotations.read_only_hint is False


def test_remember_stores_normalized_labels_and_get_returns_them(tmp_path):
    remember(tmp_path, "Alpha", "needle memory",
             labels=["Project:Alpha", "topic:Storage"], tags=["owner"])
    raw = (tmp_path / "knowledge" / "alpha.md").read_text(encoding="utf-8")
    assert 'labels: ["project:Alpha", "topic:Storage"]' in raw
    note = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    assert note["labels"] == ["project:Alpha", "topic:Storage"]
    assert note["tags"] == ["owner"]
    assert note["version"] == 1


def test_append_keeps_labels_and_explicit_clear_removes_them(tmp_path):
    remember(tmp_path, "Alpha", "needle memory", labels=["project:Alpha"],
             tags=["owner"])
    ok(tmp_path, "memory_remember", {"title": "Alpha", "body": "appended",
                                     "mode": "append"})
    note = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    assert note["labels"] == ["project:Alpha"] and note["tags"] == ["owner"]
    assert note["version"] == 2
    ok(tmp_path, "memory_remember", {"title": "Alpha", "body": "cleared",
                                     "mode": "append", "labels": []})
    note = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    assert note["labels"] == [] and note["tags"] == ["owner"]
    raw = (tmp_path / "knowledge" / "alpha.md").read_text(encoding="utf-8")
    assert "labels: []" in raw


def test_replace_keeps_or_replaces_labels_with_version(tmp_path):
    remember(tmp_path, "Alpha", "needle memory", labels=["project:Alpha"])
    first = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    out = remember(tmp_path, "Alpha", "needle memory two", mode="replace",
                   expected_version=first["version"])
    assert out["version"] == 2
    kept = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    assert kept["labels"] == ["project:Alpha"]
    out = remember(tmp_path, "Alpha", "needle memory three", mode="replace",
                   expected_version=kept["version"], labels=["topic:Fresh"])
    assert out["version"] == 3
    replaced = ok(tmp_path, "memory_get_note", {"note": "alpha"})
    assert replaced["labels"] == ["topic:Fresh"]


def test_manual_spelling_preserved_stored_and_matched_by_namespace_case(
        tmp_path):
    (tmp_path / "beta.md").write_text(
        "---\ntype: topic\nlabels: [\"Project:Beta\"]\n---\n\n"
        "hand written body about betas\n", encoding="utf-8")
    note = ok(tmp_path, "memory_get_note", {"note": "beta"})
    assert note["labels"] == ["Project:Beta"]
    listed = ok(tmp_path, "memory_list")["notes"]
    assert next(n for n in listed if n["slug"] == "beta")["labels"] == \
        ["Project:Beta"]
    assert [h["slug"] for h in ok(tmp_path, "memory_search", {
        "query": "betas", "labels": ["project:Beta"]})["results"]] == ["beta"]
    # value case is preserved: project:beta (lowercase value) must not
    # match a stored "Project:Beta" label, so the valid filter finds nothing
    assert ok(tmp_path, "memory_search", {
        "query": "betas", "labels": ["project:beta"]})["results"] == []


def test_search_and_list_and_filter(tmp_path):
    _seed_three(tmp_path)
    hits = ok(tmp_path, "memory_search", {
        "query": "needle", "labels": ["project:Alpha", "topic:Storage"]})
    assert {h["slug"] for h in hits["results"]} == {"alpha"}
    hits = ok(tmp_path, "memory_search", {
        "query": "needle", "labels": ["project:Alpha"]})
    assert {h["slug"] for h in hits["results"]} == {"alpha", "othertopic"}
    for h in hits["results"]:
        assert "labels" in h
    listed = ok(tmp_path, "memory_list", {
        "labels": ["project:Alpha", "topic:Other"], "limit": 1})
    assert listed["total"] == 1
    assert [n["slug"] for n in listed["notes"]] == ["othertopic"]


def test_search_still_requires_query_text_alongside_labels(tmp_path):
    _seed_three(tmp_path)
    assert ok(tmp_path, "memory_search", {
        "query": "absent-term-xyz", "labels": ["project:Alpha"]})["results"] == []
    hits = ok(tmp_path, "memory_search", {
        "query": "needle", "labels": ["topic:Other"]})
    assert [h["slug"] for h in hits["results"]] == ["othertopic"]


def test_empty_labels_preserve_existing_behavior(tmp_path):
    _seed_three(tmp_path)
    plain = ok(tmp_path, "memory_search", {"query": "needle"})
    empty = ok(tmp_path, "memory_search",
               {"query": "needle", "labels": []})
    assert [h["slug"] for h in empty["results"]] == \
        [h["slug"] for h in plain["results"]]
    listed_plain = ok(tmp_path, "memory_list")
    listed_empty = ok(tmp_path, "memory_list", {"labels": []})
    assert listed_empty["total"] == listed_plain["total"]
    assert [n["slug"] for n in listed_empty["notes"]] == \
        [n["slug"] for n in listed_plain["notes"]]


def test_list_pagination_and_label_counts_cover_all_eligible(tmp_path):
    _seed_three(tmp_path)
    listed = ok(tmp_path, "memory_list", {
        "labels": ["topic:Storage"], "limit": 1})
    assert listed["total"] == 2
    assert len(listed["notes"]) == 1
    assert listed["notes"][0]["slug"] in {"alpha", "foreign"}
    assert listed["label_counts"] == {
        "project:Alpha": 1, "topic:Storage": 2, "project:Foreign": 1}
    listed = ok(tmp_path, "memory_list", {"labels": ["project:Alpha"]})
    assert listed["total"] == 2
    assert listed["label_counts"] == {
        "project:Alpha": 2, "topic:Storage": 1, "topic:Other": 1}


def test_label_counts_over_unfiltered_list_excludes_nothing_and_archive(
        tmp_path):
    _seed_three(tmp_path)
    listed = ok(tmp_path, "memory_list")
    assert listed["label_counts"]["project:Alpha"] == 2
    ok(tmp_path, "memory_forget", {"note": "foreign", "confirm": True})
    archived = ok(tmp_path, "memory_list")
    assert "project:Foreign" not in archived["label_counts"]
    assert archived["total"] == 2


@pytest.mark.parametrize("bad", ["not-a-label", "project:",
                                 "\u0000", "label:with\nnewline"])
def test_remember_rejects_malformed_labels_without_writes(tmp_path, bad):
    remember(tmp_path, "Good", "needle memory", labels=["project:Ok"])
    before = _files(tmp_path)
    err(tmp_path, "memory_remember",
        {"title": "Invalid", "body": "must not persist", "labels": [bad]})
    assert _files(tmp_path) == before
    assert (tmp_path / "knowledge" / "invalid.md").exists() is False


def test_remember_and_search_reject_non_list_labels_without_writes(tmp_path):
    remember(tmp_path, "Good", "needle memory", labels=["project:Ok"])
    before = _files(tmp_path)
    for name, args in (
        ("memory_remember", {"title": "Invalid", "body": "x",
                             "labels": "project:Ok"}),
        ("memory_remember", {"title": "Invalid", "body": "x", "labels": [3]}),
        ("memory_remember", {"title": "Invalid", "body": "x",
                             "labels": ["no-colon-value"]}),
        ("memory_search", {"query": "needle", "labels": "project:Ok"}),
        ("memory_search", {"query": "needle", "labels": ["no-colon-value"]}),
        ("memory_search", {"query": "needle", "labels": ["invalid!"]}),
        ("memory_list", {"labels": ["no-colon-value"]}),
    ):
        assert call(tmp_path, name, args).is_error
    assert _files(tmp_path) == before