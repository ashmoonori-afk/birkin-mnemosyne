"""Measure the hosted judge's merged scores on frozen question sets.

Every paid request goes through ``Meter``, which caches by packet hash, counts
reported tokens and stops before the budget passes. Set OPENGATEWAY_API_KEY.

    python benchmarks/unanswerable/judge.py score --split tune --sizes 1000 \\
        --cache cache.jsonl --out tune-1000.jsonl
    python benchmarks/unanswerable/judge.py sweep --scores tune-*.jsonl --out sweep.json
    python benchmarks/unanswerable/judge.py rows --scores test-*.jsonl --threshold 0.5 \\
        --out gate.json

Baseline is ``--threshold 0``: the five notes kept without any filter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.append(str(ROOT / "benchmarks" / "retrieval"))

from birkin_mnemosyne import crosslingual
from birkin_mnemosyne.kibitzer import KibitzerAdapter
from birkin_mnemosyne.mnemosyne import tokenize

QUESTIONS = HERE / "questions.json"
PRICE = 6.3e-9
LIST_PRICE = 1.26e-7
RETRIES = 4
GRID = [round(0.05 * step, 2) for step in range(1, 20)]


class BudgetStop(RuntimeError):
    """The next request could pass the spending limit."""


class Meter:
    """Cached, counted and budget-capped access to the judge."""

    def __init__(self, cache: str, budget: float) -> None:
        self.path, self.budget = Path(cache), budget
        self.lock = threading.Lock()
        self.answers: dict[str, dict[str, Any]] = {}
        self.spent_tokens = self.new_tokens = self.requests = self.hits = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.answers[row["key"]] = row["response"]
                self.spent_tokens += row["response"]["usage"]["input_tokens"]
        self.remote = crosslingual.opengateway_decider()

    def spent(self) -> float:
        return self.spent_tokens * PRICE

    def _ask(self, packet: dict[str, Any]) -> Mapping[str, Any]:
        for attempt in range(RETRIES):
            try:
                return self.remote(packet)
            except crosslingual.RerankError:
                if attempt == RETRIES - 1:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def __call__(self, packet: dict[str, Any]) -> Mapping[str, Any]:
        text = json.dumps(packet, ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(text.encode()).hexdigest()
        with self.lock:
            known = self.answers.get(key)
            if known is not None:
                self.hits += 1
                return known
            if self.spent() >= self.budget:
                raise BudgetStop(f"spent USD {self.spent():.4f} of {self.budget}")
        response = dict(self._ask(packet))
        with self.lock:
            self.answers[key] = response
            self.requests += 1
            tokens = response["usage"]["input_tokens"]
            self.spent_tokens += tokens
            self.new_tokens += tokens
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "response": response}) + "\n")
        return response


def questions(split: str, sets: list[str], rc: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if "U" in sets:
        for item in json.loads(QUESTIONS.read_text(encoding="utf-8")):
            if item["split"] == split:
                out.append({"set": "U", "text": item["text"], "siblings": [],
                            **{key: item[key] for key in
                               ("id", "stratum", "lang", "form", "group")}})
    if "A1" in sets:
        wanted = "dev" if split == "tune" else "test"
        queries = [q for q in rc.queries() if q.split == wanted]
        if split == "tune":
            queries += rc.dev_extra_queries()
        out += [{"set": "A1", "text": q.text, "kind": q.kind, "lang": q.lang,
                 "author": q.author, "gold": q.gold + ".md",
                 "siblings": sorted(f"{slug}.md" for slug in q.siblings)} for q in queries]
    return out


def score_size(size: int, cases: list[dict[str, Any]], meter: Meter, br: Any, rc: Any,
               threads: int, out: Any) -> None:
    with tempfile.TemporaryDirectory(prefix="mnemosyne-judge-") as directory:
        vault = Path(directory)
        br.write_vault(vault, rc.corpus(size))
        adapter = KibitzerAdapter(vault)
        snapshot = adapter._snapshot(False)
        adapter._snapshot = lambda force_refresh=False: snapshot  # type: ignore[method-assign]
        index = crosslingual._CosineIndex(snapshot.postings, len(snapshot.documents))
        done = threading.Lock()

        def one(case: dict[str, Any]) -> None:
            scored, _ = crosslingual.scored_top(
                adapter, case["text"], decide=meter, exclude_paths=case["siblings"],
                workers=1, cosine_index=index)
            terms = set(tokenize(case["text"]))
            row = {**case, "size": size, "top": [
                [card.path, score, all(card.path in snapshot.postings.get(term, ())
                                       for term in terms)] for card, score in scored]}
            with done:
                out.write(json.dumps(row, ensure_ascii=True) + "\n")
                out.flush()

        with ThreadPoolExecutor(threads) as pool:
            list(pool.map(one, cases))


def score(args: argparse.Namespace) -> None:
    import bench_retrieval as br
    import retrieval_corpus as rc
    meter = Meter(args.cache, args.budget)
    cases = questions(args.split, args.sets, rc)
    with open(args.out, "w", encoding="utf-8") as out:
        for size in args.sizes:
            start = time.perf_counter()
            score_size(size, cases, meter, br, rc, args.threads, out)
            print(size, len(cases), f"new={meter.requests} cached={meter.hits} "
                  f"tokens={meter.new_tokens} spent={meter.spent():.4f} "
                  f"{time.perf_counter() - start:.0f}s", flush=True)


def load(paths: list[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for path in paths
            for line in Path(path).read_text(encoding="utf-8").splitlines()]


def kept(row: dict[str, Any], threshold: float, exact: bool) -> list[str]:
    return [path for path, value, whole in row["top"]
            if value >= threshold or (exact and whole)]


def to_rows(scored: list[dict[str, Any]], threshold: float, exact: bool) -> list[dict[str, Any]]:
    rows = []
    for row in scored:
        paths = kept(row, threshold, exact)
        if row["set"] == "U":
            rows.append({key: row[key] for key in
                         ("set", "size", "id", "stratum", "lang", "form", "group")}
                        | {"surfaced": paths})
        else:
            rank = paths.index(row["gold"]) + 1 if row["gold"] in paths else None
            rows.append({key: row[key] for key in ("set", "size", "kind", "lang", "author")}
                        | {"rank": rank, "surfaced": len(paths)})
    return rows


def sweep(args: argparse.Namespace) -> None:
    from compare import check_retrieval, reduction, wsr
    scored = load(args.scores)
    sizes = sorted({row["size"] for row in scored})
    base = to_rows(scored, 0.0, False)
    table = []
    for exact in (False, True):
        for threshold in GRID:
            gate = to_rows(scored, threshold, exact)
            line: dict[str, Any] = {"threshold": threshold, "exact": exact}
            passed = True
            for size in sizes:
                checks: dict[str, Any] = {}
                check_retrieval(base, gate, size, checks)
                failed = [key for key, value in checks.items() if value.get("pass") is False]
                passed = passed and not failed

                def pick(rows: list[dict[str, Any]], stratum: str | None,
                         at: int = size) -> list[dict[str, Any]]:
                    return [row for row in rows if row["set"] == "U" and row["size"] == at and
                            (stratum is None or row["stratum"] == stratum)]

                line[str(size)] = {
                    "pooled": reduction(wsr(pick(base, None)), wsr(pick(gate, None))),
                    "offtopic": reduction(wsr(pick(base, "offtopic")),
                                          wsr(pick(gate, "offtopic"))),
                    "near": reduction(wsr(pick(base, "near")), wsr(pick(gate, "near"))),
                    "base_wsr": wsr(pick(base, None)), "gate_wsr": wsr(pick(gate, None)),
                    "para": checks[f"R1:para@{size}"]["drop_points"],
                    "mixed": checks[f"R1:mixed@{size}"]["drop_points"],
                    "all": checks[f"R1:all@{size}"]["drop_points"],
                    "exact_lost": checks[f"R2:exact@{size}"]["lost"], "failed": failed}
            line["within_limits"] = passed
            table.append(line)
    Path(args.out).write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8")
    for line in table:
        print(line["threshold"], "exact" if line["exact"] else "-", line["within_limits"], [
            (size, round(line[str(size)]["pooled"], 2), round(line[str(size)]["offtopic"], 2),
             round(line[str(size)]["near"], 2), round(line[str(size)]["para"], 1),
             round(line[str(size)]["mixed"], 1), line[str(size)]["exact_lost"])
            for size in sizes])


def rows(args: argparse.Namespace) -> None:
    out = to_rows(load(args.scores), args.threshold, args.exact)
    Path(args.out).write_text(json.dumps({"threshold": args.threshold, "rows": out},
                                         ensure_ascii=True) + "\n", encoding="utf-8")
    print(args.out, len(out))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("score")
    run.add_argument("--split", choices=("tune", "test"), required=True)
    run.add_argument("--sets", nargs="+", default=["U", "A1"])
    run.add_argument("--sizes", nargs="+", type=int, required=True)
    run.add_argument("--cache", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--budget", type=float, default=1.60)
    run.add_argument("--threads", type=int, default=min(12, os.cpu_count() or 4))
    table = commands.add_parser("sweep")
    table.add_argument("--scores", nargs="+", required=True)
    table.add_argument("--out", required=True)
    output = commands.add_parser("rows")
    output.add_argument("--scores", nargs="+", required=True)
    output.add_argument("--threshold", type=float, required=True)
    output.add_argument("--exact", action="store_true")
    output.add_argument("--out", required=True)
    args = parser.parse_args()
    {"score": score, "sweep": sweep, "rows": rows}[args.command](args)


if __name__ == "__main__":
    main()
