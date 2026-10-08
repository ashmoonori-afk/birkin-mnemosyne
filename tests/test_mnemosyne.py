"""Mnemosyne — the mechanical memory engine (index / BM25 / dynamics / zones).

Pure functions get exact-value tests; the engine is exercised against a real
temp vault (isolated temp vault via conftest). No LLM anywhere.
"""

from __future__ import annotations
import config

import json
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne
from birkin_mnemosyne import VaultMemory


def _vault() -> Path:
    return config.vault_dir(config.load_config())


def _mem() -> VaultMemory:
    return VaultMemory(config.load_config())


def _engine() -> mnemosyne.Mnemosyne:
    eng = mnemosyne.Mnemosyne(_vault())
    eng.refresh()
    return eng


NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


# ---------------- tokenize -------------------------------------------------

def test_tokenize_ascii_words_lowercased():
    assert mnemosyne.tokenize("Hello World2") == ["hello", "world2"]


def test_tokenize_hangul_runs_and_bigrams():
    toks = mnemosyne.tokenize("메모리 시스템")
    assert "메모리" in toks and "시스템" in toks
    assert "메모" in toks and "모리" in toks          # bigrams of run 1
    assert "시스" in toks and "스템" in toks          # bigrams of run 2


def test_tokenize_mixed_korean_ascii():
    toks = mnemosyne.tokenize("AI에이전트")
    assert "ai" in toks and "에이전트" in toks and "이전" in toks


def test_tokenize_japanese_han_and_kana():
    toks = mnemosyne.tokenize("豚骨スープ")
    assert {"豚", "骨", "豚骨", "骨ス", "スー", "ープ"} <= set(toks)


def test_tokenize_cjk_iteration_mark_and_middle_dot():
    assert "人々" in mnemosyne.tokenize("人々")
    assert not any("・" in t for t in mnemosyne.tokenize("トム・クルーズ"))


def test_single_language_japanese_query_is_plain_bm25():
    postings = {"車検": {"a": 1}, "の期": {"a": 1, "b": 1}}
    doclens = {"a": 2, "b": 2}
    scores = mnemosyne.bm25_scores(["車検", "の期"], postings, doclens, 2.0, 2)
    import math
    idf1 = math.log(1 + (2 - 1 + 0.5) / 1.5)
    idf2 = math.log(1 + (2 - 2 + 0.5) / 2.5)
    assert scores["a"] == pytest.approx(idf1 + idf2)


def test_digits_do_not_count_as_a_script():
    postings = {"2024": {"a": 1}, "계획": {"a": 1}}
    scores = mnemosyne.bm25_scores(["2024", "계획"], postings, {"a": 2}, 2.0, 1)
    plain = mnemosyne.bm25_scores(["2024"], postings, {"a": 2}, 2.0, 1)["a"] + \
        mnemosyne.bm25_scores(["계획"], postings, {"a": 2}, 2.0, 1)["a"]
    assert scores["a"] == pytest.approx(plain)


def test_tokenize_folds_vietnamese():
    assert mnemosyne.tokenize("Tiếng Việt") == ["tieng", "viet"]


def test_truncation_stem_joins_inflections():
    note = set(mnemosyne.tokenize("Der Vertrag verlängert sich"))
    query = set(mnemosyne.tokenize("Verlängerung"))
    assert "verla~" in note & query
    assert "vertr~" in note and "der" in note and "sich" in note
    assert not any(t.endswith("~") for t in mnemosyne.tokenize("cat 2024 hello"))


def test_tokenize_supplementary_han():
    assert {"𠮷", "𠮷野", "野"} <= set(mnemosyne.tokenize("𠮷野家"))


def test_tokenize_chinese_unigrams_and_bigrams():
    toks = mnemosyne.tokenize("搬家准备")
    assert {"搬", "家", "搬家", "家准", "准备"} <= set(toks)


def test_tokenize_folds_latin_accents_and_case():
    assert mnemosyne.tokenize("Azafrán FÜTTERN Straße") == [
        "azafran", "azafr~", "futtern", "futte~", "strasse", "stras~"]


