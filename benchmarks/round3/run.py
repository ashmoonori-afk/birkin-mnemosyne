"""Frozen, author-separated round-3 measurements; missing authors stay missing."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import tiktoken

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "retrieval"), str(HERE.parents[1])]

from benchmarks.retrieval import retrieval_corpus as corpus
from benchmarks.retrieval.bench_retrieval import (
    gold_rank,
    percentile,
    rank_metrics,
    write_vault,
)
from benchmarks.round3.answerer import answer
from benchmarks.round3.startup_answerer import answer as startup_answer
from benchmarks.round3.startup_answerer import documents
from birkin_mnemosyne import (
    Answer,
    Consolidation,
    IdentityReader,
    StartupReader,
    VaultMemory,
)
from birkin_mnemosyne.kibitzer import KibitzerAdapter

ENCODER = tiktoken.get_encoding("o200k_base")


def timed(call):
    start = time.perf_counter()
    result = call()
    return result, (time.perf_counter() - start) * 1000


def context_size(text):
    return {"characters": len(text), "utf8_bytes": len(text.encode("utf-8")),
            "tokens_estimated_chars_div_4": len(text) / 4,
            "tokens_measured_o200k_base": len(ENCODER.encode(text, disallowed_special=()))}


def consolidation(data):
    rows = []
    for case in data["consolidation"]:
        with tempfile.TemporaryDirectory(prefix="mnemosyne-r3-pair-") as directory:
            root = Path(directory)
            memory = VaultMemory({"vault_path": directory})
            for title, body in zip(case["titles"], case["bodies"], strict=True):
                memory.write_note(title, body, source="frozen:" + case["id"])
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
            service = Consolidation(root)
            questions, elapsed = timed(service.questions)
            assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
            restored = None
            if questions:
                question = questions[0]
                receipt = service.apply(question, Answer(
                    question.id, "merge", "\n\n".join(case["bodies"]),
                ))
                service.undo(receipt.transaction_id)
                restored = before == {
                    p.relative_to(root): p.read_bytes() for p in root.rglob("*.md")}
                assert restored
            rows.append({"id": case["id"], "gold_related": case["related"],
                         "before_detected": False, "after_detected": bool(questions),
                         "question_ms": elapsed, "explicit_merge_restore": restored})
        assert not root.exists()
    tp = sum(r["gold_related"] and r["after_detected"] for r in rows)
    predicted = sum(r["after_detected"] for r in rows)
    positives = sum(r["gold_related"] for r in rows)
    return {"author": data["author"], "rows": rows,
            "baseline": "No explicit user-question detector",
            "after_precision": tp / predicted if predicted else None,
            "after_recall": tp / positives if positives else None,
            "question_p50_ms": statistics.median(r["question_ms"] for r in rows)}


def identity(data):
    rows = []
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r3-identity-") as directory:
        root = Path(directory)
        path = root / "AGENTS.md"
        path.write_bytes(data["identity"]["document"].encode("utf-8"))
        reader = IdentityReader(root)
        for question in data["identity"]["questions"]:
            full, full_ms = timed(lambda: path.read_text("utf-8"))
            result, read_ms = timed(lambda question=question: reader.search(
                "AGENTS.md", question["query"], limit=1))
            common = (question["section"], question["field"])
            rows.append({
                "id": question["id"],
                "before_correct": answer(full, *common) == question["answer"],
                "after_correct": answer(result.context, *common) == question["answer"],
                "full_ms": full_ms, "reader_ms": read_ms,
                "full_context": context_size(full),
                "reader_context": context_size(result.context),
            })
    assert not root.exists()
    return {"author": data["author"], "rows": rows,
            "before_accuracy": sum(r["before_correct"] for r in rows) / len(rows),
            "after_accuracy": sum(r["after_correct"] for r in rows) / len(rows),
            "scope": "Supplemental excerpts; not complete startup"}


def startup(data):
    fixture = data["startup"]
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r3-startup-") as directory:
        root = Path(directory)
        files = {record["path"]: record["text"] for record in fixture["files"]}
        for record in fixture.get("long_material", []):
            files[record["path"]] += "".join(
                record["line_template"].format(i=i) for i in range(record["count"]))
            files[record["path"]] += record["tail"]
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))

        def full_read():
            return json.dumps({"files": [{"path": name, "text": (root / name).read_text("utf-8")}
                                         for name in files]}, ensure_ascii=False)

        full, full_ms = timed(full_read)
        reader = StartupReader(root)
        result, cold_ms = timed(lambda: reader.read(["MODE.md"]))
        warm, warm_ms = timed(lambda: reader.read(["MODE.md"]))
        supplied = documents(result.context)
        assert result.coverage.complete and warm.cache_hit
        assert supplied == files
        rows = [{"id": q["id"],
                 "before_correct": startup_answer(full, q) == q["answer"],
                 "after_correct": startup_answer(result.context, q) == q["answer"]}
                for q in fixture["questions"]]
        missing = [item for item in fixture["required_items"]
                   if item["text"] not in supplied.get(item["source"], "")]
        fresh = {}
        for mode, paths in (("startup", ["MODE.md"]), ("full", list(files))):
            process, wall_ms = timed(lambda mode=mode, paths=paths: subprocess.run(
                [sys.executable, str(HERE / "_probe.py"), mode, str(root), *paths],
                check=True, capture_output=True, text=True))
            fresh[mode] = {**json.loads(process.stdout), "process_wall_ms": wall_ms}
        measured = {
            "author": data["author"], "rows": rows,
            "before_accuracy": sum(r["before_correct"] for r in rows) / len(rows),
            "after_accuracy": sum(r["after_correct"] for r in rows) / len(rows),
            "missing_required_items": missing,
            "complete": result.coverage.complete,
            "files": result.coverage.files, "covered_lines": result.coverage.lines,
            "source_bytes": result.coverage.bytes,
            "full_ms": full_ms, "cold_ms": cold_ms, "warm_ms": warm_ms,
            "full_context": context_size(full),
            "complete_context": context_size(result.context),
            "fresh_process": fresh,
            "baseline": "Full read of the entire known fixture closure",
        }
    assert not root.exists()
    return measured


def kibitzer():
    """Historical frozen queries are regression evidence, not new authored sets."""
    groups = {}
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r3-recall-") as directory:
        root = Path(directory)
        knowledge = root / "knowledge"
        write_vault(knowledge, corpus.corpus())
        memory = VaultMemory({"vault_path": directory})
        adapter = KibitzerAdapter(root)
        for query in corpus.queries():
            before, before_ms = timed(lambda query=query: memory.search(query.text, limit=10))
            after, after_ms = timed(lambda query=query: adapter.select(query.text, limit=10))
            before_slugs = [hit["title"] for hit in before]
            after_slugs = [Path(hit.path).stem for hit in after]
            key = (query.author, query.split, query.kind)
            bucket = groups.setdefault(key, {"before": [], "after": [],
                                             "before_ms": [], "after_ms": []})
            bucket["before"].append(gold_rank(before_slugs, query.gold, query.siblings))
            bucket["after"].append(gold_rank(after_slugs, query.gold, query.siblings))
            bucket["before_ms"].append(before_ms)
            bucket["after_ms"].append(after_ms)
    assert not root.exists()
    return [{"author": author, "split": split, "kind": kind,
             "before": rank_metrics(values["before"]),
             "after": rank_metrics(values["after"]),
             "before_p95_ms": percentile(values["before_ms"], 95),
             "after_p95_ms": percentile(values["after_ms"], 95),
             "scope": "Historical frozen retrieval; top-1 precision equals hit@1"}
            for (author, split, kind), values in sorted(groups.items())]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    hashes: dict[str, str] = {}
    pairs = []
    excerpts = []
    complete = []
    missing: list[str] = []
    for name in ("frozen_sol.json", "frozen_claude.json",
                 "frozen_sol_startup.json", "frozen_claude_startup.json"):
        path = HERE / name
        if not path.exists():
            missing.append(name)
            continue
        raw = path.read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
        if "consolidation" in data:
            pairs.append(consolidation(data))
        if "identity" in data:
            excerpts.append(identity(data))
        if "startup" in data:
            complete.append(startup(data))
    for path in [HERE / "answerer.py", HERE / "startup_answerer.py",
                 HERE.parent / "retrieval" / "retrieval_corpus.py",
                 *(HERE.parent / "retrieval" / name for name in corpus.AUTHOR_FILES.values())]:
        hashes[str(path.relative_to(HERE.parent))] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"evaluation_hashes": hashes, "consolidation": pairs, "identity": excerpts,
              "startup": complete, "missing_author_sets": missing, "kibitzer": kibitzer(),
              "accuracy_scope": "Fixed context-only extraction, not generative compliance",
              "token_scope": "Measured o200k_base BPE over whole contexts; not GPT6.1/Claude billing claims",
              "both_new_authors_verified": not missing,
              "cleanup": "All per-case temporary directories removed and absence asserted"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(json.dumps({"output": str(args.output),
                      "both_new_authors_verified": result["both_new_authors_verified"],
                      "missing_author_sets": result["missing_author_sets"],
                      "cleanup": result["cleanup"]}))


if __name__ == "__main__":
    main()
