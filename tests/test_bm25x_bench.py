"""Harness checks using handmade queries only, never the final test questions."""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks/retrieval"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.retrieval import bench_bm25x as bx
from benchmarks.retrieval import bench_retrieval as br
from benchmarks.retrieval import retrieval_corpus as rc
from birkin_mnemosyne.mnemosyne import Mnemosyne


def record(value: bx.JSON) -> Mapping[str, bx.JSON]:
    """Assert the machine-consumed report field is an object before reading it."""
    assert isinstance(value, dict)
    return value


def array(value: bx.JSON) -> list[bx.JSON]:
    """Assert the machine-consumed report field is an array before reading it."""
    assert isinstance(value, list)
    return value


def test_practice_filter_excludes_held_out_and_keeps_extra(monkeypatch):
    # Given
    dev = rc.Query("handmade dev", "one", "exact", "en", "dev")
    held = rc.Query("do not execute", "two", "exact", "en", "test")
    extra = rc.Query("handmade extra", "one", "counter", "en", "dev")
    monkeypatch.setattr(rc, "queries", lambda: [held, dev])
    monkeypatch.setattr(rc, "dev_extra_queries", lambda: [extra])
    # When
    result = bx.practice_queries()
    # Then
    assert result == [dev, extra]


def test_summary_uses_sibling_ranks_and_full_author_language_kind(tmp_path, monkeypatch):
    # Given
    notes = [rc.Note("gold", "cedar", "harbor", "en"),
             rc.Note("sibling", "cedar cedar", "harbor harbor", "ko")]
    br.write_vault(tmp_path, notes)
    queries = [
        rc.Query("cedar harbor", "gold", "exact", "en", "dev",
                 frozenset({"sibling"}), "gpt-6.1-sol"),
        rc.Query("cedar", "sibling", "counter", "ko", "dev",
                 frozenset({"gold"}), "claude-fable-5.1")]
    search = bx.CapturedSearch(Mnemosyne(tmp_path, semantic=False))
    search.build()
    clock = iter([1., 1.01, 2., 2.03])
    monkeypatch.setattr(bx, "time", SimpleNamespace(perf_counter=lambda: next(clock)))
    # When
    result = bx.summary(search, queries)
    # Then
    groups = record(result["by_author_lang_kind"])
    assert groups["dev/gpt-6.1-sol/en/exact"] == br.rank_metrics([1])
    assert groups["dev/claude-fable-5.1/ko/counter"] == br.rank_metrics([1])
    assert len(groups) == 8
    assert groups["dev/gpt-6.1-sol/ko/counter"] == br.rank_metrics([])
    assert [array(row)[-1] for row in array(result["ranks"])] == [1, 1]
    assert len(search.hits) == len(queries)
    serialized = array(result["serialized_hits"])[0]
    assert isinstance(serialized, str)
    assert "score" in json.loads(serialized)[0]
    assert result["query_latency_ms"] == pytest.approx([10., 30.])
    assert record(result["latency_ms"])["p50"] == pytest.approx(20.)
    assert record(record(result["latency_ms_by_author"])["gpt-6.1-sol"])["p50"] == pytest.approx(10.)
    assert record(record(result["latency_ms_by_author_lang"])["dev/claude-fable-5.1/ko"])["p95"] == pytest.approx(30.)
    assert record(record(result["latency_ms_by_author_kind"])["dev/gpt-6.1-sol/exact"])["n"] == 1
    assert record(result["latency_ms_by_author_lang_kind"])["dev/gpt-6.1-sol/ko/counter"] == {
        "p50": None, "p95": None, "n": 0}


def test_capture_original_and_default_once_per_handmade_query(tmp_path, monkeypatch):
    # Given
    br.write_vault(tmp_path, [rc.Note("one", "cedar", "harbor reserve", "en")])
    dex = Mnemosyne(tmp_path, semantic=False)
    default = Mnemosyne(tmp_path, semantic=False)
    original = bx.original_module().Mnemosyne(tmp_path, semantic=False)
    calls = []
    real_search = original.search

    def record(query, **kwargs):
        calls.append(query)
        return real_search(query, **kwargs)

    monkeypatch.setattr(original, "search", record)
    search = bx.CapturedSearch(dex, default, original)
    search.build()
    # When
    search.search("cedar harbor", 10)
    # Then
    assert calls == ["cedar harbor"]
    assert search.hits == search.default_hits == search.original_hits


def test_serialized_hits_detect_score_metadata_and_order_changes():
    # Given
    hits = [{"slug": "one", "score": 0.123456789, "title": "cedar"},
            {"slug": "two", "score": 0.1, "title": "harbor"}]
    variants = [list(reversed(hits)),
                [{**hits[0], "score": 0.123456788}, hits[1]],
                [{**hits[0], "title": "changed"}, hits[1]]]
    # When
    serialized = [bx.serialize_hits(row) for row in variants]
    # Then
    assert all(row != bx.serialize_hits(hits) for row in serialized)