def test_tokenize_nfkc_fullwidth_and_halfwidth():
    assert mnemosyne.tokenize("ＡＰＩ") == ["api"]
    assert "カタ" in mnemosyne.tokenize("ｶﾀｶﾅ")


def test_tokenize_folds_only_latin_letters():
    assert mnemosyne.tokenize("Йогурт café") == ["йогурт", "йогур~", "cafe"]


def test_bm25_rewards_matching_every_query_script():
    # A matches both Latin terms (one of them 3x); B matches one Latin and the
    # Japanese term. Plain BM25 ranks A first; covering both scripts of the
    # code-switched query must put B first.
    postings = {"moving": {"A": 1, "B": 1}, "checklist": {"A": 3}, "手続": {"B": 1}}
    doclens = {"A": 4, "B": 4, "C": 4}
    scores = mnemosyne.bm25_scores(["moving", "checklist", "手続"], postings,
                                   doclens, avgdl=4.0, n_docs=3)
    assert scores["B"] > scores["A"]


def test_doc_length_ignores_cjk_unigrams():
    terms = {t: 1 for t in mnemosyne.tokenize("豚骨スープ car")}
    assert mnemosyne._doc_length(terms) == 5          # 4 bigrams + "car"


def test_search_finds_japanese_and_chinese_notes(tmp_path):
    (tmp_path / "ja.md").write_text("---\ntitle: 車検\n---\n\n車検の期限は来年二月。", encoding="utf-8")
    (tmp_path / "zh.md").write_text("---\ntitle: 搬家\n---\n\n下个月从上海搬到杭州。", encoding="utf-8")
    (tmp_path / "en.md").write_text("---\ntitle: car\n---\n\ncar inspection", encoding="utf-8")
    dex = mnemosyne.Mnemosyne(tmp_path)
    assert dex.search("車検 期限")[0]["slug"] == "ja"
    assert dex.search("搬到杭州")[0]["slug"] == "zh"


def test_index_from_older_tokenizer_is_rebuilt(tmp_path):
    note = tmp_path / "ja.md"
    note.write_text("---\ntitle: 車検\n---\n\n車検の期限", encoding="utf-8")
    st = note.stat()
    # A v1 cache whose fingerprint matches the file: only the version check
    # can force the re-parse that makes the Japanese text searchable.
    stale = {"version": mnemosyne.INDEX_VERSION - 1, "notes": {"ja": {
        "title": "車検", "rel": "ja.md", "zone": "", "type": "topic",
        "tags": [], "links": [], "created": "", "updated": "",
        "confidence": 0.5, "polarity": "positive", "expires_at": None,
        "summary": "", "mtime": st.st_mtime, "size": st.st_size,
        "doclen": 0, "terms": {}}}}
    (tmp_path / mnemosyne.INDEX_FILE).write_bytes(zlib.compress(json.dumps(stale).encode()))
    dex = mnemosyne.Mnemosyne(tmp_path)
    assert [h["slug"] for h in dex.search("車検")] == ["ja"]


# ---------------- BM25 ------------------------------------------------------

def test_bm25_length_normalization_hand_computed():
    import math
    postings = {"cat": {"d1": 2, "d2": 1}, "dog": {"d1": 1}}
    doclens = {"d1": 3, "d2": 1}
    scores = mnemosyne.bm25_scores(["cat"], postings, doclens,
                                   avgdl=2.0, n_docs=2)
    idf = math.log(1 + 0.5 / 2.5)
    assert scores["d1"] == pytest.approx(idf * 2 * 2.5 / 4.0625)
    assert scores["d2"] == pytest.approx(idf * 1 * 2.5 / 1.9375)
    assert scores["d2"] > scores["d1"]   # shorter doc wins at equal tf-ish


