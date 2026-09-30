"""Retrieval benchmark: quality, latency, and footprint per engine.

Runs every query of ``retrieval_corpus`` against a real vault on disk at
several corpus sizes (gold-only 160, then padded to 1k / 10k notes) and
reports, per split (dev/test) and query kind (exact/para/mixed):

  R@1, R@5, MRR@10, nDCG@10         (one gold note per query)
  latency p50 / p95                  (warm, per query, includes refresh())
  index bytes on disk                (every sidecar the engine persists)
  build time, cold start, peak RSS   (cold = fresh process: import + load
                                      the on-disk index + first query)
  install size                       (--install-size: fresh venv, site-
                                      packages delta of the package + extra)

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
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import retrieval_corpus as rc

from birkin_mnemosyne.mnemosyne import INDEX_FILE, Mnemosyne

REPO = Path(__file__).resolve().parents[2]

K = 10
CREATED = "2026-01-01T00:00:00+00:00"


class Engine(Protocol):
    name: str

    def build(self) -> None: ...

    def search(self, query: str, k: int) -> list[str]: ...

    def index_bytes(self) -> int: ...


class BM25Engine:
    """The library's own search path (BM25 + dynamics/zone boosts)."""

    name = "bm25"

    def __init__(self, vault: Path):
        self.vault = vault
        self.dex = Mnemosyne(vault)

    def build(self) -> None:
        self.dex.rebuild()

    def search(self, query: str, k: int) -> list[str]:
        return [h["slug"] for h in self.dex.search(query, limit=k)]

    def index_bytes(self) -> int:
        p = self.vault / INDEX_FILE
        return p.stat().st_size if p.exists() else 0


ENGINES: dict[str, type] = {"bm25": BM25Engine}


# -- metrics ------------------------------------------------------------------

def rank_metrics(ranks: list[int | None]) -> dict[str, float]:
    """1-based gold ranks (None = not in top K) -> R@1, R@5, MRR, nDCG@10."""
    n = len(ranks) or 1
    return {
        "r@1": sum(r is not None and r <= 1 for r in ranks) / n,
        "r@5": sum(r is not None and r <= 5 for r in ranks) / n,
        "mrr": sum(1.0 / r for r in ranks if r is not None) / n,
        "ndcg@10": sum(1.0 / math.log2(r + 1)
                       for r in ranks if r is not None and r <= 10) / n,
        "n": len(ranks),
    }


def percentile(xs: list[float], p: float) -> float:
    """Linear-interpolated percentile (numpy's default method)."""
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * p / 100.0
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


# -- vault + evaluation ---------------------------------------------------------

def write_vault(vault: Path, notes: list[rc.Note]) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for n in notes:
        (vault / f"{n.slug}.md").write_text(
            f"---\ntitle: {n.title}\ncreated: {CREATED}\n---\n\n{n.body}\n",
            encoding="utf-8")


def evaluate(engine: Engine, queries: list[rc.Query], k: int = K) -> dict[str, Any]:
    by_kind: dict[tuple[str, str], list[int | None]] = {}
    by_lang: dict[tuple[str, str], list[int | None]] = {}
    by_kind_lang: dict[tuple[str, str, str], list[int | None]] = {}
    lat: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        hits = engine.search(q.text, k)
        lat.append((time.perf_counter() - t0) * 1000.0)
        rank = hits.index(q.gold) + 1 if q.gold in hits else None
        by_kind.setdefault((q.split, q.kind), []).append(rank)
        by_lang.setdefault((q.split, q.lang), []).append(rank)
        by_kind_lang.setdefault((q.split, q.kind, q.lang), []).append(rank)
    return {
        "by_kind": {key: rank_metrics(r) for key, r in by_kind.items()},
        "by_lang": {key: rank_metrics(r) for key, r in by_lang.items()},
        "by_kind_lang": {key: rank_metrics(r) for key, r in by_kind_lang.items()},
        "latency_ms": {"p50": percentile(lat, 50), "p95": percentile(lat, 95)},
    }


# -- cold start / RSS probe (runs in a fresh interpreter) ------------------------

def _maxrss_bytes() -> int:
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def _probe(engine_name: str, vault: Path, query: str) -> None:
    t0 = time.perf_counter()
    engine = ENGINES[engine_name](vault)
    engine.search(query, K)
    cold_ms = (time.perf_counter() - t0) * 1000.0
    print(json.dumps({"cold_ms": cold_ms, "peak_rss": _maxrss_bytes()}))


