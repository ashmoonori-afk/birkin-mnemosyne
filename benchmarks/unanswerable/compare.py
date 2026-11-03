"""Score a baseline run against a gated run on the pre-registered ship limits.

    python benchmarks/unanswerable/compare.py --base base.json --gate gate.json \\
        --base-latency base-lat.json --gate-latency gate-lat.json \\
        --base-large-a2 ... --gate-large-a2 ... --base-large-a3 ... --gate-large-a3 ... \\
        --out verdict.json

Limits are copied from the pre-registration and never read from the data. WSR is
the share of questions that surface at least one note. Tune runs pass the same
script with ``--tune``, which skips the large and latency checks.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

SEED = "mn-gate-1103-v1"
DRAWS = 10_000
SIZES = (160, 1000, 10000)
HIT_DEPTH = 5


def load(path: str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["rows"]


def wsr(rows: Iterable[dict[str, Any]]) -> float:
    rows = list(rows)
    return sum(bool(row["surfaced"]) for row in rows) / len(rows)


def reduction(base: float, gate: float) -> float:
    return (base - gate) / base if base else 0.0


def grouped_reduction_lower(base: list[dict[str, Any]], gate: list[dict[str, Any]]) -> float:
    """2.5th percentile of the pooled reduction, resampling sibling groups."""
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for left, right in zip(base, gate, strict=True):
        assert left["id"] == right["id"]
        groups[left["group"]].append((bool(left["surfaced"]), bool(right["surfaced"])))
    names = sorted(groups)
    rng = random.Random(SEED)
    values = []
    for _ in range(DRAWS):
        picked = [row for name in rng.choices(names, k=len(names)) for row in groups[name]]
        before = sum(left for left, _ in picked)
        after = sum(right for _, right in picked)
        values.append((before - after) / before if before else 0.0)
    return statistics.quantiles(values, n=40, method="inclusive")[0]


def hit(row: dict[str, Any]) -> bool:
    return row["rank"] is not None and row["rank"] <= HIT_DEPTH


def drop_points(base: list[dict[str, Any]], gate: list[dict[str, Any]],
                keep: Callable[[dict[str, Any]], bool]) -> float:
    left = [row for row in base if keep(row)]
    right = [row for row in gate if keep(row)]
    return (sum(map(hit, left)) - sum(map(hit, right))) / len(left) * 100


def check_unanswerable(base: list[dict[str, Any]], gate: list[dict[str, Any]],
                       size: int, out: dict[str, Any]) -> None:
    def pick(rows: list[dict[str, Any]], **match: str) -> list[dict[str, Any]]:
        return [row for row in rows if row["set"] == "U" and row["size"] == size and
                all(row[key] == value for key, value in match.items())]

    left, right = pick(base), pick(gate)
    pooled = reduction(wsr(left), wsr(right))
    out[f"U@{size}"] = {"base_wsr": wsr(left), "gate_wsr": wsr(right), "reduction": pooled,
                        "n": len(left)}
    lower = grouped_reduction_lower(left, right)
    out[f"S1@{size}"] = {"reduction": pooled, "ci_lower": lower,
                         "pass": pooled >= 0.60 and lower >= 0.50}
    for stratum, limit in (("offtopic", 0.70), ("near", 0.25)):
        value = reduction(wsr(pick(base, stratum=stratum)), wsr(pick(gate, stratum=stratum)))
        out[f"S2:{stratum}@{size}"] = {"reduction": value, "pass": value >= limit}
    for lang in sorted({row["lang"] for row in left}):
        value = reduction(wsr(pick(base, lang=lang)), wsr(pick(gate, lang=lang)))
        out[f"S3:{lang}@{size}"] = {"reduction": value, "pass": value >= 0.30}


def check_retrieval(base: list[dict[str, Any]], gate: list[dict[str, Any]],
                    size: int, out: dict[str, Any]) -> None:
    left = [row for row in base if row["set"] == "A1" and row["size"] == size]
    right = [row for row in gate if row["set"] == "A1" and row["size"] == size]
    drop = drop_points(left, right, lambda _: True)
    out[f"R1:all@{size}"] = {"drop_points": drop, "pass": drop <= 2.0}
    for kind in ("para", "mixed"):
        drop = drop_points(left, right, lambda row, k=kind: row["kind"] == k)
        out[f"R1:{kind}@{size}"] = {"drop_points": drop, "pass": drop <= 3.0}
    for lang in sorted({row["lang"] for row in left}):
        drop = drop_points(left, right, lambda row, k=lang: row["lang"] == k)
        out[f"R1:{lang}@{size}"] = {"drop_points": drop, "pass": drop <= 3.0}
    lost = sum(hit(a) and not hit(b) for a, b in zip(left, right, strict=True)
               if a["kind"] == "exact")
    out[f"R2:exact@{size}"] = {"lost": lost, "pass": lost == 0}
    out[f"noise@{size}"] = {"base": statistics.mean(row["surfaced"] for row in left),
                            "gate": statistics.mean(row["surfaced"] for row in right)}


def check_large(name: str, base: list[dict[str, Any]], gate: list[dict[str, Any]],
                out: dict[str, Any]) -> None:
    def lost(keep: Callable[[dict[str, Any]], bool]) -> float:
        before = sum(hit(row) for row in base if keep(row))
        after = sum(hit(row) for row in gate if keep(row))
        return (before - after) / before * 100 if before else 0.0

    overall, native = lost(lambda _: True), lost(lambda row: row["stratum"] == "native")
    cross = lost(lambda row: row["stratum"] == "cross")
    out[f"{name}:overall"] = {"lost_pct": overall, "pass": overall <= 2.0,
                              "base_hits": sum(map(hit, base)), "gate_hits": sum(map(hit, gate))}
    out[f"{name}:native"] = {"lost_pct": native, "pass": native <= 2.0}
    out[f"{name}:cross"] = {"lost_pct": cross, "pass": cross <= 5.0}
    for lang in sorted({row["queryLanguage"] for row in base}):
        value = lost(lambda row, k=lang: row["queryLanguage"] == k)
        out[f"{name}:{lang}"] = {"lost_pct": value, "pass": value <= 5.0}


def check_latency(base: list[dict[str, Any]], gate: list[dict[str, Any]],
                  out: dict[str, Any]) -> None:
    for left, right in zip(base, gate, strict=True):
        size = left["size"]
        out[f"L1@{size}"] = {"base_p95": left["warm_p95_ms"], "gate_p95": right["warm_p95_ms"],
                             "pass": right["warm_p95_ms"] <= left["warm_p95_ms"] * 1.20 + 1}
        cold_base = statistics.median(left["cold_ms"])
        cold_gate = statistics.median(right["cold_ms"])
        out[f"L2@{size}"] = {"base_ms": cold_base, "gate_ms": cold_gate,
                             "pass": cold_gate - cold_base <= cold_base * 0.25}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--gate", required=True)
    parser.add_argument("--tune", action="store_true")
    for name in ("base-latency", "gate-latency", "base-large-a2", "gate-large-a2",
                 "base-large-a3", "gate-large-a3"):
        parser.add_argument(f"--{name}")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    base, gate = load(args.base), load(args.gate)
    out: dict[str, Any] = {}
    for size in SIZES:
        check_unanswerable(base, gate, size, out)
        check_retrieval(base, gate, size, out)
    if not args.tune:
        check_large("R3", load(args.base_large_a2), load(args.gate_large_a2), out)
        check_large("R4", load(args.base_large_a3), load(args.gate_large_a3), out)
        check_latency(load(args.base_latency), load(args.gate_latency), out)
    failed = sorted(key for key, value in out.items() if value.get("pass") is False)
    Path(args.out).write_text(json.dumps({"failed": failed, "pass": not failed, "checks": out},
                                         indent=1) + "\n", encoding="utf-8")
    print("PASS" if not failed else f"FAIL {failed}")


if __name__ == "__main__":
    main()