def test_bm25_rare_term_outranks_common_term():
    # ported from oh-my-openagent recall (PR #9209): idf, not position, decides
    postings = {"deploy": {"a": 1, "b": 1, "c": 1}, "kessler": {"b": 1}}
    doclens = {"a": 2, "b": 2, "c": 2}
    scores = mnemosyne.bm25_scores(["deploy", "kessler"], postings, doclens, 2.0, 3)
    assert max(scores, key=scores.get) == "b"
    assert scores["a"] == pytest.approx(scores["c"])
    assert scores["a"] < scores["b"]


def test_bm25_unknown_terms_yield_empty():
    assert mnemosyne.bm25_scores(["zzz"], {}, {}, 1.0, 0) == {}


# ---------------- dynamics (pure) ------------------------------------------

def test_effective_strength_decays_on_ebbinghaus_curve():
    import math
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=7)).isoformat()}
    eff = mnemosyne.effective_strength(dyn, NOW)
    assert eff == pytest.approx(math.exp(-1.0))


def test_effective_strength_never_below_floor():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=1000)).isoformat()}
    assert mnemosyne.effective_strength(dyn, NOW) == mnemosyne.EFF_FLOOR


def test_effective_strength_fresh_equals_strength():
    dyn = {"strength": 2.0, "stability": 7.0, "access_count": 1,
           "last_access": NOW.isoformat()}
    assert mnemosyne.effective_strength(dyn, NOW) == pytest.approx(2.0)


def test_potentiate_returns_new_dict_and_bumps_strength():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(minutes=5)).isoformat()}
    out = mnemosyne.potentiate(dyn, NOW)
    assert out is not dyn and dyn["strength"] == 1.0     # immutability
    assert out["strength"] == pytest.approx(1.25)
    assert out["access_count"] == 1
    assert out["last_access"] == NOW.isoformat()


def test_potentiate_spacing_gate_blocks_stability_growth_under_1h():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(minutes=30)).isoformat()}
    assert mnemosyne.potentiate(dyn, NOW)["stability"] == pytest.approx(7.0)


def test_potentiate_spaced_access_multiplies_stability():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(hours=2)).isoformat()}
    assert mnemosyne.potentiate(dyn, NOW)["stability"] == pytest.approx(10.5)


def test_potentiate_caps():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(hours=2)).isoformat()}
    for i in range(40):
        dyn = mnemosyne.potentiate(
            dyn, NOW + timedelta(hours=2 * (i + 1)))
    assert dyn["strength"] == mnemosyne.STRENGTH_CAP
    assert dyn["stability"] <= mnemosyne.STABILITY_CAP


def test_zone_ema_daily_decay():
    ema = mnemosyne.decayed_ema(10.0, "2026-06-30", date(2026, 7, 2))
    assert ema == pytest.approx(10.0 * 0.9 ** 2)


# ---------------- index build / refresh ------------------------------------

def test_index_builds_from_vault_and_maps_zones():
    m = _mem()
    m.write_note("Proj X", "the flagship project", note_type="project")
    m.write_note("Fact Y", "a durable fact", note_type="fact")
    eng = _engine()
    px = eng.note_meta("proj-x")
    assert px is not None and px["zone"] == "projects"
    assert eng.note_meta("fact-y")["zone"] == "knowledge"


def test_incremental_refresh_reparses_only_changed_files(monkeypatch):
    m = _mem()
    m.write_note("A", "alpha body")
    m.write_note("B", "beta body")
    m.write_note("C", "gamma body")
    eng = _engine()                      # full build done

    parsed: list[str] = []
    orig = mnemosyne._note_entry

    def counting(path, rel):
        parsed.append(rel)
        return orig(path, rel)

    monkeypatch.setattr(mnemosyne, "_note_entry", counting)
    # grow one file so (mtime, size) fingerprint definitely changes
    p = _vault() / eng.resolve_rel("b")
    p.write_text(p.read_text(encoding="utf-8") + "\nmore beta text",
                 encoding="utf-8")
    eng.refresh()
    assert parsed and all("b.md" in r for r in parsed)
    assert len(parsed) == 1


