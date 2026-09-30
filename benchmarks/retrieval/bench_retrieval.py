"""Retrieval benchmark: quality, latency, and footprint per engine.

Runs every query of ``retrieval_corpus`` against a real vault on disk at
several corpus sizes (gold-only 160, then padded to 1k / 10k notes) and
reports per split (dev/test), per language and per query kind:

  R@1, R@5, MRR@10, nDCG@10   one gold note per query; the gold note's
                              declared cross-language siblings are removed
                              from the ranking before scoring
  latency p50 / p95           warm, per query, wall clock over ALL queries
                              (dev + test pooled; includes the library's
                              per-query index refresh)
  index on disk               every sidecar file in the vault (dot-files)
                              after build + all queries
  build                       full index build
  cold wall / cold load       fresh process running ``_probe.py``: total
                              process wall time (interpreter start included)
                              and in-process library import + index load +
                              first query
  peak RSS                    of that fresh process
  install size                --install-size: fresh venv, site-packages
                              growth excluding __pycache__

    python benchmarks/retrieval/bench_retrieval.py                  # 160 + 1k
    python benchmarks/retrieval/bench_retrieval.py --sizes 160 1000 10000 \\
        --json /tmp/bench.json --install-size

Numbers are reported on the *test* split; dev exists for tuning (e.g. the
RRF constant) and must not be used to pick what is reported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import retrieval_corpus as rc
from engines import ENGINES, BM25Engine, Engine

__all__ = ["BM25Engine", "Engine", "evaluate", "main", "rank_metrics", "write_vault"]

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
K = 10
CREATED = "2026-01-01T00:00:00+00:00"


# -- metrics ------------------------------------------------------------------

def rank_metrics(ranks: list[int | None]) -> dict[str, float]:
    """1-based gold ranks (None = not in top K) -> R@1, R@5, MRR, nDCG@10, n."""
    n = len(ranks) or 1
    return {
        "r@1": sum(r is not None and r <= 1 for r in ranks) / n,
        "r@5": sum(r is not None and r <= 5 for r in ranks) / n,
        "mrr": sum(1.0 / r for r in ranks if r is not None) / n,
        "ndcg@10": sum(1.0 / math.log2(r + 1)
                       for r in ranks if r is not None and r <= 10) / n,
        "n": float(len(ranks)),
    }


def percentile(xs: list[float], p: float) -> float:
    """Linear-interpolated percentile (numpy's default method)."""
    if not xs:
        raise ValueError("percentile of an empty list")
    s = sorted(xs)
    pos = (len(s) - 1) * p / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def gold_rank(hits: list[str], gold: str, siblings: frozenset[str],
              k: int = K) -> int | None:
    """Rank of ``gold`` after dropping its declared siblings, within top k."""
    ranked = [h for h in hits if h not in siblings][:k]
    return ranked.index(gold) + 1 if gold in ranked else None


# -- vault + evaluation ---------------------------------------------------------

def write_vault(vault: Path, notes: list[rc.Note]) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for n in notes:
        (vault / f"{n.slug}.md").write_text(
            f"---\ntitle: {n.title}\ncreated: {CREATED}\nupdated: {CREATED}\n"
            f"---\n\n{n.body}\n", encoding="utf-8")


def sidecar_bytes(vault: Path) -> int:
    total = 0
    for p in vault.iterdir():
        if not p.name.startswith("."):
            continue
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return total


def evaluate(engine: Engine, queries: list[rc.Query], k: int = K) -> dict[str, Any]:
    by_kind: dict[tuple[str, str], list[int | None]] = {}
    by_lang: dict[tuple[str, str], list[int | None]] = {}
    by_kind_lang: dict[tuple[str, str, str], list[int | None]] = {}
    by_author_kind: dict[tuple[str, str, str], list[int | None]] = {}
    by_author_lang: dict[tuple[str, str, str], list[int | None]] = {}
    lat: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        hits = engine.search(q.text, k + len(q.siblings))
        lat.append((time.perf_counter() - t0) * 1000.0)
        rank = gold_rank(hits, q.gold, q.siblings, k)
        by_kind.setdefault((q.split, q.kind), []).append(rank)
        by_lang.setdefault((q.split, q.lang), []).append(rank)
        by_kind_lang.setdefault((q.split, q.kind, q.lang), []).append(rank)
        by_author_kind.setdefault((q.split, q.author, q.kind), []).append(rank)
        by_author_lang.setdefault((q.split, q.author, q.lang), []).append(rank)
    return {
        "by_kind": {key: rank_metrics(r) for key, r in by_kind.items()},
        "by_lang": {key: rank_metrics(r) for key, r in by_lang.items()},
        "by_kind_lang": {key: rank_metrics(r) for key, r in by_kind_lang.items()},
        "by_author_kind": {key: rank_metrics(r) for key, r in by_author_kind.items()},
        "by_author_lang": {key: rank_metrics(r) for key, r in by_author_lang.items()},
        "latency_ms": {"p50": percentile(lat, 50), "p95": percentile(lat, 95)},
    }


def cold_start(engine_name: str, vault: Path, query: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = subprocess.run(
        [sys.executable, str(HERE / "_probe.py"), engine_name, str(vault), query],
        check=True, capture_output=True, text=True).stdout
    wall_ms = (time.perf_counter() - t0) * 1000.0
    probe = json.loads(out.strip().splitlines()[-1])
    return {"cold_wall_ms": wall_ms, "cold_load_ms": probe["load_ms"],
            "peak_rss": probe["peak_rss"]}


# -- install size ---------------------------------------------------------------

def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*")
               if f.is_file() and "__pycache__" not in f.parts)


def install_size(extra: str | None = None) -> tuple[int, str]:
    """(bytes a fresh venv's site-packages grows by for ``.`` or ``.[extra]``,
    installer used). Non-editable install; bytecode caches are excluded so
    pip and uv report comparable numbers."""
    target = f"{REPO}[{extra}]" if extra else str(REPO)
    uv = shutil.which("uv")
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        if uv:
            subprocess.run([uv, "venv", "-q", "-p", sys.executable, str(venv)], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        site = next(venv.glob("lib/python*/site-packages"), None) \
            or venv / "Lib" / "site-packages"
        before = _dir_bytes(site)
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if uv:
            subprocess.run([uv, "pip", "install", "-q", "--python", str(py), target],
                           check=True)
        else:
            subprocess.run([str(py), "-m", "pip", "install", "-q", target], check=True)
        return _dir_bytes(site) - before, "uv" if uv else "pip"


# -- driver -------------------------------------------------------------------------

def run(sizes: list[int], engines: list[str], seed: int = 0) -> list[dict[str, Any]]:
    qs = rc.queries()
    results = []
    for size in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            write_vault(vault, rc.corpus(size, seed=seed))
            for name in engines:
                engine = ENGINES[name](vault)
                t0 = time.perf_counter()
                engine.build()
                build_s = time.perf_counter() - t0
                res = evaluate(engine, qs)
                res.update(engine=name, size=size, build_s=build_s,
                           index_bytes=sidecar_bytes(vault),
                           **cold_start(name, vault, qs[0].text))
                results.append(res)
    return results


def _fmt_bytes(n: float | None) -> str:
    if n is None:
        return "n/a"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def render(results: list[dict[str, Any]], split: str = "test") -> str:
    head = "| engine | notes | {} | n | R@1 | R@5 | MRR | nDCG@10 |"
    sep = "|---|---|---|---|---|---|---|---|"

    def row(r: dict[str, Any], label: str, m: dict[str, float]) -> str:
        return (f"| {r['engine']} | {r['size']} | {label} | {m['n']:.0f} | {m['r@1']:.3f} "
                f"| {m['r@5']:.3f} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |")

    lines = [f"### Quality by language ({split} split, all query kinds, k={K})", "",
             head.format("lang"), sep]
    lines += [row(r, lang, r["by_lang"][(split, lang)])
              for r in results for lang in rc.LANGS]
    lines += ["", f"### Quality by query kind ({split} split, all languages)", "",
              head.format("kind"), sep]
    lines += [row(r, kind, r["by_kind"][(split, kind)])
              for r in results for kind in rc.QUERY_KINDS]
    lines += ["", f"### MRR by language x kind ({split} split)", "",
              "| engine | notes | lang | " + " | ".join(rc.QUERY_KINDS) + " |",
              "|---|---|---|" + "---|" * len(rc.QUERY_KINDS)]
    for r in results:
        for lang in rc.LANGS:
            cells = " | ".join(f"{r['by_kind_lang'][(split, kind, lang)]['mrr']:.3f}"
                               for kind in rc.QUERY_KINDS)
            lines.append(f"| {r['engine']} | {r['size']} | {lang} | {cells} |")
    authors = sorted({a for r in results for (_, a, _) in r["by_author_kind"]})
    lines += ["", f"### MRR by query author ({split} split)", "",
              "| engine | notes | author | " + " | ".join(rc.QUERY_KINDS) + " | "
              + " | ".join(rc.LANGS) + " |",
              "|---|---|---|" + "---|" * (len(rc.QUERY_KINDS) + len(rc.LANGS))]
    for r in results:
        for author in authors:
            cells = [f"{r['by_author_kind'][(split, author, kind)]['mrr']:.3f}"
                     for kind in rc.QUERY_KINDS]
            cells += [f"{r['by_author_lang'][(split, author, lang)]['mrr']:.3f}"
                      for lang in rc.LANGS]
            lines.append(f"| {r['engine']} | {r['size']} | {author} | "
                         + " | ".join(cells) + " |")
    lines += ["", "### Footprint (latency pooled over dev + test queries)", "",
              ("| engine | notes | index on disk | build | p50 | p95 | cold wall "
               "| cold load | peak RSS |"),
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        lat = r["latency_ms"]
        lines.append(f"| {r['engine']} | {r['size']} | {_fmt_bytes(r['index_bytes'])} "
                     f"| {r['build_s']:.2f} s | {lat['p50']:.1f} ms | {lat['p95']:.1f} ms "
                     f"| {r['cold_wall_ms']:.0f} ms | {r['cold_load_ms']:.0f} ms "
                     f"| {_fmt_bytes(r['peak_rss'])} |")
    return "\n".join(lines)


def _jsonable(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        r = dict(r)
        for key in ("by_kind", "by_lang", "by_kind_lang", "by_author_kind",
                    "by_author_lang"):
            r[key] = {"/".join(k): v for k, v in r[key].items()}
        out.append(r)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Retrieval benchmark (quality + footprint)")
    ap.add_argument("--sizes", type=int, nargs="+", default=[160, 1000])
    ap.add_argument("--engines", nargs="+", default=["bm25"], choices=sorted(ENGINES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--install-size", action="store_true")
    args = ap.parse_args(argv)

    results = run(args.sizes, args.engines, seed=args.seed)
    print(f"git {_git_sha()} · python {platform.python_version()} · "
          f"{platform.system()} {platform.machine()}")
    print(render(results, args.split))
    install: dict[str, Any] = {}
    if args.install_size:
        size, installer = install_size(None)
        install = {"core": size, "installer": installer}
        print(f"\ninstall size (core, no extras, {installer}): {_fmt_bytes(size)}")
    if args.json:
        args.json.write_text(json.dumps({"results": _jsonable(results),
                                         "install": install}, indent=1))


if __name__ == "__main__":
    main()
