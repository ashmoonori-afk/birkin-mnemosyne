"""Frozen benchmark arithmetic and real vault lifecycle."""

import hashlib
import inspect
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import pytest

# Release-wheel CI appends the benchmark namespace without shadowing the wheel.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
from benchmarks.memory_triggers import run
from birkin_mnemosyne.memory_index import MemoryIndex, OpenResult
from birkin_mnemosyne.startup import StartupReader


class _Score(TypedDict):
    returned: list[str]
    misses: list[str]
    whole_bodies_match: bool


class _Row(TypedDict):
    id: str
    automatic: _Score
    optional_open: _Score


class _Report(TypedDict):
    rows: list[_Row]


_decode_report: Callable[[str], _Report] = json.loads


def test_score_exposes_misses_extras_and_partial_bodies() -> None:
    documents = {"a.md": "whole a\n", "b.md": "whole b\n", "c.md": "whole c\n"}
    result = run.score(["a.md", "b.md"], {"a.md": "whole a", "c.md": "whole c\n"},
                       documents)
    assert result.misses == ["b.md"]
    assert result.extras == ["c.md"]
    assert result.body_matches == {"a.md": False, "c.md": True}
    assert not result.whole_bodies_match
    assert not result.passed
    assert run.score([], {}, documents).passed
    assert not run.score([], {"c.md": documents["c.md"]}, documents).passed
    positive_extra = run.score(["a.md"],
                               {"a.md": documents["a.md"], "c.md": documents["c.md"]},
                               documents)
    assert positive_extra.passed
    assert positive_extra.extras == ["c.md"]


def test_fixture_bytes_are_frozen_and_mutation_is_rejected(tmp_path: Path) -> None:
    raw = run.FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == run.FIXTURE_SHA256
    fixture = run.load_fixture()
    documents, routes = run.grown_corpus(fixture["grown"])
    assert len(documents) == 240
    assert len(routes) == 480
    changed = tmp_path / "fixture.json"
    _ = changed.write_bytes(raw + b"\n")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        _ = run.load_fixture(changed)


def test_baseline_scores_real_startup_and_open_and_cleans_vaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "caller-state")
    def count_bytes(text: str) -> dict[str, int]:
        return {"utf8_bytes": len(text.encode("utf-8"))}
    monkeypatch.setattr(run, "size", count_bytes)
    roots: list[Path] = []
    calls: list[tuple[str, int]] = []
    real_seed = run.seed
    real_open = MemoryIndex.open

    def observed_seed(
        root: Path, documents: dict[str, str], routes: list[run.Route],
        *, budget: int | None = None,
    ) -> MemoryIndex:
        roots.append(root.parent)
        return real_seed(root, documents, routes, budget=budget)

    def observed_open(index: MemoryIndex, query: str, *, limit: int = 3) -> OpenResult:
        calls.append((query, limit))
        return real_open(index, query, limit=limit)
    monkeypatch.setattr(run, "seed", observed_seed)
    monkeypatch.setattr(MemoryIndex, "open", observed_open)
    result = run.measure(baseline=True)
    assert os.environ["MNEMOSYNE_SEMANTIC"] == "caller-state"
    assert result["temporary_vault_removed"]
    assert roots and all(not root.exists() for root in roots)
    assert calls == [(task["task"], 3) for task in run.load_fixture()["tasks"]]
    # Inspect serialized output just as a report consumer does.
    rows = _decode_report(json.dumps(result))["rows"]
    database = next(row for row in rows if row["id"] == "database")
    assert database["automatic"]["returned"] == []
    assert database["automatic"]["misses"] == ["engineering/database.md"]
    assert "engineering/database.md" in database["optional_open"]["returned"]
    assert database["optional_open"]["whole_bodies_match"]
    assert result["startup_verified"]


def test_failed_read_cleans_real_seeded_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "caller-state")
    roots: list[Path] = []

    def failed_read(reader: StartupReader, paths: list[str]) -> None:
        assert paths == []
        assert reader.memory_index.read().enabled
        roots.append(reader.root.parent)
        raise RuntimeError("forced startup failure")
    monkeypatch.setattr(StartupReader, "read", failed_read)
    with pytest.raises(RuntimeError, match="forced startup failure"):
        _ = run.measure(baseline=True)
    assert roots and all(not root.exists() for root in roots)
    assert os.environ["MNEMOSYNE_SEMANTIC"] == "caller-state"


def test_context_scoring_uses_complete_actual_source_blocks(tmp_path: Path) -> None:
    documents = {"topic/a.md": "# A\n\nfirst\n\nsecond\n"}
    index = run.seed(tmp_path, documents, [{"trigger": "alpha", "document": "topic/a.md"}])
    reader = StartupReader(index.root)
    bundle = reader.read(["topic/a.md"])
    assert reader.verify(bundle.context, ["topic/a.md"]).complete
    assert run.context_bodies(bundle.context) == documents


def test_task_delivery_or_explicit_missing_api_failure(tmp_path: Path) -> None:
    documents = {"topic/a.md": "# A\n\ncomplete alpha body\n"}
    index = run.seed(tmp_path, documents, [{"trigger": "alpha", "document": "topic/a.md"}])
    reader = StartupReader(index.root)
    if "task" not in inspect.signature(StartupReader.read).parameters:
        with pytest.raises(RuntimeError, match="task-aware"):
            _ = run.measure()
        return
    bundle, coverage = run.task_bundle(reader, "alpha")
    assert coverage.complete
    assert run.score(["topic/a.md"], run.context_bodies(bundle.context), documents).passed