def test_corrupted_index_file_triggers_clean_rebuild():
    m = _mem()
    m.write_note("Solid", "still here")
    (_vault() / mnemosyne.INDEX_FILE).write_text("{not json",
                                                 encoding="utf-8")
    eng = _engine()
    assert eng.note_meta("solid") is not None


def test_deleted_note_is_pruned_on_refresh():
    m = _mem()
    m.write_note("Ghost", "soon gone")
    eng = _engine()
    (_vault() / eng.resolve_rel("ghost")).unlink()
    eng.refresh()
    assert eng.note_meta("ghost") is None


def test_search_scans_the_vault_at_most_once_per_ttl(monkeypatch):
    m = _mem()
    m.write_note("Alpha", "alpha body")
    clock = [100.0]
    monkeypatch.setattr(mnemosyne, "_clock", lambda: clock[0])
    eng = _engine()                      # scanned at t=100
    scans: list[float] = []
    orig = eng._scan

    def counting():
        scans.append(clock[0])
        return orig()

    monkeypatch.setattr(eng, "_scan", counting)
    assert eng.search("alpha", now=NOW)
    clock[0] += mnemosyne.SCAN_TTL / 2
    assert eng.search("alpha", now=NOW)
    assert scans == []                   # inside the TTL: no stat pass
    clock[0] += mnemosyne.SCAN_TTL / 2
    assert eng.search("alpha", now=NOW)
    assert scans == [100.0 + mnemosyne.SCAN_TTL]


