"""Task matching delivers complete routed sources, not ranked excerpts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError
from birkin_mnemosyne.startup import StartupError, StartupReader, source_blocks
from birkin_mnemosyne.startup_coverage import StartupPayload, digest

_payload: Callable[[str], StartupPayload] = json.loads


def seed(root: Path, count: int = 1, body: bytes = b"Complete rule.\n") -> MemoryIndex:
    index = MemoryIndex(root)
    for number in range(count):
        document = f"rule-{number}.md"
        _ = (root / document).write_bytes(body)
        _ = index.register("When reviewing deployment", document)
    return index


def body_from(context: str, path: str) -> bytes:
    blocks = sorted(
        (block for block in _payload(context)["blocks"] if block["path"] == path),
        key=lambda block: block["start_byte"],
    )
    return "".join(block["text"] for block in blocks).encode("utf-8")


@pytest.mark.parametrize(("trigger", "task", "expected"), [
    ("When reviewing deployments", "Review the deployment", True),
    ("reviewing", "review", True),
    ("stopped", "stop", True),
    ("policies", "policy", True),
    ("class", "clas", False),
    ("status", "statu", False),
    ("configure", "configuration", False),
    ("tea", "steaming", False),
    ("120", "12", False),
    ("Café", "cafe", True),
    ("배포 검증", "배포 검증을 진행", True),
    ("when", " WHEN ", True),
    ("When reviewing deployments", "When should I do this?", False),
])
def test_task_matching_uses_words_not_function_words_or_prefixes(
    tmp_path: Path, trigger: str, task: str, expected: bool,
) -> None:
    _ = (tmp_path / "rule.md").write_bytes(b"Unrelated searchable body.")
    index = MemoryIndex(tmp_path)
    _ = index.register(trigger, "rule.md")
    assert bool(index.match(task)) is expected


@pytest.mark.parametrize("task", ["", " ", "\n"])
def test_blank_task_fails_instead_of_returning_empty_success(
    tmp_path: Path, task: str,
) -> None:
    index = seed(tmp_path)
    with pytest.raises(MemoryIndexError):
        _ = index.match(task)


def test_task_read_includes_every_body_and_preserves_all_matching_aliases(
    tmp_path: Path,
) -> None:
    raw = "\ufeff---\r\nkind: rule\r\n---\r\n\r\n# Deployment\r\nLast byte".encode()
    index = seed(tmp_path, 5, raw)
    _ = index.register("deployment", "rule-0.md")
    reader = StartupReader(tmp_path)

    result = reader.read([], task="deployment")

    assert len(result.matched_entries) == 6
    assert result.coverage.complete
    assert reader.verify(result.context, [], task="deployment").complete
    paths = [record["path"] for record in _payload(result.context)["files"]]
    for number in range(5):
        path = f"rule-{number}.md"
        assert paths.count(path) == 1
        assert body_from(result.context, path) == raw


def test_no_match_does_not_fall_back_to_document_content(tmp_path: Path) -> None:
    index = seed(tmp_path, body=b"Calibration requires a collimator.")
    assert index.open("collimator").documents

    result = StartupReader(tmp_path).read([], task="collimator")

    assert result.matched_entries == ()
    assert "rule-0.md" not in {record["path"] for record in _payload(result.context)["files"]}


def test_task_receipt_binds_identical_selection_to_the_exact_task(tmp_path: Path) -> None:
    _ = seed(tmp_path)
    reader = StartupReader(tmp_path)
    result = reader.read([], task="review deployment")
    assert reader.read([], task="review deployment").cache_hit

    assert not reader.verify(result.context, [], task="deployment review").complete
    assert not reader.read([], task="deployment review").cache_hit
    assert not reader.verify(result.context, []).complete


def test_separate_roots_keep_same_named_documents_distinct(tmp_path: Path) -> None:
    identity, vault = tmp_path / "identity", tmp_path / "vault"
    identity.mkdir()
    vault.mkdir()
    _ = (identity / "rule-0.md").write_bytes(b"Identity instructions.")
    _ = seed(vault, body=b"Vault instructions.")
    reader = StartupReader(identity, memory_index_root=vault)

    result = reader.read(["rule-0.md"], task="deployment")

    assert body_from(result.context, "rule-0.md") == b"Identity instructions."
    assert body_from(
        result.context, ".mnemosyne-memory-index/documents/rule-0.md",
    ) == b"Vault instructions."
    assert reader.verify(result.context, ["rule-0.md"], task="deployment").complete


def test_same_root_overlap_is_read_once_and_keeps_explicit_closure(tmp_path: Path) -> None:
    _ = seed(tmp_path, body=b"MUST READ: extra.md\n")
    _ = (tmp_path / "extra.md").write_bytes(b"An explicit dependency.")
    result = StartupReader(tmp_path).read(["rule-0.md"], task="deployment")
    paths = [record["path"] for record in _payload(result.context)["files"]]
    assert paths.count("rule-0.md") == 1
    assert "extra.md" in paths


def test_recalled_data_does_not_expand_startup_declarations(tmp_path: Path) -> None:
    raw = b"MUST READ: missing-example.md\n"
    _ = seed(tmp_path, body=raw)
    result = StartupReader(tmp_path).read([], task="deployment")
    assert body_from(result.context, "rule-0.md") == raw
    assert result.coverage.complete


def test_changed_bytes_invalidate_task_read_with_preserved_stat(tmp_path: Path) -> None:
    _ = seed(tmp_path, body=b"First revision.")
    reader = StartupReader(tmp_path)
    before = reader.read([], task="deployment")
    path = tmp_path / "rule-0.md"
    stat = path.stat()
    _ = path.write_bytes(b"Other revision.")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    after = reader.read([], task="deployment")

    assert not after.cache_hit
    assert body_from(after.context, path.name) == b"Other revision."
    assert not reader.verify(before.context, [], task="deployment").complete


def test_forged_task_receipt_fails_even_with_valid_block_certificates(tmp_path: Path) -> None:
    _ = seed(tmp_path)
    reader = StartupReader(tmp_path)
    payload = _payload(reader.read([], task="deployment").context)
    path = ".mnemosyne-memory-index/task"
    forged = b'{"version":1,"matcher":"lexical-v1","matches":[]}'
    payload["blocks"] = [
        block for block in payload["blocks"] if block["path"] != path
    ] + source_blocks(path, forged)
    for record in payload["files"]:
        if record["path"] == path:
            record.update(sha256=digest(forged), bytes=len(forged), lines=1)
    assert not reader.verify(json.dumps(payload), [], task="deployment").complete


@pytest.mark.parametrize("count", [62, 63])
def test_task_sources_obey_the_complete_file_count_bound(tmp_path: Path, count: int) -> None:
    _ = seed(tmp_path, count)
    reader = StartupReader(tmp_path)
    if count == 62:
        result = reader.read([], task="deployment")
        assert result.coverage.files == 64
        assert len(result.matched_entries) == 62
    else:
        with pytest.raises(StartupError):
            _ = reader.read([], task="deployment")


@pytest.mark.parametrize("size", [1_048_576, 1_048_577])
def test_task_document_size_bound_never_returns_a_truncated_body(
    tmp_path: Path, size: int,
) -> None:
    raw = b"x" * size
    _ = seed(tmp_path, body=raw)
    reader = StartupReader(tmp_path)
    if size == 1_048_576:
        result = reader.read([], task="deployment")
        assert body_from(result.context, "rule-0.md") == raw
    else:
        with pytest.raises(StartupError):
            _ = reader.read([], task="deployment")


def test_total_task_source_budget_fails_without_partial_success(tmp_path: Path) -> None:
    _ = seed(tmp_path, 2, b"x" * 1_048_576)
    with pytest.raises(StartupError):
        _ = StartupReader(tmp_path).read([], task="deployment")


def test_missing_matched_document_fails_the_complete_read(tmp_path: Path) -> None:
    _ = seed(tmp_path, 2)
    (tmp_path / "rule-1.md").unlink()
    with pytest.raises(FileNotFoundError):
        _ = StartupReader(tmp_path).read([], task="deployment")