def trial(gpt: float, claude: float, inline: float = 0.5) -> bx.SelectionTrial:
    return {"by_author": {
        a: {m: value for m in bx.METRICS}
        for a, value in zip((*bx.INDEPENDENT, "claude-opus-5.5"),
                            (gpt, claude, inline))}}


def test_selection_rejects_gain_that_regresses_one_independent_author():
    # Given
    runs: list[bx.SelectionRun] = [{"trials": [trial(.5, .5), trial(.9, .4), trial(.6, .6),
                         trial(.7, .7), trial(.8, .8)]},
            {"trials": [trial(.5, .5), trial(.9, .4), trial(.6, .6),
                         trial(.7, .4), trial(.8, .4)]}]
    # When
    selected, eligible = bx.select_config(runs)
    # Then
    assert selected == bx.Config(True, 1.5, 1.5)
    assert eligible == [2]


def test_selection_ties_prefer_smallest_enabled_weights_not_inline_author_gain():
    # Given
    runs: list[bx.SelectionRun] = [{"trials": [trial(.5, .5)] + [trial(.5, .5, .99)] * 4}]
    # When
    selected, _ = bx.select_config(runs)
    # Then
    assert selected == bx.Config(True, 1.25, 1.25)


def test_selection_failing_gate_still_selects_best_enabled_grid():
    # Given
    runs: list[bx.SelectionRun] = [{"trials": [trial(.9, .9), trial(.7, .7), trial(.8, .8),
                         trial(.6, .8), trial(.5, .5)]}]
    # When
    selected, eligible = bx.select_config(runs)
    # Then
    assert selected == bx.Config(True, 1.5, 1.5)
    assert eligible == []


def test_dev_config_loads_only_frozen_field_selection(tmp_path):
    # Given
    path = tmp_path / "dev.json"
    bx.save_report(path, {"phase": "dev", "frozen_source_hashes": bx.source_hashes(),
                         "selected_config": asdict(bx.Config(True, 2, 1.5))})
    # When
    result = bx.load_dev(path)
    # Then
    assert result == bx.Config(True, 2, 1.5)


@pytest.mark.parametrize("change", ["hash", "phase", "flag", "weight", "type"])
def test_dev_config_rejects_changed_sources_or_unselected_values(tmp_path, change):
    # Given
    path = tmp_path / "dev.json"
    hashes = bx.source_hashes()
    selected = asdict(bx.Config(True, 1.5, 1.5))
    data = {"phase": "dev", "frozen_source_hashes": hashes, "selected_config": selected}
    match change:
        case "hash":
            hashes["retrieval_corpus.py"] = "changed"
        case "phase":
            data["phase"] = "test"
        case "flag":
            selected["evidence_diversity"] = True
        case "weight":
            selected["title_weight"] = 7
        case "type":
            selected["field_aware"] = "false"
    bx.save_report(path, data)
    # When / Then
    with pytest.raises(RuntimeError):
        bx.load_dev(path)


def test_synthetic_duplicates_cannot_cover_every_query_unit():
    # Given
    notes, questions = bx.synthetic_fixture()
    by_slug = {n.slug: n for n in notes}
    # When
    complete = [rc.content_units(q.text) <= rc.content_units(
        by_slug[slug].title + " " + by_slug[slug].body)
        for q in questions for slug in q.required[0]]
    # Then
    assert not any(complete)
    assert {q.lang for q in questions} == {"en", "ko", "ja", "zh"}
    assert len(questions) == 8
    assert all(len(q.required[0]) == 17 for q in questions)
    assert len({n.slug for n in notes}) == len(notes)


def test_evidence_coverage_counts_facts_not_duplicate_sources():
    # Given
    q = bx.EvidenceQuestion("one", "en", "handmade",
                            (frozenset({"a", "a-copy"}), frozenset({"b"})))
    # When
    result = bx.evidence_metrics(["a", "a-copy", "b"], q)
    # Then
    assert result["2"] == {"coverage": .5, "all_required": False,
                           "duplicate_slot_rate": .5, "returned": 2}
    assert result["5"] == {"coverage": 1, "all_required": True,
                           "duplicate_slot_rate": 1 / 3, "returned": 3}


def test_synthetic_baseline_saturates_without_rare_second_fact_win(tmp_path):
    # Given: this unit test uses only our own synthetic DEV notes and queries.
    notes, questions = bx.synthetic_fixture()
    br.write_vault(tmp_path, notes)
    search = bx.CapturedSearch(Mnemosyne(tmp_path, semantic=False))
    search.build()
    # When
    hits = [(q, search.search(q.text, 8)) for q in questions]
    # Then
    assert all(len(top) == 8 and set(top) <= q.required[0] for q, top in hits)


def test_synthetic_diversity_returns_both_required_facts_at_two(tmp_path):
    # Given: only our own multilingual synthetic DEV fixture.
    notes, questions = bx.synthetic_fixture()
    br.write_vault(tmp_path, notes)
    search = bx.CapturedSearch(Mnemosyne(
        tmp_path, semantic=False, evidence_diversity=True))
    search.build()
    # When
    results = [bx.evidence_metrics(search.search(q.text, 8), q) for q in questions]
    # Then
    assert all(record(row["2"])["all_required"] for row in results)