def test_outside_edit_shows_after_ttl_or_refresh_and_own_write_at_once(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(mnemosyne, "_clock", lambda: clock[0])
    m = _mem()
    m.write_note("Alpha", "alpha body")  # the write path scans at t=100
    eng = m.dex
    assert eng.search("alpha", now=NOW)

    (_vault() / "outside.md").write_text("zeppelin hangar", encoding="utf-8")
    assert eng.search("zeppelin", now=NOW) == []
    clock[0] += mnemosyne.SCAN_TTL
    assert [h["slug"] for h in eng.search("zeppelin", now=NOW)] == ["outside"]

    (_vault() / "second.md").write_text("walrus tusk", encoding="utf-8")
    assert eng.search("walrus", now=NOW) == []
    eng.refresh()                        # the explicit scan does not wait
    assert [h["slug"] for h in eng.search("walrus", now=NOW)] == ["second"]

    m.write_note("Own", "quokka habitat")
    assert [h["slug"] for h in eng.search("quokka", now=NOW)] == ["own"]


# ---------------- search ----------------------------------------------------

def test_search_relevance_dominates():
    m = _mem()
    m.write_note("Pizza", "recipe for pizza dough and toppings")
    m.write_note("Taxes", "annual tax filing checklist")
    eng = _engine()
    hits = eng.search("pizza dough", now=NOW)
    assert hits and hits[0]["slug"] == "pizza"


def test_search_warm_note_outranks_cold_at_equal_relevance():
    m = _mem()
    m.write_note("Alpha", "python tips collected")
    m.write_note("Beta", "python tips collected")
    eng = _engine()
    for i in range(3):
        eng.record_access("beta", now=NOW + timedelta(hours=2 * i))
    hits = eng.search("python tips", now=NOW + timedelta(hours=6))
    assert [h["slug"] for h in hits[:2]] == ["beta", "alpha"]


def test_search_zone_filter_and_archive_exclusion():
    m = _mem()
    m.write_note("Keep", "shared keyword banana", note_type="project")
    m.write_note("Gone", "shared keyword banana", note_type="fact")
    eng = _engine()
    eng.rezone("gone", mnemosyne.ARCHIVE_ZONE)
    hits = eng.search("banana", now=NOW)
    assert [h["slug"] for h in hits] == ["keep"]
    hits_all = eng.search("banana", now=NOW, include_archive=True)
    assert {h["slug"] for h in hits_all} == {"keep", "gone"}
    scoped = eng.search("banana", now=NOW, zone="projects")
    assert [h["slug"] for h in scoped] == ["keep"]


def test_search_korean_query_roundtrip():
    m = _mem()
    m.write_note("메모리 설계", "구역 기반 저장과 인덱스")
    eng = _engine()
    assert eng.search("구역", now=NOW)[0]["slug"] == _slug_kr()


def _slug_kr() -> str:
    from birkin_mnemosyne.mnemosyne import slug
    return slug("메모리 설계")


# ---------------- search-time query expansion -------------------------------

def test_expansions_find_a_note_the_query_words_miss():
    m = _mem()
    m.write_note("Sourdough", "feed the starter twice a day")
    m.write_note("Taxes", "annual filing checklist")
    eng = _engine()
    assert eng.search("bread culture upkeep", now=NOW) == []
    hits = eng.search("bread culture upkeep", now=NOW,
                      expansions={"synonyms": ["starter", "levain"]})
    assert [h["slug"] for h in hits] == ["sourdough"]


def test_expansion_terms_rank_below_the_query_words_and_by_tier():
    m = _mem()
    m.write_note("Alpha", "quokka habitat notes")
    m.write_note("Gamma", "wombat habitat notes")
    m.write_note("Omega", "numbat habitat notes")
    eng = _engine()
    # the expansion matches are the warmer notes: only the grading keeps the
    # literal match first and the closer tier second
    for i in range(3):
        for s in ("gamma", "omega"):
            eng.record_access(s, now=NOW + timedelta(hours=2 * i))
    hits = eng.search("quokka", now=NOW + timedelta(hours=6),
                      expansions={"related": ["numbat"], "synonyms": ["wombat"]})
    assert [h["slug"] for h in hits] == ["alpha", "gamma", "omega"]


def test_a_note_holding_every_query_word_stays_ahead_of_expansion_matches():
    m = _mem()
    m.write_note("Alpha", "quokka habitat notes")
    m.write_note("Gamma", "wombat burrow marsupial nocturnal grazing pouch")
    eng = _engine()
    for i in range(3):
        eng.record_access("gamma", now=NOW + timedelta(hours=2 * i))
    later = NOW + timedelta(hours=6)
    hits = eng.search("quokka", now=later, expansions={"synonyms": [
        "wombat", "burrow", "marsupial", "nocturnal", "grazing", "pouch"]})
    assert [h["slug"] for h in hits] == ["alpha", "gamma"]
    assert hits[0]["score"] == eng.search("quokka", now=later)[0]["score"]


def test_expansion_weights_skip_query_words_and_keep_the_highest_tier():
    got = mnemosyne.expansion_weights(
        {"related": ["pizza dough"], "synonyms": "dough", "note_line": None},
        mnemosyne.tokenize("pizza"))
    assert got == {"dough": mnemosyne.EXPANSION_WEIGHTS["synonyms"]}


def test_search_without_expansions_ranks_as_before():
    m = _mem()
    for i in range(6):
        m.write_note(f"Note {i}", f"python tips number {i} " + "python " * i)
    eng = _engine()
    plain = eng.search("python tips", now=NOW)
    assert eng.search("python tips", now=NOW, expansions={}) == plain
    assert eng.search("python tips", now=NOW,
                      expansions={"synonyms": None, "related": []}) == plain


@pytest.mark.parametrize("bad", [
    {"nicknames": ["x"]}, {"synonyms": [1, 2]}, {"synonyms": {"a": "b"}},
    {"related": 7}, {"note_line": b"bytes"},
    {"synonyms": (w for w in ["wombat"])}])
def test_malformed_expansions_are_refused(bad):
    m = _mem()
    m.write_note("Alpha", "quokka habitat notes")
    with pytest.raises(ValueError):
        _engine().search("quokka", now=NOW, expansions=bad)


def test_snippet_shows_the_passage_an_expansion_matched():
    m = _mem()
    m.write_note("Sourdough", "weekend baking log. " * 30
                 + "feed the starter twice a day")
    hits = m.search("bread culture upkeep",
                    expansions={"synonyms": ["starter"]})
    assert [h["title"] for h in hits] == ["sourdough"]
    assert "starter" in hits[0]["snippet"]


@pytest.mark.parametrize("where", ["zone", "archive", "expired"])
def test_full_matches_this_search_cannot_return_take_no_candidate_slot(where):
    m = _mem()
    # many short unrelated notes keep the average note short, so the long
    # full matches score below the short partial match, as in a real vault
    for i in range(100):
        m.write_note(f"Misc {i}", "unrelated", zone="misc")
    filler = " ".join(f"pad{i}" for i in range(120))
    for i in range(mnemosyne.CAND):
        m.write_note(f"Far {i}", f"quokka habitat {filler}", zone="other",
                     ttl_days=1 if where == "expired" else None)
    m.write_note("Active", "quokka quokka quokka", zone="knowledge")
    eng = _engine()
    kw: dict = {"now": NOW}
    if where == "zone":
        kw["zone"] = "knowledge"
    elif where == "archive":
        for i in range(mnemosyne.CAND):
            eng.rezone(f"far-{i}", mnemosyne.ARCHIVE_ZONE)
    else:
        for s in [s for s in eng.entries() if s.startswith("far-")]:
            eng._notes[s] = {**eng._notes[s], "expires_at": "2000-01-01"}
    plain = eng.search("quokka habitat", **kw)
    assert [h["slug"] for h in plain] == ["active"]
    assert eng.search("quokka habitat", expansions={"synonyms": ["unmatched"]},
                      **kw) == plain


def test_semantic_mode_keeps_a_full_match_first_with_its_own_score():
    m = _mem()
    m.write_note("Alpha", "quokka " + " ".join(f"pad{i}" for i in range(80)))
    for i in range(mnemosyne.FUSE_DEPTH + 1):
        m.write_note(f"Wide {i}", "wombat burrow")
    eng = _engine()
    eng._semantic_ranking = lambda query: [(f"wide-{i}", 1.0 - i / 1000)
                                           for i in range(40)]
    plain = eng.search("quokka", now=NOW)
    wide = eng.search("quokka", now=NOW,
                      expansions={"synonyms": ["wombat", "burrow"]})
    assert plain[0]["slug"] == wide[0]["slug"] == "alpha"
    assert wide[0]["score"] == plain[0]["score"]
    assert {h["slug"] for h in wide[1:]} <= {f"wide-{i}" for i in range(101)}


def test_a_one_shot_iterator_is_refused_by_both_search_entry_points():
    m = _mem()
    m.write_note("Gamma", "wombat burrow")
    for search in (m.search, m.dex.search):
        with pytest.raises(ValueError):
            search("quokka", expansions={"synonyms": (w for w in ["wombat"])})
    assert [h["title"] for h in m.search(
        "quokka", expansions={"synonyms": ("wombat",)})] == ["gamma"]


# ---------------- related / stale / rezone ----------------------------------

def test_related_excludes_self_and_existing_links():
    m = _mem()
    m.write_note("Hub", "kubernetes cluster operations",
                 links=["Spoke One"])
    m.write_note("Spoke One", "kubernetes cluster notes")
    m.write_note("Spoke Two", "kubernetes cluster deep dive")
    eng = _engine()
    rel = eng.related("hub")
    slugs = [h["slug"] for h in rel]
    assert "spoke-two" in slugs
    assert "hub" not in slugs and "spoke-one" not in slugs


def test_stale_lists_old_low_strength_notes_but_not_identity():
    m = _mem()
    m.write_note("Old Project", "dusty", note_type="project")
    m.write_note("Me", "the user", note_type="preference")   # → identity
    eng = _engine()
    old = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=200)).isoformat()}
    eng.set_dynamics("old-project", old)
    eng.set_dynamics("me", dict(old))
    stale = eng.stale(now=NOW)
    slugs = [s["slug"] for s in stale]
    assert "old-project" in slugs and "me" not in slugs


