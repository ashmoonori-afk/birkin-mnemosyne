"""Separate reference timing/RSS replay using a small, stdlib-only parent.

python benchmarks/retrieval/measure_footprint.py --output footprint-main.json

Corpus generation and warm queries run in workers, not in the process spawning
RSS probes. Linux fork/exec can otherwise inherit the benchmark parent's RSS
high-water mark. Quality and install size remain the main runner's measurements.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT)]


class Probe(TypedDict):
    load_ms: float
    peak_rss: int


class Generated(TypedDict):
    query: str


class Warm(TypedDict):
    queries: int
    p50: float
    p95: float
    index_bytes: int


class Footprint(TypedDict):
    engine: str
    size: int
    build_peak_rss: int
    search_peak_rss: int
    startup_wall_ms: list[float]
    startup_median_ms: float
    startup_max_ms: float
    warm: Warm


parse_probe: Callable[[str], Probe] = json.loads
parse_warm: Callable[[str], Warm] = json.loads
parse_generated: Callable[[str], Generated] = json.loads


def worker(mode: str, vault: Path, size: int, engine_name: str) -> None:
    from benchmarks.retrieval import retrieval_corpus as rc
    from benchmarks.retrieval.bench_retrieval import (
        clear_sidecars,
        percentile,
        sidecar_bytes,
        write_vault,
    )
    from benchmarks.retrieval.engines import ENGINES

    match mode:
        case "generate":
            write_vault(vault, rc.corpus(size, seed=0))
            print(json.dumps({"query": rc.queries()[0].text}))
        case "clear":
            clear_sidecars(vault)
        case "warm":
            engine = ENGINES[engine_name](vault)
            queries = [q for q in rc.queries() if q.split == "test"][:300]
            engine.search(queries[0].text, 10)
            latencies = []
            for query in queries:
                start = time.perf_counter()
                engine.search(query.text, 10)
                latencies.append((time.perf_counter() - start) * 1000)
            print(json.dumps({
                "queries": len(queries),
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "index_bytes": sidecar_bytes(vault),
            }))
        case _:
            raise AssertionError(mode)


def measure() -> list[Footprint]:
    rows: list[Footprint] = []
    for size in (160, 1000, 10000):
        with tempfile.TemporaryDirectory(prefix="mn-footprint-") as directory:
            vault = Path(directory) / "vault"
            base = [sys.executable, str(Path(__file__).resolve()), "--vault",
                    str(vault), "--size", str(size)]
            generated = parse_generated(subprocess.run(
                base + ["--worker", "generate"],
                check=True, capture_output=True, text=True,
            ).stdout)
            for engine in ("bm25", "hybrid"):
                subprocess.run(base + ["--worker", "clear"], check=True)
                probe = [sys.executable, str(HERE / "_probe.py"), engine,
                         str(vault), generated["query"]]
                built = parse_probe(subprocess.run(
                    probe + ["build"], check=True, capture_output=True, text=True,
                ).stdout)
                starts: list[float] = []
                peaks: list[int] = []
                for _ in range(10):
                    start = time.perf_counter()
                    cold = parse_probe(subprocess.run(
                        probe, check=True, capture_output=True, text=True,
                    ).stdout)
                    starts.append((time.perf_counter() - start) * 1000)
                    peaks.append(cold["peak_rss"])
                warmed = parse_warm(subprocess.run(
                    base + ["--worker", "warm", "--engine", engine],
                    check=True, capture_output=True, text=True,
                ).stdout)
                rows.append({
                    "engine": engine, "size": size,
                    "build_peak_rss": built["peak_rss"],
                    "search_peak_rss": max(peaks),
                    "startup_wall_ms": starts,
                    "startup_median_ms": statistics.median(starts),
                    "startup_max_ms": max(starts), "warm": warmed,
                })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("generate", "clear", "warm"))
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--size", type=int)
    parser.add_argument("--engine")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.vault, args.size, args.engine)
        return
    rows = measure()
    result = {
        "revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.strip(),
        "python": platform.python_version(), "platform": platform.platform(),
        "model_cache": os.environ.get("MNEMOSYNE_MODEL_CACHE"),
        "scope": "10 fresh starts per cell; first 300 frozen test queries, warm.",
        "rows": rows, "temporary_vaults_removed": True,
    }
    assert args.output is not None
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