def test_cleanup_receipt_asserts_temporary_directory_removed():
    # Given
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
    # When
    result = bx.cleanup_receipt(path)
    # Then
    assert result == {"path": str(path), "absent": True}


def test_cleanup_receipt_rejects_remaining_path(tmp_path):
    # Given / When / Then
    with pytest.raises(AssertionError):
        bx.cleanup_receipt(tmp_path)


def test_timing_summary_preserves_samples_and_interpolates_p95():
    # Given
    values = [1., 3., 5.]
    # When
    result = bx.timing_summary(values)
    # Then
    assert result == {"median": 3., "p95": 4.8, "n": 3, "samples": values}


def test_cli_rejects_invalid_size_before_running_any_phase(tmp_path):
    # Given / When / Then
    with pytest.raises(SystemExit) as error:
        bx.main(["dev", "--sizes", "1", "--output", str(tmp_path / "dev.json")])
    assert error.value.code == 2


@pytest.mark.parametrize("phase,expected", [
    ("dev", [1160, 10160]), ("writes", [1000, 10000])])
def test_cli_phase_option_dispatches_phase_specific_default_sizes(
        tmp_path, monkeypatch, phase, expected):
    # Given: stub only the expensive phase boundary, not CLI parsing or output.
    calls = []

    def quality(sizes):
        calls.append(sizes)
        return {"runs": []}

    def writes(sizes, repeats):
        calls.append(sizes)
        return {"runs": [], "repeats": repeats}

    monkeypatch.setattr(bx, "run_quality", quality)
    monkeypatch.setattr(bx, "run_writes", writes)
    output = tmp_path / "smoke.json"
    # When
    bx.main(["--phase", phase, "--output", str(output)])
    # Then
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == [expected]
    assert report["phase"] == phase
    assert report["size_axis"]["quality_default_distractors"] == [1000, 10000]
    assert report["size_axis"]["writes_default_total_notes"] == [1000, 10000]


def test_cli_rejects_conflicting_phase_aliases(tmp_path):
    # Given / When / Then
    with pytest.raises(SystemExit) as error:
        bx.main(["dev", "--phase", "writes", "--output", str(tmp_path / "out.json")])
    assert error.value.code == 2


def test_small_write_smoke_keeps_full_save_parity_and_separate_timings():
    # Given: three handmade notes, two cycles; no large benchmark phase.
    # When
    result = bx.run_writes([3], 2)
    # Then
    row = record(array(result["runs"])[0])
    assert record(row["cleanup"])["absent"]
    operations = [record(r) for r in array(row["operation_parity"])]
    assert [record(r["state"])["doc_count"] for r in operations] == [4, 4, 3] * 2
    assert all(r["score_byte_parity"] for r in operations)
    assert all(record(record(r)["state"])["doc_count"] == 3 for r in array(row["reload"]))
    for name in ("baseline", "incremental"):
        for op in ("insert", "edit", "delete"):
            full = record(record(record(row["full_write_ms"])[name])[op])
            index = record(record(record(row["index_update_ms"])[name])[op])
            assert full["n"] == index["n"] == 2
            for a, b in zip(array(full["samples"]), array(index["samples"])):
                assert isinstance(a, float) and isinstance(b, float)
                assert a >= b
        assert record(record(row["cache_save_ms"])[name])["n"] == 2
    assert all(record(record(r)["adjust_doclen_ms"])["n"] == 2
               for r in array(row["arithmetic_only"]))


def test_miniature_dev_smoke_records_enabled_selection_and_freeze(monkeypatch):
    # Given: all queries and notes are independently handmade for this test.
    notes = [rc.Note("one", "cedar", "harbor", "en"),
             rc.Note("two", "maple", "oxygen", "en"),
             rc.Note("three", "willow", "neutral", "en")]
    queries = [rc.Query("cedar", "one", "exact", "en", "dev", author=a)
               for a in (*bx.INDEPENDENT, "claude-opus-5.5")]
    monkeypatch.setattr(rc, "queries", lambda: queries)
    monkeypatch.setattr(rc, "dev_extra_queries", list)
    monkeypatch.setattr(rc, "corpus", lambda size, seed: notes)
    monkeypatch.setattr(rc, "gold_notes", lambda: notes)
    # When
    result = bx.run_quality([3])
    # Then
    assert record(result["selected_config"])["field_aware"] is True
    assert record(result["selection"])["selected_trial_index"] in (1, 2, 3, 4)
    assert result["frozen_source_hashes"] == bx.source_hashes()
    run = record(array(result["runs"])[0])
    assert record(run["cleanup"])["absent"]
    trials = array(run["trials"])
    assert len(trials) == 5
    assert all(array(row)[0] == "dev" for trial_row in trials
               for row in array(record(trial_row)["ranks"]))