def test_rezone_moves_file_and_updates_index():
    m = _mem()
    m.write_note("Mover", "goes places", note_type="fact")
    eng = _engine()
    eng.rezone("mover", "finance")
    assert eng.note_meta("mover")["zone"] == "finance"
    assert (_vault() / "finance" / "mover.md").is_file()
    assert not (_vault() / "knowledge" / "mover.md").exists()


def test_rezone_rejects_bad_zone_names():
    m = _mem()
    m.write_note("Fixed", "immovable")
    eng = _engine()
    with pytest.raises(ValueError):
        eng.rezone("fixed", "../escape")
    with pytest.raises(ValueError):
        eng.rezone("no-such-note", "finance")


def test_rezone_refuses_to_overwrite_existing_destination():
    import os
    m = _mem()
    m.write_note("Foo", "the indexed copy", note_type="fact")
    vault = _vault()
    src = vault / "knowledge" / "foo.md"
    hidden = vault / "projects" / "foo.md"
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text("---\ntitle: foo\n---\nolder hand-made copy\n",
                      encoding="utf-8")
    old = src.stat().st_mtime - 1000
    os.utime(hidden, (old, old))
    src_bytes, hidden_bytes = src.read_bytes(), hidden.read_bytes()
    eng = _engine()
    assert eng.note_meta("foo")["rel"] == "knowledge/foo.md"
    with pytest.raises(ValueError) as exc:
        eng.rezone("foo", "projects")
    msg = str(exc.value)
    assert "knowledge/foo.md" in msg and "projects/foo.md" in msg
    assert src.read_bytes() == src_bytes
    assert hidden.read_bytes() == hidden_bytes
    assert eng.note_meta("foo")["rel"] == "knowledge/foo.md"