def cold_start(engine_name: str, vault: Path, query: str) -> dict[str, float]:
    out = subprocess.run(
        [sys.executable, __file__, "--probe", engine_name, str(vault), query],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out.strip().splitlines()[-1])


# -- install size ---------------------------------------------------------------

def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def install_size(extra: str | None = None) -> int:
    """Bytes a fresh venv's site-packages grows by for ``.`` or ``.[extra]``
    (non-editable install; pip itself is excluded by diffing a bare venv)."""
    target = f"{REPO}[{extra}]" if extra else str(REPO)
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "venv"
        uv = shutil.which("uv")
        if uv:
            subprocess.run([uv, "venv", "-q", "-p", sys.executable, str(venv)],
                           check=True)
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
        return _dir_bytes(site) - before


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
                           index_bytes=engine.index_bytes(),
                           **cold_start(name, vault, qs[0].text))
                results.append(res)
    return results


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def render(results: list[dict[str, Any]], split: str = "test") -> str:
    head = "| engine | notes | {} | R@1 | R@5 | MRR | nDCG@10 |"
    lines = [f"### Quality by language ({split} split, all query kinds, k={K})", "",
             head.format("lang"), "|---|---|---|---|---|---|---|"]
    for r in results:
        for lang in rc.LANGS:
            m = r["by_lang"][(split, lang)]
            lines.append(f"| {r['engine']} | {r['size']} | {lang} | {m['r@1']:.3f} "
                         f"| {m['r@5']:.3f} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |")
    lines += ["", f"### Quality by query kind ({split} split, all languages)", "",
              head.format("kind"), "|---|---|---|---|---|---|---|"]
    for r in results:
        for kind in rc.QUERY_KINDS:
            m = r["by_kind"][(split, kind)]
            lines.append(f"| {r['engine']} | {r['size']} | {kind} | {m['r@1']:.3f} "
                         f"| {m['r@5']:.3f} | {m['mrr']:.3f} | {m['ndcg@10']:.3f} |")
    lines += ["", f"### MRR by language x kind ({split} split)", "",
              "| engine | notes | lang | " + " | ".join(rc.QUERY_KINDS) + " |",
              "|---|---|---|" + "---|" * len(rc.QUERY_KINDS)]
    for r in results:
        for lang in rc.LANGS:
            cells = " | ".join(f"{r['by_kind_lang'][(split, kind, lang)]['mrr']:.3f}"
                               for kind in rc.QUERY_KINDS)
            lines.append(f"| {r['engine']} | {r['size']} | {lang} | {cells} |")
    lines += ["", "### Footprint", "",
              "| engine | notes | index on disk | build | p50 | p95 | cold start | peak RSS |",
              "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lat = r["latency_ms"]
        lines.append(f"| {r['engine']} | {r['size']} | {_fmt_bytes(r['index_bytes'])} "
                     f"| {r['build_s']:.2f} s | {lat['p50']:.1f} ms | {lat['p95']:.1f} ms "
                     f"| {r['cold_ms']:.0f} ms | {_fmt_bytes(r['peak_rss'])} |")
    return "\n".join(lines)


def _jsonable(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        r = dict(r)
        r["by_kind"] = {"/".join(k): v for k, v in r["by_kind"].items()}
        r["by_lang"] = {"/".join(k): v for k, v in r["by_lang"].items()}
        r["by_kind_lang"] = {"/".join(k): v for k, v in r["by_kind_lang"].items()}
        out.append(r)
    return out


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--probe":
        _probe(argv[1], Path(argv[2]), argv[3])
        return
    ap = argparse.ArgumentParser(description="Retrieval benchmark (quality + footprint)")
    ap.add_argument("--sizes", type=int, nargs="+", default=[160, 1000])
    ap.add_argument("--engines", nargs="+", default=["bm25"], choices=sorted(ENGINES))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--split", default="test", choices=["dev", "test"])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--install-size", action="store_true")
    args = ap.parse_args(argv)

    results = run(args.sizes, args.engines, seed=args.seed)
    print(f"python {platform.python_version()} · {platform.system()} {platform.machine()}")
    print(render(results, args.split))
    extra: dict[str, int] = {}
    if args.install_size:
        extra["core"] = install_size(None)
        print(f"\ninstall size (core, no extras): {_fmt_bytes(extra['core'])}")
    if args.json:
        args.json.write_text(json.dumps({"results": _jsonable(results),
                                         "install_bytes": extra}, indent=1))


if __name__ == "__main__":
    main()
