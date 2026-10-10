"""Derived topic views preserve every durable route and complete source."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin_mnemosyne.capacity import DEFAULT_BUDGET, capacity_report
from birkin_mnemosyne.memory import VaultMemory
from birkin_mnemosyne.memory_index import (
    INDEX_SOURCE,
    IndexEntry,
    MemoryIndex,
    MemoryIndexError,
    decode_index_json,
)
from birkin_mnemosyne.startup import StartupReader, source_blocks
from birkin_mnemosyne.startup_coverage import StartupPayload, digest

_payload: Callable[[str], StartupPayload] = json.loads


def grouped_index(root: Path) -> tuple[MemoryIndex, tuple[IndexEntry, ...]]:
    index = MemoryIndex(root)
    expected: list[IndexEntry] = []
    for topic in ("shipping", "storage"):
        directory = root / "guides" / topic
        directory.mkdir(parents=True)
        for number in range(12):
            path = directory / f"procedure-{number:02d}.md"
            _ = path.write_bytes(f"BODY_{topic}_{number}\r\n".encode())
            document = path.relative_to(root).as_posix()
            for action in ("applying", "auditing"):
                trigger = f"When {action} {topic} procedure {number:02d} in production"
                expected.append(IndexEntry(trigger, document))
                _ = index.register(trigger, document)
    return index, tuple(expected)


def test_grouped_index_expands_to_every_original_route_without_writes(tmp_path: Path) -> None:
    index, expected = grouped_index(tmp_path)
    state = index.path.read_bytes()
    files = set(index.directory.rglob("*"))

    view = index.read()

    assert view.mode == "grouped"
    assert view.entries == expected
    assert {topic.topic for topic in view.topics} == {
        "dir:guides/shipping", "dir:guides/storage",
    }
    expanded: list[IndexEntry] = []
    expected_topic_rows: list[dict[str, str | int]] = []
    for topic in view.topics:
        leaf = index.read(topic=topic.topic)
        assert leaf.mode == "topic"
        assert leaf.topic == topic.topic
        assert leaf.index_sha256 == view.index_sha256
        assert len(leaf.entries) == topic.routes == 24
        assert len({entry.document for entry in leaf.entries}) == topic.documents == 12
        expected_routes = [
            (entry.trigger, entry.document) for entry in expected
            if "dir:" + entry.document.rsplit("/", 1)[0] == topic.topic
        ]
        for trigger, document in expected_routes:
            assert trigger in leaf.context
            assert document in leaf.context
        raw = json.dumps(sorted(expected_routes), ensure_ascii=False,
                         separators=(",", ":")).encode()
        assert topic.sha256 == hashlib.sha256(raw).hexdigest()
        expected_topic_rows.append({
            "topic": topic.topic, "routes": 24, "documents": 12,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        expanded.extend(leaf.entries)
    assert [
        decode_index_json(line[2:]) for line in view.context.splitlines()
        if line.startswith("- {")
    ] == expected_topic_rows
    assert set(expanded) == set(expected)
    assert len(expanded) == len(expected)
    assert index.path.read_bytes() == state
    assert set(index.directory.rglob("*")) == files


def test_tiny_budget_restart_and_zero_limit_keep_every_topic(tmp_path: Path) -> None:
    index, expected = grouped_index(tmp_path)
    _ = index.register(expected[0].trigger, expected[0].document, max_tokens=1)
    view = MemoryIndex(tmp_path, required=True).read()
    assert view.mode == "grouped"
    assert view.entries == expected
    assert view.over_budget and view.warnings
    assert view.estimated_tokens == (len(view.context.encode()) + 3) // 4
    memory = VaultMemory({"vault_path": str(tmp_path)})
    assert memory.render(limit=0).startswith(view.context)
    report = capacity_report(memory.dex, DEFAULT_BUDGET)
    assert report["always_loaded"]["index_entries"] == len(expected)
    assert report["always_loaded"]["estimated_tokens"] == view.estimated_tokens
    assert report["always_loaded"]["over_budget"]
    for topic in view.topics:
        assert topic.topic in view.context
        leaf = index.read(topic=topic.topic)
        assert leaf.over_budget and leaf.warnings
        assert len(leaf.entries) == 24


def test_small_index_stays_flat_when_group_metadata_costs_more(tmp_path: Path) -> None:
    directory = tmp_path / "short"
    directory.mkdir()
    index = MemoryIndex(tmp_path)
    for name in ("a", "b"):
        _ = (directory / f"{name}.md").write_bytes(b"body")
        _ = index.register(name, f"short/{name}.md")
    assert index.read().mode == "flat"
    assert len(index.read(topic="dir:short").entries) == 2


def test_alias_compaction_keeps_every_trigger_and_reads_the_body_once(tmp_path: Path) -> None:
    directory = tmp_path / "a-long-topic-directory"
    directory.mkdir()
    path = directory / "a-long-document-name-for-operational-rules.md"
    _ = path.write_bytes(b"One complete body.")
    document = path.relative_to(tmp_path).as_posix()
    index = MemoryIndex(tmp_path)
    triggers = ("review", "publish", "audit")
    for trigger in triggers:
        _ = index.register(trigger, document)
    view = index.read()
    assert view.mode == "flat"
    assert view.entries == tuple(IndexEntry(trigger, document) for trigger in triggers)
    assert view.context.count(document) == 1
    assert [
        decode_index_json(line[2:]) for line in view.context.splitlines()
        if line.startswith("- {")
    ] == [{"document": document, "triggers": list(triggers)}]
    for trigger in triggers:
        assert index.open(trigger).documents[0].content == "One complete body."
    result = StartupReader(tmp_path).read([], task="review audit")
    assert len(result.matched_entries) == 2
    assert sum(record["path"] == document for record in _payload(result.context)["files"]) == 1


@pytest.mark.parametrize("topic", ["", "../outside", ".mnemosyne-memory-index", "dir:missing"])
def test_topic_selectors_are_not_filesystem_paths(tmp_path: Path, topic: str) -> None:
    index, _ = grouped_index(tmp_path)
    with pytest.raises(MemoryIndexError):
        _ = index.read(topic=topic)


def test_disabled_topic_read_fails_without_creating_state(tmp_path: Path) -> None:
    with pytest.raises(MemoryIndexError):
        _ = MemoryIndex(tmp_path).read(topic="dir:missing")
    assert list(tmp_path.iterdir()) == []


def test_task_read_includes_only_selected_complete_topic_views(tmp_path: Path) -> None:
    index, expected = grouped_index(tmp_path)
    reader = StartupReader(tmp_path)
    task = "shipping"
    result = reader.read([], task=task)
    payload = _payload(result.context)
    topic_id = "dir:guides/shipping"
    topic_path = ".mnemosyne-memory-index/topic/" + hashlib.sha256(topic_id.encode()).hexdigest()
    assert {entry for entry in result.matched_entries} == {
        entry for entry in expected if "/shipping/" in entry.document
    }
    topic_sources = [
        record["path"] for record in payload["files"]
        if record["path"].startswith(".mnemosyne-memory-index/topic/")
    ]
    assert topic_sources == [topic_path]
    text = "".join(block["text"] for block in payload["blocks"] if block["path"] == topic_path)
    assert text == index.read(topic=topic_id).context
    assert result.coverage.files == 15
    assert reader.verify(result.context, [], task=task).complete


@pytest.mark.parametrize("source", ["top", "topic"])
def test_verifier_rejects_recertified_missing_group_material(
    tmp_path: Path, source: str,
) -> None:
    _ = grouped_index(tmp_path)
    reader = StartupReader(tmp_path)
    payload = _payload(reader.read([], task="shipping").context)
    path = INDEX_SOURCE if source == "top" else next(
        record["path"] for record in payload["files"]
        if record["path"].startswith(".mnemosyne-memory-index/topic/")
    )
    forged = b"# Incomplete route map\n"
    payload["blocks"] = [
        block for block in payload["blocks"] if block["path"] != path
    ] + source_blocks(path, forged)
    for record in payload["files"]:
        if record["path"] == path:
            record.update(sha256=digest(forged), bytes=len(forged), lines=1)
    assert not reader.verify(json.dumps(payload), [], task="shipping").complete


def test_fresh_group_registration_invalidates_an_old_bundle(tmp_path: Path) -> None:
    index, _ = grouped_index(tmp_path)
    reader = StartupReader(tmp_path)
    before = reader.read([], task="shipping")
    _ = (tmp_path / "new.md").write_bytes(b"A new independent rule.")
    _ = index.register("new unrelated condition", "new.md")
    assert not reader.verify(before.context, [], task="shipping").complete
