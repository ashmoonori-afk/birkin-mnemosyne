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

    def __init__(self, cache: str, budget: float, reuse: bool = True) -> None:
        self.path, self.budget, self.reuse = Path(cache), budget, reuse
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
            known = self.answers.get(key) if self.reuse else None
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


def five(args: argparse.Namespace) -> None:
    from birkin_mnemosyne.kibitzer import RecallDocument
    questions_ = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    labels = {row["key"]: row for row in json.loads(Path(args.labels).read_text(encoding="utf-8"))}
    picked_rows = json.loads(Path(args.picked).read_text(encoding="utf-8"))["predictions"]
    picked = {row["key"]: row["picked"] for row in picked_rows}
    wanted = {path for key in picked for path in picked[key]}
    documents: dict[str, RecallDocument] = {}
    sample: list[RecallDocument] = []
    with open(args.corpus, encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            doc = RecallDocument(row["path"], row["description"], row["body"])
            if len(sample) < crosslingual.DF_SAMPLE:
                sample.append(doc)
            if doc.path in wanted:
                documents[doc.path] = doc
    df, size = crosslingual.document_frequencies(sample)
    meter = Meter(args.cache, args.budget)
    lock = threading.Lock()

    def one(question: dict[str, Any]) -> dict[str, Any]:
        query, label = question["query"], labels[question["key"]]
        scored = []
        for path in picked[question["key"]]:
            doc = documents[path]
            card = crosslingual.Card(path, doc.description,
                                     crosslingual.passage(query, doc.body, df, size))
            scored.append([path, crosslingual.score_cards(meter, query, [card])[0]])
        return {"set": args.name, "key": question["key"], "stratum": label["stratum"],
                "queryLanguage": question["queryLanguage"], "gold": label["gold"],
                "top": scored}

    with ThreadPoolExecutor(args.threads) as pool, open(args.out, "w", encoding="utf-8") as out:
        for row in pool.map(one, questions_):
            with lock:
                out.write(json.dumps(row, ensure_ascii=True) + "\n")
    print(args.name, len(questions_), f"new={meter.requests} spent={meter.spent():.4f}")


def large_rows(args: argparse.Namespace) -> None:
    out = []
    for row in load(args.scores):
        paths = [path for path, value in row["top"] if value >= args.threshold]
        hit = any(path in row["gold"] for path in paths)
        out.append({"key": row["key"], "stratum": row["stratum"],
                    "queryLanguage": row["queryLanguage"], "rank": 1 if hit else None,
                    "surfaced": len(paths)})
    Path(args.out).write_text(json.dumps({"threshold": args.threshold, "rows": out}) + "\n",
                              encoding="utf-8")
    print(args.out, len(out), sum(row["rank"] is not None for row in out))


def latency(args: argparse.Namespace) -> None:
    import bench_retrieval as br
    import retrieval_corpus as rc
    unanswerable = sorted((item for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))
                           if item["split"] == "tune"), key=lambda item: item["id"])[:20]
    dev = [q for q in rc.queries() if q.split == "dev"][:20]
    texts = [item["text"] for item in unanswerable] + [q.text for q in dev]
    meter = Meter(args.cache, args.budget, reuse=False)
    report: dict[str, Any] = {}
    for size in args.sizes:
        with tempfile.TemporaryDirectory(prefix="mnemosyne-latency-") as directory:
            vault = Path(directory)
            br.write_vault(vault, rc.corpus(size))
            plain = KibitzerAdapter(vault)
            _ = plain.recall(texts[0], rerank=False)
            nokey = []
            for text in texts:
                start = time.perf_counter()
                _ = plain.recall(text, limit=3, rerank=False)
                nokey.append((time.perf_counter() - start) * 1000)
            report[f"{size}:no-key"] = {"p50_ms": br.percentile(nokey, 50),
                                        "p95_ms": br.percentile(nokey, 95)}
            for arm, floor in (("ungated", 0.0), ("gated", args.floor)):
                crosslingual.RELEVANCE_FLOOR = floor
                adapter = KibitzerAdapter(vault, decide=meter)
                walls, requests, tokens, surfaced = [], [], [], []
                for text in texts:
                    before_requests, before_tokens = meter.requests, meter.new_tokens
                    start = time.perf_counter()
                    result = adapter.recall(text, limit=3)
                    walls.append((time.perf_counter() - start) * 1000)
                    assert result.fallback is None, result.fallback
                    requests.append(meter.requests - before_requests)
                    tokens.append(meter.new_tokens - before_tokens)
                    surfaced.append(len(result.candidates))
                cold = [cold_probe(vault, texts[0], floor) for _ in range(5)]
                mean_tokens = sum(tokens) / len(tokens)
                report[f"{size}:{arm}"] = {
                    "p50_ms": br.percentile(walls, 50), "p95_ms": br.percentile(walls, 95),
                    "cold_ms": cold, "requests_per_query": sum(requests) / len(requests),
                    "tokens_per_query": mean_tokens, "usd_per_query": mean_tokens * PRICE,
                    "usd_per_query_list": mean_tokens * LIST_PRICE,
                    "silent_share": sum(n == 0 for n in surfaced) / len(surfaced)}
                print(size, arm, json.dumps(report[f"{size}:{arm}"])[:300], flush=True)
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print("spent", round(meter.spent(), 4))


def cold_probe(vault: Path, text: str, floor: float) -> float:
    import subprocess
    done = subprocess.run([sys.executable, __file__, "cold", "--vault", str(vault),
                           "--text", text, "--floor", str(floor)],
                          capture_output=True, text=True, check=True)
    return float(done.stdout.strip().splitlines()[-1])


def cold(args: argparse.Namespace) -> None:
    crosslingual.RELEVANCE_FLOOR = args.floor
    start = time.perf_counter()
    result = KibitzerAdapter(args.vault, decide=crosslingual.opengateway_decider()).recall(
        args.text, limit=3)
    elapsed = (time.perf_counter() - start) * 1000
    assert result.fallback is None
    print(elapsed)


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
    big = commands.add_parser("five")
    for name in ("name", "questions", "labels", "picked", "corpus", "cache", "out"):
        big.add_argument(f"--{name}", required=True)
    big.add_argument("--budget", type=float, default=3.15)
    big.add_argument("--threads", type=int, default=12)
    big_rows = commands.add_parser("large-rows")
    big_rows.add_argument("--scores", nargs="+", required=True)
    big_rows.add_argument("--threshold", type=float, required=True)
    big_rows.add_argument("--out", required=True)
    timing = commands.add_parser("latency")
    timing.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000])
    timing.add_argument("--floor", type=float, required=True)
    timing.add_argument("--cache", required=True)
    timing.add_argument("--budget", type=float, default=3.15)
    timing.add_argument("--out", required=True)
    probe = commands.add_parser("cold")
    probe.add_argument("--vault", required=True)
    probe.add_argument("--text", required=True)
    probe.add_argument("--floor", type=float, required=True)
    args = parser.parse_args()
    {"score": score, "sweep": sweep, "rows": rows, "five": five, "large-rows": large_rows,
     "latency": latency, "cold": cold}[args.command](args)


if __name__ == "__main__":
    main()
