"""Frozen, query-only INDEX measurements; no model calls or private data.

Run: python -m benchmarks.memory_index.run --output results.json
Install tiktoken separately for this benchmark, never for the core package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict

from benchmarks.memory_index.baseline import size
from benchmarks.memory_index.sample import make_sample
from benchmarks.round3.answerer import answer
from benchmarks.round4.run import check_inputs
from birkin_mnemosyne.memory_index import MemoryIndex
from birkin_mnemosyne.memory_index_integrity import check_index
from birkin_mnemosyne.memory_index_migration import split_note
from birkin_mnemosyne.startup import StartupReader

ROOT = Path(__file__).resolve().parents[2]
AUTHOR_FILES = (
    ("gpt-6.1-sol", "benchmarks/round3/frozen_sol.json"),
    ("anthropic-subscription/claude-opus-5-5", "benchmarks/round3/frozen_claude_identity.json"),
)


class ScoreRow(TypedDict):
    id: str
    positive: bool
    before_correct: bool
    after_correct: bool


class Counts(TypedDict):
    total: int
    before_correct: int
    after_correct: int


class ScoreSummary(TypedDict):
    all: Counts
    positive: Counts
    abstention: Counts
    regressions: list[str]
    improvements: list[str]


class QuestionResult(ScoreRow):
    query: str
    before_answer: str | None
    after_answer: str | None
    expected: str | None
    matched_by: str
    paths: list[str]
    loaded_context_sha256: str
    additional_document_bodies: dict[str, int]
    opened_payload: dict[str, int]
    total_task_context: dict[str, int]


class AuthorResult(TypedDict):
    author: str
    fixture: str
    fixture_sha256: str
    summary: ScoreSummary
    rows: list[QuestionResult]
    always_loaded_before: dict[str, int]
    always_loaded_after: dict[str, int]
    scope: str
    temporary_vault_removed: bool


class FrozenQuestion(TypedDict):
    id: str
    query: str
    section: str
    field: str
    answer: str | None


class FrozenIdentity(TypedDict):
    document: str
    questions: list[FrozenQuestion]


class FrozenAuthor(TypedDict):
    author: str
    identity: FrozenIdentity


# The immutable-input guard validates these exact fixture bytes before scoring.
_load_fixture: Callable[[str], FrozenAuthor] = json.loads


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _counts(rows: Sequence[ScoreRow]) -> Counts:
    return {
        "total": len(rows),
        "before_correct": sum(row["before_correct"] for row in rows),
        "after_correct": sum(row["after_correct"] for row in rows),
    }


def score_summary(rows: Sequence[ScoreRow]) -> ScoreSummary:
    """Separate positives/abstentions and expose regressions despite equal totals."""
    return {
        "all": _counts(rows),
        "positive": _counts([row for row in rows if row["positive"]]),
        "abstention": _counts([row for row in rows if not row["positive"]]),
        "regressions": [
            row["id"] for row in rows if row["before_correct"] and not row["after_correct"]],
        "improvements": [
            row["id"] for row in rows if row["after_correct"] and not row["before_correct"]],
    }


def synthetic() -> dict[str, object]:
    sample = make_sample()
    with tempfile.TemporaryDirectory(prefix="mn-index-cost-") as directory:
        root = Path(directory)
        for name, text in sample.items():
            _ = (root / name).write_bytes(text.encode("utf-8"))
        before = StartupReader(root).read(list(sample)).context
        coverage: list[dict[str, object]] = []
        for name, text in sample.items():
            report = split_note(root, name, apply=True)
            restored = b"".join(
                (root / topic.document).read_bytes()[topic.prefix_bytes:]
                for topic in report.topics
            )
            assert restored == text.encode("utf-8")
            assert [row.text for row in report.coverage] == text.splitlines(keepends=True)
            coverage.append({
                "source": name, "bytes": report.source_bytes,
                "lines": len(report.coverage), "topics": len(report.topics),
                "source_sha256": report.source_sha256, "byte_exact": True,
            })
        checked = check_index(root)
        assert checked.ok, checked
        after = StartupReader(root).read(list(sample)).context
        index = MemoryIndex(root).read()
        result = {
            "before": size(before), "after": size(after),
            "complete_index": size(index.context),
            "source_sizes": {name: size(text) for name, text in sample.items()},
            "coverage": coverage, "integrity": {**asdict(checked), "ok": checked.ok},
            "index_entries": len(index.entries), "index_budget": index.max_tokens,
            "index_over_budget": index.over_budget,
            "scope": "Whole StartupReader.context including instructions and certificates.",
        }
    assert not root.exists()
    return {**result, "temporary_vault_removed": True}


def author_result(author: str, relative: str) -> AuthorResult:
    fixture = _load_fixture((ROOT / relative).read_text(encoding="utf-8"))
    assert fixture["author"] == author
    document = fixture["identity"]["document"]
    with tempfile.TemporaryDirectory(prefix="mn-index-author-") as directory:
        root = Path(directory)
        _ = (root / "AGENTS.md").write_bytes(document.encode("utf-8"))
        report = split_note(root, "AGENTS.md", apply=True)
        assert "".join(row.text for row in report.coverage) == document
        assert check_index(root).ok
        index = MemoryIndex(root)
        resident = index.render()
        rows: list[QuestionResult] = []
        for question in fixture["identity"]["questions"]:
            # Only the frozen natural-language query enters routing. Neither
            # section/field nor gold answer is supplied to the router.
            opened = index.open(question["query"], limit=3)
            context = "\n\n".join(item.content for item in opened.documents)
            payload = json.dumps(asdict(opened), ensure_ascii=False, separators=(",", ":"))
            before = answer(document, question["section"], question["field"])
            after = answer(context, question["section"], question["field"])
            rows.append({
                "id": question["id"], "query": question["query"],
                "positive": question["answer"] is not None,
                "before_answer": before, "after_answer": after,
                "expected": question["answer"],
                "before_correct": before == question["answer"],
                "after_correct": after == question["answer"],
                "matched_by": opened.matched_by,
                "paths": [item.path for item in opened.documents],
                "loaded_context_sha256": sha(context.encode("utf-8")),
                "additional_document_bodies": size(context),
                "opened_payload": size(payload),
                "total_task_context": size(resident + "\n" + payload),
            })
        result: AuthorResult = {
            "author": author, "fixture": relative,
            "fixture_sha256": sha((ROOT / relative).read_bytes()),
            "summary": score_summary(rows), "rows": rows,
            "always_loaded_before": size(document),
            "always_loaded_after": size(resident),
            "temporary_vault_removed": False,
            "scope": (
                "Constrained extraction, not agent compliance. Before is the full "
                "original Markdown. After residency is the complete rendered INDEX; "
                "task totals add the full serialized OpenResult, including paths."
            ),
        }
    assert not root.exists()
    result["temporary_vault_removed"] = True
    return result


class _Arguments(argparse.Namespace):
    output: Path | None = None


def main() -> None:
    import tiktoken

    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(namespace=_Arguments())
    assert args.output is not None
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "birkin_mnemosyne"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    if dirty:
        raise ValueError("commit the product tree before measuring it")
    inputs = check_inputs()
    previous = os.environ.get("MNEMOSYNE_SEMANTIC")
    os.environ["MNEMOSYNE_SEMANTIC"] = "0"
    try:
        cost = synthetic()
        authors = [author_result(author, path) for author, path in AUTHOR_FILES]
    finally:
        if previous is None:
            _ = os.environ.pop("MNEMOSYNE_SEMANTIC", None)
        else:
            os.environ["MNEMOSYNE_SEMANTIC"] = previous
    product_tree = subprocess.run(
        ["git", "rev-parse", "HEAD:birkin_mnemosyne"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    frozen = {record["path"]: record["raw_sha256"] for record in inputs["files"]}
    artifacts = ("run.py", "sample.py", "baseline.py", "baseline.json", "PROTOCOL.md")
    result = {
        "version": 1, "product_tree": product_tree,
        "benchmark_sha256": {
            name: sha((Path(__file__).parent / name).read_bytes()) for name in artifacts},
        "frozen_input_sha256": frozen,
        "frozen_manifest_sha256": sha((ROOT / "benchmarks/round4/frozen-manifest.json").read_bytes()),
        "synthetic": cost, "authors": authors,
        "accuracy_preserved_for_both": all(not a["summary"]["regressions"] for a in authors),
        "accuracy_gain_for_both": all(
            a["summary"]["all"]["after_correct"] > a["summary"]["all"]["before_correct"]
            for a in authors),
        "runtime": {"python": sys.version, "platform": platform.platform(),
                    "tiktoken": tiktoken.__version__, "encoding": "o200k_base",
                    "semantic": "disabled"},
        "limits": [
            "Recorded independent authorship; reused public fixtures, not newly unseen questions.",
            "No model calls; deterministic constrained extraction is not general agent compliance.",
            "BPE counts are declared o200k_base units, not GPT/Claude billing.",
            "Host system prompts and JSON-RPC transport envelopes are not billed-token measurements.",
            "Tiny notes can cost more after indexing; per-author and per-task costs are retained.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _ = args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "before": cost["before"], "after": cost["after"],
        "index": cost["complete_index"],
        "authors": [{"author": a["author"], **a["summary"]} for a in authors],
        "accuracy_gain_for_both": result["accuracy_gain_for_both"],
        "cleanup": "All temporary vaults removed; semantic environment restored.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
