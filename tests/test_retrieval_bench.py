"""Integrity + harness checks for the retrieval benchmark (benchmarks/retrieval).

The corpus is data, so these tests pin what the benchmark claims about it:
every query has exactly one gold note, dev/test never overlap, padding is
deterministic, and paraphrase queries really share little vocabulary with
their gold note (otherwise the "paraphrase" numbers would be a lexical test).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks" / "retrieval"))

import bench_retrieval as br
import retrieval_corpus as rc

SPLITS = ("dev", "test")
TEST_QUERY_DIGEST = "8cd2ec2b4d7000a8457310742002168c5416c1099b9deff3e9ee8cd346a0b951"


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
    assert len(qs) == len(rc.gold_notes()) * len(rc.QUERY_KINDS) * len(rc.AUTHORS)
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


def test_test_split_is_frozen():
    # Pinned before any tuning: changing which notes are test is a breaking
    # change to every reported number and must be deliberate.
    test = sorted(g.slug for g in rc.gold_notes() if g.split == "test")
    digest = hashlib.sha256(",".join(test).encode()).hexdigest()
    assert (len(test), digest) == (108, "f0ec29b013c5e55a286123a3e958a6e1cf01f75898a3417d07f3198187da7900")


def test_test_queries_are_frozen():
    # Freezes the query texts of the test split too, not just its notes.
    rows = sorted((q.author, q.gold, q.kind, q.text) for q in rc.queries()
                  if q.split == "test")
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()
    assert (len(rows), digest) == (972, TEST_QUERY_DIGEST)


_NATIVE_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3]+")
_LATIN_WORD = re.compile(r"[A-Za-z\u00c0-\u024f]{3,}")
_NUMBER = re.compile(r"(?<![A-Za-z0-9\-])\d{2,}(?![A-Za-z0-9])")


def mixed_rule_problem(note: rc.Note, query: str) -> str | None:
    """Why a code-switched query breaks the authoring rule, or None."""
    lead = note.title + " " + note.body.split("\n\n")[0]
    copied = set(_NUMBER.findall(query)) & set(_NUMBER.findall(lead))
    if copied:
        return f"restates numbers {sorted(copied)}"
    if note.lang == "en":
        latin = _LATIN_WORD.findall(query)
        if not _NATIVE_RUN.search(query) or len(latin) > 1:
            return f"needs Korean with at most one English word, has {latin}"
    elif note.lang in ("ko", "ja", "zh"):
        runs = _NATIVE_RUN.findall(query)
        if not 1 <= len(runs) <= 2 or len(_LATIN_WORD.findall(query)) < 2:
            return f"needs English plus 1-2 native words, has {runs}"
    else:
        doc = rc.content_units(note.title + " " + note.body)
        shared = {u for u in rc.content_units(query) if not u.isdigit()} & doc
        if not 1 <= len(shared) <= 3:
            return f"needs 1-2 native words (+1 name), shares {sorted(shared)}"
    return None


@pytest.mark.parametrize("author", rc.AUTHORS)
def test_mixed_queries_follow_the_code_switching_rule(author):
    gold = {g.slug: g for g in rc.gold_notes()}
    problems = {slug: mixed_rule_problem(gold[slug], kinds["mixed"])
                for slug, kinds in rc.author_queries(author).items()}
    assert {s: p for s, p in problems.items() if p} == {}


@pytest.mark.parametrize("author", rc.AUTHORS)
def test_author_sets_cover_every_gold_note(author):
    sets = rc.author_queries(author)
    assert set(sets) == {g.slug for g in rc.gold_notes()}
    for kinds in sets.values():
        assert set(kinds) == set(rc.QUERY_KINDS)
        assert all(isinstance(q, str) and q.strip() for q in kinds.values())


@pytest.mark.parametrize("author", [a for a in rc.AUTHORS if a != rc.INLINE_AUTHOR])
@pytest.mark.parametrize("lang", rc.LANGS)
def test_external_author_paraphrases_share_little_vocabulary(author, lang):
    gold = {g.slug: g for g in rc.gold_notes()}
    ratios = []
    for slug, kinds in rc.author_queries(author).items():
        g = gold[slug]
        if g.lang != lang:
            continue
        q = rc.content_units(kinds["para"])
        doc = rc.content_units(g.title + " " + g.body)
        assert q, slug
        ratios.append(len(q & doc) / len(q))
    assert max(ratios) <= 0.3
    assert sum(ratios) / len(ratios) <= 0.06


@pytest.mark.parametrize("author", rc.AUTHORS)
def test_exact_queries_are_lexical_for_every_author(author):
    gold = {g.slug: g for g in rc.gold_notes()}
    for slug, kinds in rc.author_queries(author).items():
        q = rc.content_units(kinds["exact"])
        doc = rc.content_units(gold[slug].title + " " + gold[slug].body)
        assert q, (author, slug)
        assert len(q & doc) / len(q) >= 0.6, (author, slug)


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
    assert {a for (_, a, _) in res["by_author_kind"]} == set(rc.AUTHORS)
    assert br.sidecar_bytes(vault) > 0


def test_main_end_to_end_writes_tables_and_json(tmp_path, capsys):
    out = tmp_path / "bench.json"
    br.main(["--sizes", "160", "--json", str(out)])
    printed = capsys.readouterr().out
    for header in ("Quality by language", "Quality by query kind",
                   "MRR by query author", "Footprint"):
        assert header in printed
    [row] = json.loads(out.read_text())["results"]
    assert row["size"] == 160 and row["index_bytes"] > 0
    assert row["cold_wall_ms"] >= row["cold_load_ms"] > 0
    assert row["peak_rss"] > 0
    assert set(row["by_lang"]) == {f"{s}/{lang}" for s in SPLITS for lang in rc.LANGS}
    assert set(row["by_author_kind"]) == {f"{s}/{a}/{k}" for s in SPLITS
                                          for a in rc.AUTHORS for k in rc.QUERY_KINDS}