def test_entries_returns_snapshot_not_live_dict():
    """Consumers iterate entries() while other threads mutate the index —
    it must be a copy (review finding: RuntimeError under concurrency)."""
    m = _mem()
    m.write_note("Snap", "frozen view")
    eng = _engine()
    snap = eng.entries()
    snap.clear()                       # vandalize the copy
    assert eng.note_meta("snap") is not None


def test_zone_priority_reflects_access_concentration():
    m = _mem()
    m.write_note("P1", "project work", note_type="project")
    m.write_note("K1", "fact work", note_type="fact")
    eng = _engine()
    for i in range(4):
        eng.record_access("p1", now=NOW + timedelta(hours=2 * i))
    pri = eng.zone_priorities(today=NOW.date())
    assert pri["projects"] == pytest.approx(1.0)
    assert pri.get("knowledge", 0.0) < 1.0


# ---------------- dynamics persistence (M1-2 / M1-3) -------------------------

def test_two_engines_on_one_vault_merge_dynamics():
    """Two engines stand in for two processes: each holds its own in-memory
    copy, so a whole-dict write-back would erase the other's accesses."""
    m = _mem()
    m.write_note("Merge X", "first note")
    m.write_note("Merge Y", "second note")
    base = _engine()
    x0 = base.dynamics_of("merge-x")["access_count"]
    y0 = base.dynamics_of("merge-y")["access_count"]
    a, b = _engine(), _engine()
    a.record_access("merge-x", now=NOW)
    b.record_access("merge-y", now=NOW + timedelta(hours=2))
    a.record_access("merge-x", now=NOW + timedelta(hours=4))
    third = _engine()
    assert third.dynamics_of("merge-x")["access_count"] == x0 + 2
    assert third.dynamics_of("merge-y")["access_count"] == y0 + 1


