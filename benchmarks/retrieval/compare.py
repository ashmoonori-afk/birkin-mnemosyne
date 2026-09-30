"""Before/after tables from two bench_retrieval.py --json outputs.

    python compare.py BEFORE.json AFTER.json [--split test] [--label-before X --label-after Y]
    python compare.py RUN.json RUN.json --engine-before bm25 --engine-after hybrid
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LANGS = ("en", "ko", "ja", "zh", "es", "de")
KINDS = ("exact", "para", "mixed")


def load(path: Path, engine: str | None = None) -> dict[int, dict[str, Any]]:
    """Rows by corpus size; ``engine`` picks one engine from a run of several."""
    rows = json.loads(path.read_text())["results"]
    return {r["size"]: r for r in rows if engine in (None, r["engine"])}


def fmt(a: float, b: float) -> str:
    d = b - a
    mark = "+" if d > 0.0005 else ("-" if d < -0.0005 else "=")
    return f"{a:.3f} -> {b:.3f} ({mark}{abs(d):.3f})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--split", default="test")
    ap.add_argument("--label-before", default="before")
    ap.add_argument("--label-after", default="after")
    ap.add_argument("--engine-before", help="engine to read from BEFORE (one file, two engines)")
    ap.add_argument("--engine-after", help="engine to read from AFTER")
    a = ap.parse_args()
    before, after = load(a.before, a.engine_before), load(a.after, a.engine_after)
    sp = a.split
    print(f"### {a.label_before} -> {a.label_after} ({sp} split): R@5 and MRR per slice\n")
    print("| notes | slice | n | R@5 | MRR |")
    print("|---|---|---|---|---|")
    for size in sorted(set(before) & set(after)):
        b, f = before[size], after[size]
        for lang in LANGS:
            k = f"{sp}/{lang}"
            mb, mf = b["by_lang"][k], f["by_lang"][k]
            print(f"| {size} | {lang} | {mf['n']:.0f} | {fmt(mb['r@5'], mf['r@5'])} | {fmt(mb['mrr'], mf['mrr'])} |")
        for kind in KINDS:
            k = f"{sp}/{kind}"
            mb, mf = b["by_kind"][k], f["by_kind"][k]
            print(f"| {size} | {kind} (all langs) | {mf['n']:.0f} | {fmt(mb['r@5'], mf['r@5'])} | {fmt(mb['mrr'], mf['mrr'])} |")
    if all("by_author_kind" in r for r in list(before.values()) + list(after.values())):
        print(f"\n### MRR per query author ({sp} split)\n")
        print("| notes | author | " + " | ".join(KINDS) + " |")
        print("|---|---|" + "---|" * len(KINDS))
        for size in sorted(set(before) & set(after)):
            authors = sorted({k.split("/")[1] for k in after[size]["by_author_kind"]})
            for au in authors:
                cells = [fmt(before[size]["by_author_kind"][f"{sp}/{au}/{kd}"]["mrr"],
                             after[size]["by_author_kind"][f"{sp}/{au}/{kd}"]["mrr"]) for kd in KINDS]
                print(f"| {size} | {au} | " + " | ".join(cells) + " |")
    if all("by_author_lang" in r for r in list(before.values()) + list(after.values())):
        for metric, label in (("mrr", "MRR"), ("r@5", "R@5")):
            print(f"\n### {label} per query author and language ({sp} split)\n")
            print("| notes | author | " + " | ".join(LANGS) + " |")
            print("|---|---|" + "---|" * len(LANGS))
            for size in sorted(set(before) & set(after)):
                authors = sorted({k.split("/")[1] for k in after[size]["by_author_lang"]})
                for au in authors:
                    cells = [fmt(before[size]["by_author_lang"][f"{sp}/{au}/{lang}"][metric],
                                 after[size]["by_author_lang"][f"{sp}/{au}/{lang}"][metric])
                             for lang in LANGS]
                    print(f"| {size} | {au} | " + " | ".join(cells) + " |")
    if all("ranks" in r for r in list(before.values()) + list(after.values())):
        print(f"\n### Queries whose gold rank improved / worsened ({sp} split)\n")
        print("| notes | " + " | ".join(LANGS + KINDS) + " |")
        print("|---|" + "---|" * len(LANGS + KINDS))
        for size in sorted(set(before) & set(after)):
            pairs = [(x, y) for x, y in zip(before[size]["ranks"], after[size]["ranks"])
                     if x[0] == sp]
            cells = []
            for pos, values in ((1, LANGS), (2, KINDS)):
                for value in values:
                    mine = [(x[4] or 99, y[4] or 99) for x, y in pairs if x[pos] == value]
                    cells.append(f"{sum(b < a for a, b in mine)} up / "
                                 f"{sum(b > a for a, b in mine)} down of {len(mine)}")
            print(f"| {size} | " + " | ".join(cells) + " |")
    print("\n### Footprint\n")
    print("| notes | index on disk | p50 | p95 | cold wall | peak RSS | build peak RSS |")
    print("|---|---|---|---|---|---|---|")
    for size in sorted(set(before) & set(after)):
        b, f = before[size], after[size]
        build = (f"{b['build_peak_rss']/1e6:.0f} -> {f['build_peak_rss']/1e6:.0f} MB"
                 if b.get("build_peak_rss") and f.get("build_peak_rss") else "n/a")
        print(f"| {size} | {b['index_bytes']/1e6:.2f} MB -> {f['index_bytes']/1e6:.2f} MB "
              f"| {b['latency_ms']['p50']:.1f} -> {f['latency_ms']['p50']:.1f} ms "
              f"| {b['latency_ms']['p95']:.1f} -> {f['latency_ms']['p95']:.1f} ms "
              f"| {b['cold_wall_ms']:.0f} -> {f['cold_wall_ms']:.0f} ms "
              f"| {b['peak_rss']/1e6:.0f} -> {f['peak_rss']/1e6:.0f} MB | {build} |")


if __name__ == "__main__":
    main()
