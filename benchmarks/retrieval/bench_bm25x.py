# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# How to run: .venv/bin/uv run python benchmarks/retrieval/bench_bm25x.py
# --phase dev --output /tmp/bm25x/dev.json (repository stdlib-only package).
# Scope requires this runner in one file; phase functions are independently testable.

"""Reproducible BM25 experiments; only dev selects configurations.

Run from the repository with .venv/bin/uv run python
benchmarks/retrieval/bench_bm25x.py --phase dev --output /tmp/bm25x/dev.json.
The all phase deliberately includes held-out evaluation; run it only after
the implementation and the independently selected dev configuration freeze.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import json
import math
import platform
import subprocess
import sys
import tempfile
import time
import types
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cache
from itertools import product
from pathlib import Path
from typing import Final, TypeAlias, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.retrieval import bench_retrieval as br
from benchmarks.retrieval import retrieval_corpus as rc
from birkin_mnemosyne.mnemosyne import Mnemosyne

JSON: TypeAlias = str | int | float | bool | None | Sequence["JSON"] | Mapping[str, "JSON"]
HERE: Final = Path(__file__).resolve().parent
NOW: Final = datetime(2026, 1, 1, tzinfo=timezone.utc)
INDEPENDENT: Final = ("gpt-6.1-sol", "claude-fable-5.1")
GRID: Final = ((1.25, 1.25), (1.5, 1.5), (2.0, 1.5), (2.0, 2.0))
METRICS: Final = ("r@1", "r@5", "mrr", "ndcg@10")
ORIGINAL_SHA: Final = "011cee7752e8f5323e309b38086fafec33d60420"
QUALITY_TOTALS: Final = (1160, 10160)
WRITE_TOTALS: Final = (1000, 10000)


class SelectionTrial(TypedDict):
    by_author: dict[str, dict[str, float]]


class SelectionRun(TypedDict):
    trials: list[SelectionTrial]


@dataclass(frozen=True, slots=True)
class Config:
    field_aware: bool = False
    title_weight: float = 1.5
    tag_weight: float = 1.5
    evidence_diversity: bool = False
    incremental_doclen: bool = False

    def engine(self, vault: Path) -> Mnemosyne:
        return Mnemosyne(vault, semantic=False, **asdict(self))


class CapturedSearch:
    """Mutable accumulator: evaluate once, retain complete serialized hits.

    A paired default instance is searched during that same evaluation to
    check explicit-off parity, without repeating queries on either instance.
    """

    name = "bm25x"

    def __init__(self, dex: Mnemosyne, default: Mnemosyne | None = None,
                 original: Mnemosyne | None = None):
        self.dex = dex
        self.default = default
        self.original = original
        self.hits: list[bytes] = []
        self.default_hits: list[bytes] = []
        self.original_hits: list[bytes] = []
        self.latencies: list[float] = []

    def build(self) -> None:
        self.dex.rebuild()
        if self.default is not None:
            self.default.refresh()
        if self.original is not None:
            self.original.refresh()

    def search(self, query: str, k: int) -> list[str]:
        started = time.perf_counter()
        hits = self.dex.search(query, limit=k, now=NOW)
        self.latencies.append((time.perf_counter() - started) * 1000)
        self.hits.append(serialize_hits(hits))
        if self.default is not None:
            self.default_hits.append(serialize_hits(
                self.default.search(query, limit=k, now=NOW)))
        if self.original is not None:
            self.original_hits.append(serialize_hits(
                self.original.search(query, limit=k, now=NOW)))
        return [hit["slug"] for hit in hits]


def serialize_hits(hits: Sequence[Mapping[str, JSON]]) -> bytes:
    """Exact UTF-8 hit bytes, including scores; no rounding or field dropping."""
    return json.dumps(hits, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def practice_queries() -> list[rc.Query]:
    return [q for q in rc.queries() if q.split == "dev"] + rc.dev_extra_queries()


def source_hashes() -> dict[str, str]:
    """Freeze corpus, inline/external questions and practice-only additions."""
    paths = ["retrieval_corpus.py", *rc.AUTHOR_FILES.values(),
             *rc.DEV_EXTRA_FILES.values()]
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in paths}


@dataclass(frozen=True, slots=True)
class OriginalLoader(importlib.abc.InspectLoader):
    """Compile git-sourced baseline code; stdlib executes it in the module."""

    source: str

    def get_source(self, fullname: str) -> str:
        return self.source

    def get_code(self, fullname: str) -> types.CodeType:
        return compile(self.source, f"{ORIGINAL_SHA}:mnemosyne.py", "exec")


@cache
def original_module() -> types.ModuleType:
    """Load the immutable original implementation without writing a copy."""
    source = subprocess.run(
        ["git", "-C", str(HERE.parents[1]), "show",
         f"{ORIGINAL_SHA}:birkin_mnemosyne/mnemosyne.py"],
        capture_output=True, check=True).stdout
    name = "birkin_mnemosyne._bm25x_baseline"
    module = types.ModuleType(name)
    module.__package__ = "birkin_mnemosyne"
    module.__file__ = str(HERE.parents[1] / "birkin_mnemosyne/mnemosyne.py")
    sys.modules[name] = module
    OriginalLoader(source.decode("utf-8")).exec_module(module)
    module.__dict__["source_sha256"] = hashlib.sha256(source).hexdigest()
    return module


def summary(search: CapturedSearch, queries: list[rc.Query]) -> dict[str, JSON]:
    result = br.evaluate(search, queries)
    groups: dict[tuple[str, str, str, str], list[int | None]] = {}
    authors: dict[str, list[int | None]] = {}
    latency_groups: dict[str, dict[str, list[float]]] = {
        axis: {} for axis in ("by_author", "by_author_lang", "by_author_kind",
                             "by_author_lang_kind")}
    for i, (split, lang, kind, author, rank) in enumerate(result["ranks"]):
        groups.setdefault((split, author, lang, kind), []).append(rank)
        authors.setdefault(author, []).append(rank)
        for axis, key in (
                ("by_author", author),
                ("by_author_lang", f"{split}/{author}/{lang}"),
                ("by_author_kind", f"{split}/{author}/{kind}"),
                ("by_author_lang_kind", f"{split}/{author}/{lang}/{kind}")):
            latency_groups[axis].setdefault(key, []).append(search.latencies[i])
    for key in product(sorted({q.split for q in queries}),
                       sorted({q.author for q in queries}),
                       sorted({q.lang for q in queries}),
                       sorted({q.kind for q in queries})):
        groups.setdefault(key, [])
        latency_groups["by_author_lang_kind"].setdefault("/".join(key), [])
    out: dict[str, JSON] = {
        name: {"/".join(key): value for key, value in rows.items()}
        for name, rows in result.items() if name.startswith("by_")}
    out.update(evaluation_latency_ms=result["latency_ms"],
               latency_ms={"p50": br.percentile(search.latencies, 50),
                           "p95": br.percentile(search.latencies, 95),
                           "n": len(search.latencies)},
               query_latency_ms=search.latencies, ranks=result["ranks"],
               latency_scopes={
                   "evaluation_latency_ms": "evaluation wrapper including paired parity calls",
                   "latency_ms": "actual public search only; excludes parity calls and serialization"},
               by_author={a: br.rank_metrics(r) for a, r in authors.items()},
               by_author_lang_kind={"/".join(key): br.rank_metrics(r)
                                    for key, r in groups.items()},
               queries=[{"text": q.text, "gold": q.gold, "siblings": sorted(q.siblings)}
                        for q in queries],
               serialized_hits=[h.decode("utf-8") for h in search.hits])
    out.update({
        f"latency_ms_{axis}": {
            key: {"p50": br.percentile(values, 50) if values else None,
                  "p95": br.percentile(values, 95) if values else None,
                  "n": len(values)}
            for key, values in rows.items()}
        for axis, rows in latency_groups.items()})
    return out


def select_config(runs: list[SelectionRun]) -> tuple[Config, list[int]]:
    """Require non-regression on every independent author's metrics per size.

    Rank eligible configurations by mean independent-author MRR across sizes.
    Always select an enabled field grid trial, even if every trial fails the
    gate; the report distinguishes that selection from recommending it.
    Ties prefer smaller weights. Inline author is reported, but is not treated
    as an independently authored tuning set.
    """
    eligible = []
    for i in range(1, 1 + len(GRID)):
        if all(row["trials"][i]["by_author"][a][m]
               >= row["trials"][0]["by_author"][a][m]
               for row in runs for a in INDEPENDENT for m in METRICS):
            eligible.append(i)
    best = max(eligible or list(range(1, 1 + len(GRID))), key=lambda i: sum(
        row["trials"][i]["by_author"][a]["mrr"]
        for row in runs for a in INDEPENDENT))
    return ([Config()] + [Config(True, t, g) for t, g in GRID])[best], eligible


def cleanup_receipt(path: Path) -> dict[str, JSON]:
    absent = not path.exists()
    assert absent, f"TemporaryDirectory was not removed: {path}"
    return {"path": str(path), "absent": absent}


def run_quality(sizes: list[int], dev: Config | None = None) -> dict[str, JSON]:
    """Practice grid, or exactly four held-out ablations with byte parity."""
    frozen = source_hashes()
    queries = practice_queries() if dev is None else [
        q for q in rc.queries() if q.split == "test"]
    configs = ([Config()] + [Config(True, t, g) for t, g in GRID]
               if dev is None else [
                   Config(), dev, Config(evidence_diversity=True),
                   Config(incremental_doclen=True)])
    runs = []
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix="bm25x-quality-") as tmp:
            root = Path(tmp)
            vault = root / "vault"
            br.write_vault(vault, rc.corpus(size, seed=0))
            trials = []
            captures = []
            for config in configs:
                default = Mnemosyne(vault, semantic=False) if (
                    dev is not None and not trials) else None
                original = original_module().Mnemosyne(vault, semantic=False) if (
                    dev is not None and not trials) else None
                search = CapturedSearch(config.engine(vault), default, original)
                search.build()
                row = summary(search, queries)
                row["config"] = asdict(config)
                trials.append(row)
                captures.append(search)
            row: dict[str, JSON] = {
                "total_notes": size, "distractors": size - len(rc.gold_notes()),
                "trials": trials}
            if dev is not None:
                baseline, incremental = captures[0], captures[3]
                parity = {"baseline_incremental": baseline.hits == incremental.hits,
                          "explicit_off_default": baseline.hits == baseline.default_hits,
                          "explicit_off_original": baseline.hits == baseline.original_hits,
                          "query_count": len(queries)}
                assert all(parity[k] for k in
                           ("baseline_incremental", "explicit_off_default",
                            "explicit_off_original")), parity
                row.update(names=["baseline", "field", "diversity", "incremental"],
                           byte_parity=parity,
                           original_serialized_hits=[
                               h.decode("utf-8") for h in baseline.original_hits],
                           default_serialized_hits=[
                               h.decode("utf-8") for h in baseline.default_hits])
        row["cleanup"] = cleanup_receipt(root)
        runs.append(row)
    assert source_hashes() == frozen, "Frozen sources changed during evaluation"
    report: dict[str, JSON] = {"runs": runs, "frozen_source_hashes": frozen}
    if dev is not None:
        report["original_baseline"] = {
            "git_sha": ORIGINAL_SHA, "source_sha256": original_module().__dict__["source_sha256"]}
    if dev is None:
        selected, eligible = select_config(runs)
        selected_index = 1 + GRID.index((selected.title_weight, selected.tag_weight))
        gains = [row["trials"][selected_index]["by_author"][a]["mrr"]
                 - row["trials"][0]["by_author"][a]["mrr"]
                 for row in runs for a in INDEPENDENT]
        report.update(selected_config=asdict(selected), eligible_trial_indices=eligible,
                      selection={"authors": list(INDEPENDENT), "metrics": list(METRICS),
                                 "scope": "per-author, per-size, DEV only",
                                 "objective": "mean independent-author MRR",
                                 "tie_break": "smaller title/tag weights",
                                 "passed_nonregression_gate": bool(eligible),
                                 "selected_trial_index": selected_index,
                                 "mean_mrr_gain": sum(gains) / len(gains),
                                 "fallback": "best mean grid MRR if gate fails",
                                 "recommendation": "field" if eligible and sum(gains) > 0
                                 else "baseline"})
    return report


def load_dev(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["phase"] != "dev" or data["frozen_source_hashes"] != source_hashes():
        raise RuntimeError("dev configuration has changed frozen sources or wrong phase")
    values = data["selected_config"]
    if set(values) != set(asdict(Config())) or not all(
            type(values[key]) is bool for key in
            ("field_aware", "evidence_diversity", "incremental_doclen")):
        raise RuntimeError("invalid dev config fields or flag types")
    if not all(type(values[key]) in (int, float) and math.isfinite(values[key])
               and values[key] > 0 for key in ("title_weight", "tag_weight")):
        raise RuntimeError("invalid dev weights")
    config = Config(**values)
    if config.evidence_diversity or config.incremental_doclen:
        raise RuntimeError("dev selection must only tune field weights")
    if not config.field_aware or (config.title_weight, config.tag_weight) not in GRID:
        raise RuntimeError("dev selection is outside the practice grid")
    return config


@dataclass(frozen=True, slots=True)
class EvidenceQuestion:
    slug: str
    lang: str
    text: str
    required: tuple[frozenset[str], frozenset[str]]


def synthetic_fixture() -> tuple[list[rc.Note], list[EvidenceQuestion]]:
    """Our own synthetic DEV data, unrelated to the frozen author questions.

    Each first fact has 16 near duplicates. The long second fact contains an
    extra query unit absent from every first-fact copy, so complete lexical
    match protection cannot pin all those duplicates in front of diversity.
    Twenty long unrelated notes per question make that extra unit common,
    avoiding an automatic rare-unit IDF win for the second fact at baseline.
    Required sets are equivalent sources for each of two evidence facts.
    """
    cases = (
        ("en", "cedar launch access harbor", "oxygen", "oxygen reserve is blue"),
        ("en", "maple depot transit permit", "cobalt", "cobalt storage is east"),
        ("ko", "백두 출항 항구 허가", "산소", "산소 보관함은 파란색"),
        ("ko", "한라 창고 운송 승인", "코발트", "코발트 보관함은 동쪽"),
        ("ja", "杉 森林 天気 湿度", "酸素", "酸素容器は青色"),
        ("ja", "楓 倉庫 運送 承認", "金属", "金属容器は東側"),
        ("zh", "雪松 出航 港口 许可", "氧气", "氧气容器是蓝色"),
        ("zh", "枫树 仓库 运输 批准", "钴矿", "钴矿容器在东侧"),
    )
    notes = []
    questions = []
    for i, (lang, anchors, extra, fact) in enumerate(cases):
        stem = f"synthetic-{lang}-{i}"
        first = frozenset(f"{stem}-first-{j:02d}" for j in range(17))
        second = f"{stem}-second"
        notes.extend(rc.Note(slug, anchors, f"{anchors}. reference{'.' * (j + 1)}",
                             lang, "dev")
                     for j, slug in enumerate(sorted(first)))
        notes.append(rc.Note(second, f"{stem} companion",
                             fact + ". " + "neutral background record. " * 160,
                             lang, "dev"))
        notes.extend(rc.Note(f"{stem}-noise-{j:02d}", f"Unrelated record {i}-{j}",
                             extra + ". " + "neutral background record. " * 320,
                             lang, "dev") for j in range(20))
        questions.append(EvidenceQuestion(
            stem, lang, f"{anchors} {extra}", (first, frozenset({second}))))
    return notes, questions


def evidence_metrics(hits: list[str], question: EvidenceQuestion) -> dict[str, JSON]:
    metrics = {}
    for k in (2, 5, 8):
        top = hits[:k]
        labels = [i for slug in top for i, sources in enumerate(question.required)
                  if slug in sources]
        covered = len(set(labels))
        metrics[str(k)] = {
            "coverage": covered / len(question.required),
            "all_required": covered == len(question.required),
            "duplicate_slot_rate": (len(labels) - covered) / len(top) if top else 0.0,
            "returned": len(top)}
    return metrics


def run_multi() -> dict[str, JSON]:
    notes, questions = synthetic_fixture()
    with tempfile.TemporaryDirectory(prefix="bm25x-multi-") as tmp:
        root = Path(tmp)
        vault = root / "vault"
        br.write_vault(vault, notes)
        trials = []
        for diversity in (False, True):
            config = Config(evidence_diversity=diversity)
            search = CapturedSearch(config.engine(vault))
            search.build()
            rows = []
            for q in questions:
                hits = search.search(q.text, 8)
                if not diversity:
                    assert len(hits) == 8 and set(hits) <= q.required[0], (
                        "Synthetic baseline does not saturate with first-fact copies",
                        q.slug, hits)
                rows.append({"id": q.slug, "lang": q.lang, "query": q.text,
                             "required_sources": [sorted(s) for s in q.required],
                             "hits": hits, "metrics": evidence_metrics(hits, q)})
            aggregates = {}
            for lang in ("all", "en", "ko", "ja", "zh"):
                selected = [r for r in rows if lang == "all" or r["lang"] == lang]
                aggregates[lang] = {
                    str(k): {name: sum(r["metrics"][str(k)][name] for r in selected)
                             / len(selected) for name in
                             ("coverage", "all_required", "duplicate_slot_rate")}
                    for k in (2, 5, 8)}
            trials.append({"config": asdict(config), "queries": rows,
                           "aggregates": aggregates,
                           "serialized_hits": [h.decode("utf-8") for h in search.hits]})
    return {"fixture": "own-synthetic-dev", "total_notes": len(notes),
            "independent_author_attribution": "N/A: our own synthetic DEV fixture",
            "query_count": len(questions), "trials": trials,
            "cleanup": cleanup_receipt(root)}


def timing_summary(samples: list[float]) -> dict[str, JSON]:
    return {"median": br.percentile(samples, 50), "p95": br.percentile(samples, 95),
            "n": len(samples), "samples": samples}


def length_state(dex: Mnemosyne) -> dict[str, JSON]:
    notes = dex._notes
    assert notes is not None
    count = len(notes)
    total = sum(entry["doclen"] for entry in notes.values())
    assert (dex._total_doclen, dex._doc_count) == (total, count)
    assert dex._avgdl == (total / count if count else 0.0)
    return {"total_doclen": total, "doc_count": count, "avgdl": dex._avgdl}


def run_writes(sizes: list[int], repeats: int) -> dict[str, JSON]:
    """Time public insert/edit/delete updates including whole compressed saves.

    Full-write timing includes file IO and the index update; nested index
    timing isolates parse/accounting/persistence. Delete uses public refresh;
    insert/edit use public note_written. Real cache-save and arithmetic
    costs are separate experiments, never patched/no-save latency paths.
    """
    runs = []
    for size in sizes:
        with tempfile.TemporaryDirectory(prefix="bm25x-writes-") as tmp:
            root = Path(tmp)
            notes = [rc.Note(f"write-{i:05d}", f"Write record {i}",
                             "writeprobe cedar fixed baseline record", "en")
                     for i in range(size)]
            engines = []
            for enabled in (False, True):
                vault = root / ("incremental" if enabled else "baseline")
                br.write_vault(vault, notes)
                dex = Config(incremental_doclen=enabled).engine(vault)
                dex.rebuild()
                engines.append(dex)
            samples = [{op: [] for op in ("insert", "edit", "delete")}
                       for _ in engines]
            full_samples = [{op: [] for op in ("insert", "edit", "delete")}
                            for _ in engines]
            receipts = []
            for cycle in range(repeats):
                for op in ("insert", "edit", "delete"):
                    states = []
                    hits = []
                    for i, dex in enumerate(engines):
                        path = dex.vault / "write-probe.md"
                        full_started = time.perf_counter()
                        match op:
                            case "insert":
                                br.write_vault(dex.vault, [rc.Note(
                                    path.stem, "Write probe",
                                    "writeprobe cedar inserted fixed record", "en")])
                            case "edit":
                                br.write_vault(dex.vault, [rc.Note(
                                    path.stem, "Write probe",
                                    "writeprobe cedar edited fixed record extra terms", "en")])
                            case "delete":
                                path.unlink()
                        started = time.perf_counter()
                        match op:
                            case "insert" | "edit":
                                dex.note_written(path)
                            case "delete":
                                dex.refresh()
                        finished = time.perf_counter()
                        samples[i][op].append((finished - started) * 1000)
                        full_samples[i][op].append((finished - full_started) * 1000)
                        states.append(length_state(dex))
                        hits.append(serialize_hits(dex.search("writeprobe cedar", now=NOW)))
                        assert dex._index_path.is_file(), "Full save did not produce cache"
                        persisted = json.loads(zlib.decompress(
                            dex._index_path.read_bytes()))["notes"]
                        assert persisted == dex._notes, "Whole compressed save is stale"
                    assert states[0] == states[1], (op, states)
                    assert hits[0] == hits[1], (op, hits)
                    receipts.append({"cycle": cycle, "operation": op,
                                     "state": states[0], "score_byte_parity": True})
            arithmetic = []
            cache_saves = []
            reloads = []
            for i, dex in enumerate(engines):
                recompute = []
                incremental = []
                save_samples = []
                calls_per_sample = 100
                for _ in range(repeats):
                    started = time.perf_counter()
                    for _ in range(calls_per_sample):
                        dex._recompute_avgdl()
                    recompute.append((time.perf_counter() - started) * 1000
                                     / calls_per_sample)
                    started = time.perf_counter()
                    for _ in range(calls_per_sample):
                        dex._adjust_doclen(0, 0, 0)
                    incremental.append((time.perf_counter() - started) * 1000
                                       / calls_per_sample)
                    started = time.perf_counter()
                    dex._save_index()
                    save_samples.append((time.perf_counter() - started) * 1000)
                arithmetic.append({"recompute_avgdl_ms": timing_summary(recompute),
                                   "adjust_doclen_ms": timing_summary(incremental),
                                   "calls_per_sample": calls_per_sample,
                                   "reported_unit": "ms per real accounting call"})
                cache_saves.append(timing_summary(save_samples))
                reloaded = Config(incremental_doclen=(i == 1)).engine(dex.vault)
                reloaded.refresh()
                assert length_state(dex) == length_state(reloaded)
                assert serialize_hits(dex.search("writeprobe cedar", now=NOW)) == (
                    serialize_hits(reloaded.search("writeprobe cedar", now=NOW)))
                reloads.append({"state": length_state(reloaded),
                                "score_byte_parity": True,
                                "compressed_cache_bytes": dex._index_path.stat().st_size})
            row: dict[str, JSON] = {"total_notes": size, "repeats": repeats,
                   "index_update_ms": {
                       name: {op: timing_summary(values) for op, values in group.items()}
                       for name, group in zip(("baseline", "incremental"), samples)},
                   "full_write_ms": {
                       name: {op: timing_summary(values) for op, values in group.items()}
                       for name, group in zip(("baseline", "incremental"), full_samples)},
                   "cache_save_ms": dict(zip(("baseline", "incremental"), cache_saves)),
                   "arithmetic_only": arithmetic, "operation_parity": receipts,
                   "reload": reloads}
        row["cleanup"] = cleanup_receipt(root)
        runs.append(row)
    return {"runs": runs, "full_compressed_save_enabled": True,
            "independent_author_attribution": "N/A: fixed write workload, no author queries",
            "update_api": {"insert": "note_written", "edit": "note_written",
                           "delete": "refresh"},
            "timing_scopes": {
                "full_write_ms": "file write/unlink through note_written/refresh with save",
                "index_update_ms": "note_written/refresh including whole compressed save",
                "cache_save_ms": "real unpatched _save_index after operation workloads",
                "arithmetic_only": "real _recompute_avgdl versus neutral _adjust_doclen(0,0,0)"}}


def save_report(path: Path, report: Mapping[str, JSON]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
                    + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    phases = ("dev", "test", "multi", "writes", "all")
    parser.add_argument("phase", nargs="?", choices=phases)
    parser.add_argument("--phase", dest="phase_option", choices=phases)
    parser.add_argument("--sizes", nargs="+", type=int,
                        help="explicit TOTAL NOTES override; quality defaults 1160/10160 "
                             "(1000/10000 distractors); writes defaults 1000/10000 notes")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--dev-config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.phase and args.phase_option and args.phase != args.phase_option:
        parser.error("positional phase and --phase must agree")
    phase = args.phase_option or args.phase
    if phase is None:
        parser.error("--phase (or positional phase) is required")
    quality_sizes: list[int] = args.sizes or list(QUALITY_TOTALS)
    write_sizes: list[int] = args.sizes or list(WRITE_TOTALS)
    if (args.repeats < 2 or min(quality_sizes) < 160
            or len(set(quality_sizes)) != len(quality_sizes)):
        parser.error("sizes must be >=160 total notes; repeats must be >=2")
    metadata: dict[str, JSON] = {"phase": phase, "schema_version": 1,
                "language_axis": "gold-note language, NOT query language",
                "size_axis": {
                    "quality_default_total_notes": list(QUALITY_TOTALS),
                    "quality_default_distractors": [1000, 10000],
                    "writes_default_total_notes": list(WRITE_TOTALS),
                    "quality_requested_total_notes": quality_sizes,
                    "writes_requested_total_notes": write_sizes,
                    "sizes_override_unit": "TOTAL NOTES"},
                "seed": 0, "fixed_now": NOW.isoformat(),
                "python": sys.version, "platform": platform.platform(),
                "production_source_sha256": hashlib.sha256(
                    (HERE.parents[1] / "birkin_mnemosyne/mnemosyne.py").read_bytes()
                ).hexdigest(),
                "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    match phase:
        case "dev":
            report = run_quality(quality_sizes)
        case "test":
            dev_path = args.dev_config or args.output.with_name("dev.json")
            report = run_quality(quality_sizes, load_dev(dev_path))
            report["dev_config_sha256"] = hashlib.sha256(dev_path.read_bytes()).hexdigest()
        case "multi":
            report = run_multi()
        case "writes":
            report = run_writes(write_sizes, args.repeats)
        case "all":
            dev_path = args.dev_config or args.output.with_name("dev.json")
            if dev_path.resolve() == args.output.resolve():
                parser.error("all output must differ from the frozen dev config")
            practice = run_quality(quality_sizes)
            save_report(dev_path, {**metadata, **practice, "phase": "dev"})
            report = {"dev": practice,
                      "test": run_quality(quality_sizes, load_dev(dev_path)),
                      "multi": run_multi(),
                      "writes": run_writes(write_sizes, args.repeats)}
        case unknown:
            parser.error(f"unknown phase {unknown}")
    save_report(args.output, {**metadata, **report})


if __name__ == "__main__":
    main()
