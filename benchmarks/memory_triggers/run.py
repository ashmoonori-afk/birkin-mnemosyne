"""Frozen public full-body delivery benchmark; no model calls.

Run: python -m benchmarks.memory_triggers.run --output results.json
Use --baseline with release 0.6.0 for route-only startup and separate open hits.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

from benchmarks.memory_index.baseline import size
from benchmarks.memory_triggers.topic_costs import measure_topics
from birkin_mnemosyne.memory_index import IndexEntry, MemoryIndex
from birkin_mnemosyne.startup import StartupBundle, StartupReader
from birkin_mnemosyne.startup_coverage import Coverage, StartupPayload

FIXTURE = Path(__file__).with_name("fixture.json")
FIXTURE_SHA256 = "a482f7f3af566c392aa6ca2cf7890f6ce48adfcb8e133571adcfc3d52a3936de"


class Route(TypedDict):
    trigger: str
    document: str


class Task(TypedDict):
    id: str
    task: str
    required: list[str]


class Grown(TypedDict):
    topic_count: int
    documents_per_topic: int
    aliases_per_document: int
    path_pattern: str
    trigger_patterns: list[str]
    body_pattern: str
    token_budget: int
    scope: str


class Fixture(TypedDict):
    version: int
    scope: str
    documents: dict[str, str]
    routes: list[Route]
    tasks: list[Task]
    grown: Grown
    protocol: dict[str, str]


_decode_fixture: Callable[[bytes], Fixture] = json.loads
_decode_context: Callable[[str], StartupPayload] = json.loads


@runtime_checkable
class TaskReader(Protocol):
    def read(self, paths: Sequence[str], *, task: str) -> StartupBundle: ...

    def verify(self, context: str, paths: Sequence[str], *, task: str) -> Coverage: ...


@dataclass(frozen=True, slots=True)
class Score:
    required: list[str]
    returned: list[str]
    misses: list[str]
    extras: list[str]
    whole_bodies_match: bool
    body_matches: dict[str, bool]
    passed: bool


def load_fixture(path: Path = FIXTURE) -> Fixture:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError("frozen public fixture SHA-256 mismatch")
    return _decode_fixture(raw)


def score(required: Sequence[str], returned: Mapping[str, str],
          documents: Mapping[str, str]) -> Score:
    """Score actual returned bodies, including unexpected or incomplete documents."""
    misses = sorted(set(required) - returned.keys())
    extras = sorted(returned.keys() - set(required))
    matches = {path: path in documents and body == documents[path]
               for path, body in returned.items()}
    whole = all(matches.values())
    return Score(list(required), list(returned), misses, extras, whole, matches,
                 not misses and whole and (bool(required) or not extras))


def context_bodies(context: str) -> dict[str, str]:
    """Reassemble actual source blocks, excluding only synthetic routing sources."""
    payload = _decode_context(context)
    bodies: dict[str, str] = {}
    for record in payload["files"]:
        path = record["path"]
        prefix = ".mnemosyne-memory-index/documents/"
        if path.startswith(prefix):
            document = path[len(prefix):]
        elif path.startswith(".mnemosyne-memory-index"):
            continue
        else:
            document = path
        blocks = sorted((block for block in payload["blocks"] if block["path"] == path),
                        key=lambda block: block["start_byte"])
        bodies[document] = "".join(block["text"] for block in blocks)
    return bodies


def seed(root: Path, documents: Mapping[str, str], routes: Sequence[Route],
         *, budget: int | None = None) -> MemoryIndex:
    """Use the product registration API as the only routing authority."""
    index = MemoryIndex(root)
    for name, text in documents.items():
        path = index.document_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_bytes(text.encode("utf-8"))
    for route in routes:
        _ = index.register(route["trigger"], route["document"], max_tokens=budget)
    if index.read().entries != tuple(IndexEntry(**route) for route in routes):
        raise ValueError("registration did not retain every frozen route")
    return index


def grown_corpus(shape: Grown) -> tuple[dict[str, str], list[Route]]:
    documents: dict[str, str] = {}
    routes: list[Route] = []
    if len(shape["trigger_patterns"]) != shape["aliases_per_document"]:
        raise ValueError("grown alias patterns do not match the frozen shape")
    for topic in range(shape["topic_count"]):
        for document in range(shape["documents_per_topic"]):
            fields = {"topic": topic, "document": document}
            path = shape["path_pattern"].format(**fields)
            documents[path] = shape["body_pattern"].format(**fields)
            routes.extend({"trigger": pattern.format(**fields), "document": path}
                          for pattern in shape["trigger_patterns"])
    return documents, routes


def task_bundle(reader: object, task: str) -> tuple[StartupBundle, Coverage]:
    """Missing task API or matched-entry receipts are hard failures, not baselines."""
    if not isinstance(reader, TaskReader):
        raise TypeError("task-aware startup reader is required")
    bundle = reader.read([], task=task)
    if not hasattr(bundle, "matched_entries"):
        raise RuntimeError("StartupBundle.matched_entries is required")
    return bundle, reader.verify(bundle.context, [], task=task)


def product_metadata() -> dict[str, str | None]:
    root = Path(inspect.getfile(StartupReader)).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    def git(*args: str) -> str | None:
        result = subprocess.run(["git", "-C", str(root), *args],
                                capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    return {"product_root": str(root), "product_source_sha256": digest.hexdigest(),
            "revision": git("rev-parse", "HEAD"),
            "committed_product_tree": git("rev-parse", "HEAD:birkin_mnemosyne")}


def measure(*, baseline: bool = False) -> dict[str, object]:
    fixture = load_fixture()
    if not baseline and any("task" not in inspect.signature(method).parameters
                            for method in (StartupReader.read, StartupReader.verify)):
        raise RuntimeError("task-aware StartupReader.read/verify API is required")
    # Explicit open can fall back to search; keep it lexical with no model loading.
    previous = os.environ.get("MNEMOSYNE_SEMANTIC")
    os.environ["MNEMOSYNE_SEMANTIC"] = "0"
    try:
        with tempfile.TemporaryDirectory(prefix="mn-triggers-") as directory:
            root = Path(directory)
            index = seed(root / "sample", fixture["documents"], fixture["routes"])
            reader = StartupReader(index.root)
            startup = reader.read([])
            startup_verified = reader.verify(startup.context, []).complete
            rows: list[dict[str, object]] = []
            failed: list[str] = []
            for task in fixture["tasks"]:
                if baseline:
                    bundle = reader.read([])
                    verified = reader.verify(bundle.context, []).complete
                else:
                    bundle, coverage = task_bundle(reader, task["task"])
                    verified = coverage.complete
                bodies = context_bodies(bundle.context)
                delivered = score(task["required"], bodies, fixture["documents"])
                if not verified or not delivered.passed:
                    failed.append(task["id"])
                opened = index.open(task["task"], limit=3)
                optional = score(task["required"],
                                 {item.path: item.content for item in opened.documents},
                                 fixture["documents"])
                opened_payload = json.dumps(asdict(opened), ensure_ascii=False,
                                            separators=(",", ":"))
                entries: tuple[IndexEntry, ...] = getattr(bundle, "matched_entries", ())
                rows.append({
                    "id": task["id"], "task": task["task"],
                    "automatic": asdict(delivered), "verified": verified,
                    "matched_entries": [asdict(entry) for entry in entries],
                    "documents": bodies, "context": bundle.context,
                    "task_context": size(bundle.context),
                    "resident_plus_task_context": size(index.render() + "\n" + bundle.context),
                    "task_context_sha256": hashlib.sha256(bundle.context.encode()).hexdigest(),
                    "optional_open": {**asdict(optional), "matched_by": opened.matched_by},
                    "optional_opened_payload": size(opened_payload),
                    "optional_document_bodies": size("\n\n".join(
                        item.content for item in opened.documents)),
                })
            documents, routes = grown_corpus(fixture["grown"])
            grown = seed(root / "grown", documents, routes,
                         budget=fixture["grown"]["token_budget"])
            view = grown.read()
            grown_reader = StartupReader(grown.root)
            grown_bundle = grown_reader.read([])
            grown_verified = grown_reader.verify(grown_bundle.context, []).complete
            graph = measure_topics(grown, tuple(IndexEntry(**route) for route in routes), size)
            graph_verified = (
                graph["all_routes_expandable"] is not False
                and graph["all_topics_in_resident"] is not False
                and (baseline or graph["mode"] == "grouped")
            )
            result: dict[str, object] = {
                "mode": "release-route-only" if baseline else "task-aware",
                "fixture_sha256": FIXTURE_SHA256, "product": product_metadata(),
                "scope": fixture["scope"], "rows": rows,
                "automatic_failed_tasks": failed,
                "rendered_index": size(index.render()),
                "whole_startup_payload": size(startup.context),
                "startup_verified": startup_verified,
                "grown": {
                    "documents": len(documents), "routes": len(view.entries),
                    "rendered_index": size(view.context),
                    "whole_startup_payload": size(grown_bundle.context),
                    "verified": grown_verified,
                    **graph,
                },
                "passed": (startup_verified and grown_verified and graph_verified
                           and (baseline or not failed)),
            }
        result["temporary_vault_removed"] = not root.exists()
        return result

    finally:
        if previous is None:
            _ = os.environ.pop("MNEMOSYNE_SEMANTIC", None)
        else:
            os.environ["MNEMOSYNE_SEMANTIC"] = previous

class _Arguments(argparse.Namespace):
    output: Path | None = None
    baseline: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args(namespace=_Arguments())
    result = measure(baseline=args.baseline)
    assert args.output is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _ = args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "passed": result["passed"],
        "automatic_failed_tasks": result["automatic_failed_tasks"],
        "rendered_index": result["rendered_index"],
        "whole_startup_payload": result["whole_startup_payload"],
        "grown": result["grown"],
        "temporary_vault_removed": result["temporary_vault_removed"],
    }, indent=2, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
