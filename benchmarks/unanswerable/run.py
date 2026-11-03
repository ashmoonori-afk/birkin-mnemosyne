"""Measure ``KibitzerAdapter.select()`` of one checkout on frozen question sets.

Each run records what one checkout surfaces, one row per query, so a baseline
and a gated checkout can be compared afterwards with ``compare.py``:

    python benchmarks/unanswerable/run.py --repo <checkout> --split tune \\
        --sets unanswerable retrieval --sizes 160 1000 10000 --out tune.json
    python benchmarks/unanswerable/run.py --repo <checkout> --mode latency \\
        --sizes 1000 10000 --out latency.json
    python benchmarks/unanswerable/run.py --repo <checkout> --mode large \\
        --index <dir> --cases <questions.json> <labels.json> --out large.json

``--repo`` picks the package under test; questions and vaults always come from
this checkout, so both arms see identical bytes. The large mode serves a
disk-backed snapshot because the 718,911-passage corpus is far above what the
adapter's file scan supports; ranking still runs through the public ``select``.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
QUESTIONS = HERE / "questions.json"
CASE_LIMIT = 5
COLD_RUNS = 5


def load_package(repo: str) -> Any:
    """Import the package under test first, so bench modules cannot shadow it."""
    sys.path.insert(0, str(Path(repo).resolve()))
    import birkin_mnemosyne
    from birkin_mnemosyne.kibitzer import KibitzerAdapter
    return birkin_mnemosyne, KibitzerAdapter


def bench_modules() -> tuple[Any, Any]:
    sys.path.append(str(ROOT / "benchmarks" / "retrieval"))
    import bench_retrieval as br
    import retrieval_corpus as rc
    return br, rc


def head(repo: str) -> str:
    done = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True)
    return done.stdout.strip()


def unanswerable_rows(adapter: Any, size: int, split: str) -> list[dict[str, Any]]:
    rows = []
    for item in json.loads(QUESTIONS.read_text(encoding="utf-8")):
        if item["split"] != split:
            continue
        hits = adapter.select(item["text"], limit=CASE_LIMIT)
        rows.append({"set": "U", "size": size, "id": item["id"], "stratum": item["stratum"],
                     "lang": item["lang"], "form": item["form"], "group": item["group"],
                     "surfaced": [hit.path for hit in hits]})
    return rows


def retrieval_rows(adapter: Any, size: int, split: str, br: Any, rc: Any) -> list[dict[str, Any]]:
    wanted = "dev" if split == "tune" else "test"
    queries = [q for q in rc.queries() if q.split == wanted]
    if split == "tune":
        queries += rc.dev_extra_queries()
    rows = []
    for query in queries:
        hits = adapter.select(query.text, limit=CASE_LIMIT + len(query.siblings))
        slugs = [hit.path.removesuffix(".md") for hit in hits]
        rows.append({"set": "A1", "size": size, "kind": query.kind, "lang": query.lang,
                     "author": query.author,
                     "rank": br.gold_rank(slugs, query.gold, query.siblings, CASE_LIMIT),
                     "surfaced": len(slugs)})
    return rows


def run_vaults(args: argparse.Namespace, adapter_type: Any) -> list[dict[str, Any]]:
    br, rc = bench_modules()
    rows: list[dict[str, Any]] = []
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="mnemosyne-unanswerable-") as directory:
            vault = Path(directory)
            br.write_vault(vault, rc.corpus(size))
            adapter = adapter_type(vault)
            if "unanswerable" in args.sets:
                rows += unanswerable_rows(adapter, size, args.split)
            if "retrieval" in args.sets:
                rows += retrieval_rows(adapter, size, args.split, br, rc)
    return rows


def run_latency(args: argparse.Namespace, adapter_type: Any) -> list[dict[str, Any]]:
    br, rc = bench_modules()
    texts = [q.text for q in rc.queries()]
    rows: list[dict[str, Any]] = []
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="mnemosyne-latency-") as directory:
            vault = Path(directory)
            br.write_vault(vault, rc.corpus(size))
            cold = [cold_probe(args.repo, vault, texts[0]) for _ in range(COLD_RUNS)]
            adapter = adapter_type(vault)
            _ = adapter.select(texts[0], limit=3)
            warm = []
            for text in texts:
                start = time.perf_counter()
                _ = adapter.select(text, limit=3)
                warm.append((time.perf_counter() - start) * 1000)
            rows.append({"size": size, "cold_ms": cold,
                         "warm_p50_ms": br.percentile(warm, 50),
                         "warm_p95_ms": br.percentile(warm, 95)})
    return rows


def cold_probe(repo: str, vault: Path, text: str) -> float:
    done = subprocess.run(
        [sys.executable, __file__, "--repo", repo, "--mode", "cold", "--vault", str(vault),
         "--text", text], capture_output=True, text=True, check=True)
    return float(done.stdout.strip())


def run_cold(args: argparse.Namespace, adapter_type: Any) -> None:
    adapter = adapter_type(args.vault)
    start = time.perf_counter()
    _ = adapter.select(args.text, limit=3)
    print((time.perf_counter() - start) * 1000)


_ADAPTER: Any = None


def _large_row(case: dict[str, Any]) -> dict[str, Any]:
    hits = [hit.path for hit in _ADAPTER.select(case["query"], limit=CASE_LIMIT)]
    row = {key: case.get(key) for key in ("key", "id", "queryLanguage", "stratum", "lang")}
    gold = case.get("gold")
    if gold is not None:
        row["rank"] = next((i + 1 for i, path in enumerate(hits) if path in gold), None)
    row["surfaced"] = len(hits)
    return row


def run_large(args: argparse.Namespace, adapter_type: Any) -> list[dict[str, Any]]:
    global _ADAPTER
    sys.path.append(str(HERE))
    from large_index import load_snapshot
    questions = json.loads(Path(args.cases[0]).read_text(encoding="utf-8"))
    labels = {row["key"]: row for row in json.loads(Path(args.cases[1]).read_text(encoding="utf-8"))}
    cases = [{**q, "stratum": labels[q["key"]]["stratum"], "gold": set(labels[q["key"]]["gold"])}
             for q in questions]
    with tempfile.TemporaryDirectory(prefix="mnemosyne-large-") as directory:
        adapter = adapter_type(directory)
        snapshot = load_snapshot(args.index)
        adapter._snapshot = lambda force_refresh=False: snapshot
        _ADAPTER = adapter
        with multiprocessing.get_context("fork").Pool(args.workers) as pool:
            return pool.map(_large_row, cases, chunksize=8)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--mode", choices=("vault", "latency", "large", "cold"), default="vault")
    parser.add_argument("--sets", nargs="+", default=["unanswerable", "retrieval"])
    parser.add_argument("--split", choices=("tune", "test"), default="tune")
    parser.add_argument("--sizes", nargs="+", type=int, default=[160, 1000, 10000])
    parser.add_argument("--index")
    parser.add_argument("--cases", nargs=2)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--vault")
    parser.add_argument("--text")
    parser.add_argument("--out")
    args = parser.parse_args()
    package, adapter_type = load_package(args.repo)
    if args.mode == "cold":
        run_cold(args, adapter_type)
        return
    runner = {"vault": run_vaults, "latency": run_latency, "large": run_large}[args.mode]
    rows = runner(args, adapter_type)
    Path(args.out).write_text(json.dumps({
        "package": package.__file__, "head": head(args.repo), "mode": args.mode,
        "split": args.split, "rows": rows}, ensure_ascii=True) + "\n", encoding="utf-8")
    print(args.out, len(rows))


if __name__ == "__main__":
    main()
