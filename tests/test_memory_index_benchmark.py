"""Score arithmetic must expose regressions and separate abstention."""

import hashlib
import json
from pathlib import Path

from benchmarks.memory_index import run
from benchmarks.memory_index.run import ScoreRow, score_summary
from benchmarks.memory_index.sample import make_sample


def test_scores_do_not_pool_positives_and_abstentions():
    rows: list[ScoreRow] = [
        {"id": "positive-ok", "positive": True, "before_correct": True, "after_correct": True},
        {"id": "positive-lost", "positive": True, "before_correct": True, "after_correct": False},
        {"id": "positive-gain", "positive": True, "before_correct": False, "after_correct": True},
        {"id": "abstention-ok", "positive": False, "before_correct": True, "after_correct": True},
        {"id": "abstention-gain", "positive": False, "before_correct": False, "after_correct": True},
    ]
    report = score_summary(rows)
    assert report["all"] == {"total": 5, "before_correct": 3, "after_correct": 4}
    assert report["positive"] == {"total": 3, "before_correct": 2, "after_correct": 2}
    assert report["abstention"] == {"total": 2, "before_correct": 1, "after_correct": 2}
    assert report["regressions"] == ["positive-lost"]
    assert report["improvements"] == ["positive-gain", "abstention-gain"]


def test_equal_totals_do_not_hide_question_regressions():
    report = score_summary([
        {"id": "lost", "positive": True, "before_correct": True, "after_correct": False},
        {"id": "gained", "positive": True, "before_correct": False, "after_correct": True},
    ])
    assert report["all"]["before_correct"] == report["all"]["after_correct"] == 1
    assert report["regressions"] == ["lost"]
    assert report["improvements"] == ["gained"]


def test_synthetic_corpus_keeps_the_preimplementation_input_hashes():
    baseline = json.loads(
        (Path(__file__).parents[1] / "benchmarks/memory_index/baseline.json").read_bytes())
    actual = {name: hashlib.sha256(text.encode("utf-8")).hexdigest()
              for name, text in make_sample().items()}
    assert actual == baseline["source_sha256"]


def test_routing_receives_only_query_before_answer_scoring(tmp_path, monkeypatch):
    query = "slot"
    fixture = {
        "author": "test-author",
        "identity": {
            "document": "# Distinct section\nSlot: stored answer\n",
            "questions": [{
                "id": "probe", "query": query, "section": "Distinct section",
                "field": "Slot", "answer": "stored answer",
            }],
        },
    }
    (tmp_path / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run, "size", lambda text: {"utf8_bytes": len(text.encode("utf-8"))})
    monkeypatch.setenv("MNEMOSYNE_SEMANTIC", "0")
    calls = []
    real_open = run.MemoryIndex.open

    def observed_open(index, supplied_query, *, limit=3):
        calls.append((supplied_query, limit))
        return real_open(index, supplied_query, limit=limit)
    monkeypatch.setattr(run.MemoryIndex, "open", observed_open)
    result = run.author_result("test-author", "fixture.json")
    assert calls == [(query, 3)]
    assert result["summary"]["all"] == {
        "total": 1, "before_correct": 1, "after_correct": 1}
    assert result["rows"][0]["paths"]
