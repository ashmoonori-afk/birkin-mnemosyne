"""Integrity + harness checks for the retrieval benchmark (benchmarks/retrieval).

The corpus is data, so these tests pin what the benchmark claims about it:
every query has exactly one gold note, dev/test never overlap, padding is
deterministic, and paraphrase queries really share little vocabulary with
their gold note (otherwise the "paraphrase" numbers would be a lexical test).
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "retrieval"))

import bench_retrieval as br
import retrieval_corpus as rc

SPLITS = ("dev", "test")


def test_gold_corpus_shape():
    gold = rc.gold_notes()
    counts = {lang: sum(g.lang == lang for g in gold) for lang in rc.LANGS}
    assert counts == {"en": 40, "ko": 40, "ja": 20, "zh": 20, "es": 20, "de": 20}
    assert len({g.slug for g in gold}) == len(gold)
    for g in gold:
        assert set(g.queries) == set(rc.QUERY_KINDS)
        assert all(q.strip() for q in g.queries.values())


def test_split_is_disjoint_and_complete():
    gold = rc.gold_notes()
    dev = {g.slug for g in gold if g.split == "dev"}
    test = {g.slug for g in gold if g.split == "test"}
    assert dev and test and not dev & test
    assert dev | test == {g.slug for g in gold}
    # every language appears in both splits (tuned on dev, reported on test)
    for split in SPLITS:
        assert {g.lang for g in gold if g.split == split} == set(rc.LANGS)


def test_queries_cover_each_split_and_kind():
    qs = rc.queries()
    assert len(qs) == len(rc.gold_notes()) * len(rc.QUERY_KINDS)
    gold = {g.slug for g in rc.gold_notes()}
    assert all(q.gold in gold for q in qs)
    assert {(q.split, q.kind) for q in qs} == {
        (s, k) for s in SPLITS for k in rc.QUERY_KINDS}


@pytest.mark.parametrize("lang", rc.LANGS)
def test_paraphrase_queries_share_little_vocabulary(lang):
    ratios = []
    for g in rc.gold_notes():
        if g.lang != lang:
            continue
        q = rc.content_units(g.queries["para"])
        doc = rc.content_units(g.title + " " + g.body)
        assert q, g.slug
        ratios.append(len(q & doc) / len(q))
    assert max(ratios) <= 0.3
    assert sum(ratios) / len(ratios) <= 0.05


def test_exact_queries_are_lexical():
    for g in rc.gold_notes():
        q = rc.content_units(g.queries["exact"])
        doc = rc.content_units(g.title + " " + g.body)
        assert len(q & doc) / len(q) >= 0.6, g.slug


def test_content_units_fold_scripts():
    assert rc.content_units("Azafrán y FÜTTERN") == {"azafran", "futtern"}
    assert rc.content_units("豚骨スープ") == {"豚骨", "骨ス", "スー", "ープ"}
    assert rc.content_units("김") == {"김"}


def test_padding_is_deterministic_and_sized():
    n = len(rc.gold_notes()) + 300
    a = rc.corpus(n, seed=7)
    b = rc.corpus(n, seed=7)
    assert len(a) == n
    assert [(x.slug, x.body) for x in a] == [(x.slug, x.body) for x in b]
    assert len({x.slug for x in a}) == n
    assert {x.lang for x in a if x.slug.startswith("d-")} == set(rc.LANGS)
    gold_small = {x.slug: x.body for x in rc.corpus() if x.slug.startswith("g-")}
    gold_big = {x.slug: x.body for x in a if x.slug.startswith("g-")}
    assert gold_small == gold_big


def test_sibling_groups_are_valid():
    slugs = {g.slug for g in rc.gold_notes()}
    seen: set[str] = set()
    for group in rc.SIBLING_GROUPS:
        assert len(group) >= 2 and set(group) <= slugs, group
        assert not seen & set(group), group
        seen |= set(group)
        langs = [s[2:4] for s in group]
        assert len(set(langs)) == len(langs), group
    split_of = {g.slug: g.split for g in rc.gold_notes()}
    for group in rc.SIBLING_GROUPS:
        assert len({split_of[slug] for slug in group}) == 1, group
    for g in rc.gold_notes():
        for sib in g.siblings:
            assert g.slug in next(n for n in rc.gold_notes() if n.slug == sib).siblings


def test_no_undeclared_latin_script_siblings():
    gold = rc.gold_notes()
    units = {g.slug: {u for u in rc.content_units(g.title + " " + g.body)
                      if u.isascii() and len(u) >= 4 and not u.isdigit()}
             for g in gold}
    df = Counter(u for us in units.values() for u in us)
    for a, b in itertools.combinations(gold, 2):
        if a.lang == b.lang or b.slug in a.siblings:
            continue
        shared = {u for u in units[a.slug] & units[b.slug] if df[u] <= 3}
        assert len(shared) < 2, (a.slug, b.slug, shared)


def test_gold_rank_ignores_siblings():
    sibs = frozenset({"s1", "s2"})
    assert br.gold_rank(["s1", "x", "g"], "g", sibs) == 2
    assert br.gold_rank(["s1", "s2", "g"], "g", sibs) == 1
    assert br.gold_rank(["a", "b", "g"], "g", frozenset(), k=2) is None
    assert br.gold_rank(["s1", "a", "g"], "g", sibs, k=2) == 2


def test_rank_metrics():
    m = br.rank_metrics([1, 2, None, 6])
    assert m["r@1"] == pytest.approx(0.25)
    assert m["r@5"] == pytest.approx(0.5)
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0 + 1 / 6) / 4)
    ndcg = (1 + 1 / math.log2(3) + 0 + 1 / math.log2(7)) / 4
    assert m["ndcg@10"] == pytest.approx(ndcg)


def test_percentile():
    assert br.percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert br.percentile([5.0], 95) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        br.percentile([], 50)


def test_bm25_run_on_gold_corpus(tmp_path):
    vault = tmp_path / "vault"
    br.write_vault(vault, rc.corpus())
    engine = br.BM25Engine(vault)
    engine.build()
    res = br.evaluate(engine, rc.queries())
    assert set(res["by_kind"]) == {(s, k) for s in SPLITS for k in rc.QUERY_KINDS}
    assert set(res["by_lang"]) == {(s, lang) for s in SPLITS for lang in rc.LANGS}
    assert res["by_kind_lang"][("test", "exact", "en")]["r@5"] >= 0.9
    assert br.sidecar_bytes(vault) > 0


def test_main_end_to_end_writes_tables_and_json(tmp_path, capsys):
    out = tmp_path / "bench.json"
    br.main(["--sizes", "160", "--json", str(out)])
    printed = capsys.readouterr().out
    for header in ("Quality by language", "Quality by query kind", "Footprint"):
        assert header in printed
    [row] = json.loads(out.read_text())["results"]
    assert row["size"] == 160 and row["index_bytes"] > 0
    assert row["cold_wall_ms"] >= row["cold_load_ms"] > 0
    assert row["peak_rss"] > 0
    assert set(row["by_lang"]) == {f"{s}/{lang}" for s in SPLITS for lang in rc.LANGS}