@pytest.mark.parametrize("payload", [b"{not json", b"\xff\xfe\x00bad", b"[1, 2]"])
def test_corrupt_dynamics_file_is_backed_up_not_overwritten(payload):
    m = _mem()
    m.write_note("Corrupt Probe", "body")
    dyn_path = _vault() / mnemosyne.DYNAMICS_FILE
    dyn_path.write_bytes(payload)
    eng = mnemosyne.Mnemosyne(_vault())
    eng.record_access("corrupt-probe", now=NOW)
    backups = list(_vault().glob(mnemosyne.DYNAMICS_FILE + ".corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == payload
    fresh = json.loads(dyn_path.read_text(encoding="utf-8"))
    assert fresh["notes"]["corrupt-probe"]["access_count"] == 1


def _fake_clock(monkeypatch, start: float = 1000.0) -> list[float]:
    clock = [start]
    monkeypatch.setattr(mnemosyne, "_clock", lambda: clock[0])
    return clock


def _count_index_saves(monkeypatch, eng: mnemosyne.Mnemosyne) -> list[int]:
    saves: list[int] = []
    real = eng._save_index
    monkeypatch.setattr(eng, "_save_index", lambda: saves.append(1) or real())
    return saves


def _cached_slugs() -> set[str]:
    path = _vault() / mnemosyne.INDEX_FILE
    return set(mnemosyne._decode_index(path.read_bytes()))


def test_index_saves_are_coalesced_within_the_interval(monkeypatch):
    clock = _fake_clock(monkeypatch)
    m = _mem()
    saves = _count_index_saves(monkeypatch, m.dex)
    for i in range(20):
        m.write_note(f"Coalesce {i}", f"coalesce body {i}")
    assert len(saves) == 1               # the first write; the rest are dirty
    clock[0] += mnemosyne.INDEX_SAVE_INTERVAL
    m.write_note("Coalesce after", "written past the interval")
    assert len(saves) == 2
    assert len(_cached_slugs()) == 21    # the late save carries every note


def test_flush_persists_a_dirty_index_for_a_new_instance(monkeypatch):
    _fake_clock(monkeypatch)
    m = _mem()
    for i in range(20):
        m.write_note(f"Flush {i}", f"flush body {i}")
    assert len(_cached_slugs()) < 20     # still coalesced on disk
    m.dex.flush()
    assert len(_cached_slugs()) == 20

    def no_reparse(*_a, **_k):
        raise AssertionError("a flushed cache needs no re-parse")

    monkeypatch.setattr(mnemosyne, "_note_entry", no_reparse)
    fresh = mnemosyne.Mnemosyne(_vault())
    assert len(fresh.entries()) == 20


def test_unflushed_index_is_rebuilt_from_the_note_files(monkeypatch):
    _fake_clock(monkeypatch)
    m = _mem()
    for i in range(20):
        m.write_note(f"Crash {i}", f"crash body {i}")
    assert len(_cached_slugs()) < 20
    del m                                # simulated crash: no flush, no atexit
    fresh = mnemosyne.Mnemosyne(_vault())
    assert len(fresh.entries()) == 20
    assert fresh.search("crash", now=NOW)


def test_deferred_save_still_saves_exactly_once(monkeypatch):
    clock = _fake_clock(monkeypatch)
    m = _mem()
    m.write_note("Seed", "seed body")
    clock[0] += mnemosyne.INDEX_SAVE_INTERVAL
    encoded: list[int] = []
    real = mnemosyne._encode_index
    monkeypatch.setattr(mnemosyne, "_encode_index",
                        lambda notes: encoded.append(1) or real(notes))
    with m.dex.deferred_save():
        for i in range(3):
            m.write_note(f"Deferred {i}", f"deferred body {i}")
        assert encoded == []
    assert len(encoded) == 1
    assert len(_cached_slugs()) == 4


def test_exit_hook_flushes_live_instances_and_never_raises(monkeypatch):
    _fake_clock(monkeypatch)
    m = _mem()
    for i in range(3):
        m.write_note(f"Exit {i}", f"exit body {i}")
    assert len(_cached_slugs()) < 3

    def broken() -> None:
        raise RuntimeError("boom")

    bad = _engine()
    monkeypatch.setattr(bad, "flush", broken)
    mnemosyne._live_instances.add(bad)
    mnemosyne._flush_live_instances()    # must swallow the broken instance
    assert len(_cached_slugs()) == 3
