"""Round 4 practice protocol: schema, provenance, separation and QA plumbing.

These tests use disposable practice documents built in-memory or under
``tmp_path``. They never read frozen questions, gold or fixtures, and they never
touch the real practice file except to assert it passes its own validation.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Collection
from pathlib import Path
from typing import TypedDict

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from benchmarks.round4 import qa

_parse_fixture_json: Callable[[str], qa.JsonValue] = json.loads


class _FixtureNote(TypedDict):
    title: str
    body: str


class _FixturePair(TypedDict):
    id: str
    topic_group: str
    partition: str
    category: str
    notes: list[_FixtureNote]
    related: bool
    rationale: str


class _FixtureTopic(TypedDict):
    id: str
    partition: str


class _FixtureAuthorBase(TypedDict):
    author: str
    license: str
    source_blind: bool
    topic_groups: list[_FixtureTopic]
    pairs: list[_FixturePair]


class _FixtureAuthor(_FixtureAuthorBase, total=False):
    authoring: str
    source_sha256: str


class _FixtureDocument(TypedDict):
    schema_version: int
    split: str
    license: str
    authors: list[_FixtureAuthor]


def _author(name: str, *, pairs, groups=None, authoring: str | None = None,
            source_sha256: str | None = None) -> _FixtureAuthor:
    payload: _FixtureAuthor = {
        "author": name,
        "license": "CC0-1.0",
        "source_blind": True,
        "topic_groups": groups if groups is not None else [
            {"id": p["topic_group"], "partition": p["partition"]} for p in pairs],
        "pairs": pairs,
    }
    if authoring is not None:
        payload["authoring"] = authoring
    if source_sha256 is not None:
        payload["source_sha256"] = source_sha256
    return payload


def _pair(pid, topic, partition, related, notes=None) -> _FixturePair:
    return {
        "id": pid,
        "topic_group": topic,
        "partition": partition,
        "category": "exact" if related else "unrelated",
        "notes": notes or [
            {"title": f"{pid}-a", "body": f"{pid} body one"},
            {"title": f"{pid}-b", "body": f"{pid} body {'one' if related else 'two'}"},
        ],
        "related": related,
        "rationale": "disposable",
    }


def _document(*, sol_pairs=None, claude_pairs=None, sol_extra=None,
              claude_extra=None) -> _FixtureDocument:
    sol_pairs = sol_pairs if sol_pairs is not None else [
        _pair("s-t", "s-topic-t", "tuning", True),
        _pair("s-v", "s-topic-v", "validation", True),
        _pair("sn-t", "sn-topic-t", "tuning", False),
        _pair("sn-v", "sn-topic-v", "validation", False),
    ]
    claude_pairs = claude_pairs if claude_pairs is not None else [
        _pair("c-t", "c-topic-t", "tuning", True),
        _pair("c-v", "c-topic-v", "validation", True),
        _pair("cn-t", "cn-topic-t", "tuning", False),
        _pair("cn-v", "cn-topic-v", "validation", False),
    ]
    sol = _author(qa.SOL_AUTHOR, pairs=sol_pairs,
                  authoring="practice, not held-out", **(sol_extra or {}))
    claude = _author(qa.CLAUDE_AUTHOR, pairs=claude_pairs,
                     source_sha256=qa.CLAUDE_PRACTICE_SHA256, **(claude_extra or {}))
    return {
        "schema_version": 1,
        "split": "practice",
        "license": "CC0-1.0",
        "authors": [sol, claude],
    }


def _json_document(document: _FixtureDocument) -> dict[str, qa.JsonValue]:
    """The fixture document as the JSON object the protocol functions accept."""
    value = _parse_fixture_json(json.dumps(document))
    assert isinstance(value, dict)
    return value


# --------------------------------------------------------------------------- #
# Real practice file
# --------------------------------------------------------------------------- #

def test_shipped_practice_validates():
    document = qa.load_practice()
    summary = qa.check_practice()
    assert summary["result"] == "PASS"
    assert summary["split"] == "practice"
    by_author = {row["author"]: row for row in summary["authors"]}
    assert by_author[qa.CLAUDE_AUTHOR]["pairs"] == 136
    assert by_author[qa.SOL_AUTHOR]["pairs"] == 48
    for row in summary["authors"]:
        for partition in qa.PARTITIONS:
            assert row["positives"][partition] > 0
            assert row["negatives"][partition] > 0
    assert qa.validate_practice(document)["authors"]


def test_validated_reports_preserve_nested_pair_metadata() -> None:
    document = _parse_fixture_json(json.dumps(_document()))
    assert isinstance(document, dict)
    authors = document["authors"]
    assert isinstance(authors, list)
    author = authors[0]
    assert isinstance(author, dict)
    pairs = author["pairs"]
    assert isinstance(pairs, list)
    pair = pairs[0]
    assert isinstance(pair, dict)
    pair["extension"] = {"sources": ["synthetic"], "flags": [True, None]}
    before = json.dumps(document, sort_keys=True)

    report = qa.validate_practice(document)

    row = next(item for item in report["authors"] if item["author"] == qa.SOL_AUTHOR)
    assert row["pairs"] == pairs
    assert row["positives"] == {"tuning": 1, "validation": 1}
    assert row["negatives"] == {"tuning": 1, "validation": 1}
    assert qa.author_pairs(document, qa.SOL_AUTHOR)[0] == pair
    assert json.dumps(document, sort_keys=True) == before


@pytest.mark.parametrize("author_index", [0, 1])
def test_claimed_source_digest_cannot_hide_changed_note_text(
    tmp_path: Path, author_index: int,
) -> None:
    document = qa.load_practice()
    authors = document["authors"]
    assert isinstance(authors, list)
    author = authors[author_index]
    assert isinstance(author, dict)
    pairs = author["pairs"]
    assert isinstance(pairs, list)
    pair = pairs[0]
    assert isinstance(pair, dict)
    notes = pair["notes"]
    assert isinstance(notes, list)
    note = notes[0]
    assert isinstance(note, dict)
    body = note["body"]
    assert isinstance(body, str)
    note["body"] = body + " modified"
    path = tmp_path / "modified-practice.json"
    _ = path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(qa.ProtocolError, match="author-pairs-digest-drift"):
        _ = qa.load_practice(path)


def test_check_practice_cli_emits_counts_and_digest_only(capsys):
    assert qa.main(["--check-practice"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["result"] == "PASS"
    assert payload["claude_source_sha256"] == qa.CLAUDE_PRACTICE_SHA256
    # No note body text may cross the CLI boundary.
    assert "body" not in output
    assert "\x1f" not in output


# --------------------------------------------------------------------------- #
# Malformed provenance
# --------------------------------------------------------------------------- #

def test_missing_claude_author_fails_closed(tmp_path):
    document = _document()
    document["authors"][1]["author"] = "unknown/model"
    with pytest.raises(qa.ProtocolError, match="claude-opus-5-5"):
        qa.validate_practice(_json_document(document))


def test_wrong_claude_digest_fails_closed():
    document = _document()
    document["authors"][1]["source_sha256"] = "0" * 64
    with pytest.raises(qa.ProtocolError, match="delivered"):
        qa.validate_practice(_json_document(document))


def test_false_source_blind_rejected():
    document = _document()
    document["authors"][0]["source_blind"] = False
    with pytest.raises(qa.ProtocolError, match="source-blind"):
        qa.validate_practice(_json_document(document))


def test_wrong_license_rejected():
    document = _document()
    document["authors"][1]["license"] = "MIT"
    with pytest.raises(qa.ProtocolError, match="CC0-1.0"):
        qa.validate_practice(_json_document(document))


def test_duplicate_json_members_rejected(tmp_path):
    path = tmp_path / "practice.json"
    path.write_text('{"schema_version":1,"schema_version":2}', encoding="utf-8")
    with pytest.raises(qa.ProtocolError, match="duplicate JSON member"):
        qa.load_practice(path)


def test_malformed_json_rejected(tmp_path):
    path = tmp_path / "practice.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(qa.ProtocolError):
        qa.load_practice(path)


@pytest.mark.parametrize("document", [None, False, [], "invalid"])
def test_non_object_practice_json_is_rejected(
    tmp_path: Path, document: qa.JsonValue,
) -> None:
    path = tmp_path / "practice.json"
    _ = path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(qa.ProtocolError):
        _ = qa.load_practice(path)


@pytest.mark.parametrize("config", [
    None, False, [], "invalid",
    {"locked": False, "thresholds": {"min_cosine": 0.9}},
    {"locked": True, "thresholds": None},
    {"locked": True, "thresholds": []},
    {"locked": True, "thresholds": {}},
])
def test_invalid_semantic_config_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: qa.JsonValue,
) -> None:
    path = tmp_path / "thresholds.json"
    _ = path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(qa, "THRESHOLDS_PATH", path)
    with pytest.raises(qa.ProtocolError):
        _ = qa.semantic_thresholds()


def test_sol_provenance_must_say_practice_not_held_out():
    document = _document()
    document["authors"][0]["authoring"] = "independent held-out evaluation set"
    with pytest.raises(qa.ProtocolError, match="not held-out"):
        qa.validate_practice(_json_document(document))


# --------------------------------------------------------------------------- #
# Duplicate ids and note text
# --------------------------------------------------------------------------- #

def test_duplicate_pair_id_rejected():
    document = _document()
    document["authors"][1]["pairs"][1]["id"] = document["authors"][1]["pairs"][0]["id"]
    with pytest.raises(qa.ProtocolError, match="duplicate pair id"):
        qa.validate_practice(_json_document(document))


def test_duplicate_topic_group_id_rejected():
    document = _document()
    document["authors"][1]["topic_groups"].append(
        _FixtureTopic(**document["authors"][1]["topic_groups"][0]))
    with pytest.raises(qa.ProtocolError, match="duplicate topic group ids"):
        qa.validate_practice(_json_document(document))


def test_empty_note_body_rejected():
    document = _document()
    document["authors"][0]["pairs"][0]["notes"][0]["body"] = "   "
    with pytest.raises(qa.ProtocolError, match="note body"):
        qa.validate_practice(_json_document(document))


def test_pair_requires_two_notes():
    document = _document()
    document["authors"][0]["pairs"][0]["notes"] = [
        document["authors"][0]["pairs"][0]["notes"][0]]
    with pytest.raises(qa.ProtocolError, match="exactly two notes"):
        qa.validate_practice(_json_document(document))


def test_empty_inventory_rejected():
    document = _document()
    document["authors"][1]["pairs"] = [
        p for p in document["authors"][1]["pairs"] if p["partition"] == "tuning"
    ]
    document["authors"][1]["topic_groups"] = [
        g for g in document["authors"][1]["topic_groups"] if g["partition"] == "tuning"
    ]
    with pytest.raises(qa.ProtocolError, match="no positive pairs|no negative pairs"):
        qa.validate_practice(_json_document(document))


# --------------------------------------------------------------------------- #
# Topic leakage across partitions
# --------------------------------------------------------------------------- #

def test_topic_group_crossing_partitions_rejected():
    document = _document()
    # Same topic id used for a tuning and a validation pair.
    document["authors"][0]["pairs"][1]["topic_group"] = "s-topic-t"
    with pytest.raises(qa.ProtocolError):
        qa.validate_practice(_json_document(document))


def test_pair_partition_must_match_topic_group():
    document = _document()
    document["authors"][0]["pairs"][0]["partition"] = "validation"
    with pytest.raises(qa.ProtocolError, match="disagrees with its topic group"):
        qa.validate_practice(_json_document(document))


def test_unknown_topic_group_rejected():
    document = _document()
    document["authors"][0]["pairs"][0]["topic_group"] = "does-not-exist"
    with pytest.raises(qa.ProtocolError, match="not declared"):
        qa.validate_practice(_json_document(document))


# --------------------------------------------------------------------------- #
# Tuning report leakage
# --------------------------------------------------------------------------- #

def test_tuning_report_rejects_validation_rows():
    document = _document()
    with pytest.raises(qa.ProtocolError, match="non-tuning pair"):
        _ = qa.tuning_report(_json_document(document), {qa.SOL_AUTHOR: [{"id": "s-v", "label": True}]})


@pytest.mark.parametrize("pair_id", [None, True, 7, [], {}])
def test_tuning_report_rejects_nonstring_pair_identifiers(pair_id: qa.JsonValue) -> None:
    document = _parse_fixture_json(json.dumps(_document()))
    assert isinstance(document, dict)
    row: dict[str, qa.JsonValue] = {"id": pair_id, "related": True}

    with pytest.raises(qa.ProtocolError):
        _ = qa.tuning_report(document, {qa.SOL_AUTHOR: [row]})


def test_tuning_report_rejects_note_text():
    document = _document()
    with pytest.raises(qa.ProtocolError, match="must not carry note text"):
        _ = qa.tuning_report(
            _json_document(document), {qa.SOL_AUTHOR: [{"id": "s-t", "body": "leaked"}]})


def test_tuning_report_accepts_tuning_labels_only():
    document = _document()
    report = qa.tuning_report(
        _json_document(document), {qa.SOL_AUTHOR: [{"id": "s-t", "related": True}]})
    author = next(a for a in report["authors"] if a["author"] == qa.SOL_AUTHOR)
    assert author["outcomes"] == [{"id": "s-t", "related": True}]
    # Validation pairs never appear in a tuning report.
    serialized = json.dumps(report)
    assert "s-v" not in serialized


def test_tuning_report_preserves_nested_label_counts() -> None:
    document = _parse_fixture_json(json.dumps(_document()))
    assert isinstance(document, dict)
    outcome: dict[str, qa.JsonValue] = {
        "id": "s-t", "related": True,
        "counts": {"tp": 1, "fp": 0},
        "labels": [True, False, None],
    }
    before = json.dumps(outcome, sort_keys=True)

    report = qa.tuning_report(document, {qa.SOL_AUTHOR: [outcome]})

    author = next(row for row in report["authors"] if row["author"] == qa.SOL_AUTHOR)
    assert author["outcomes"] == [outcome]
    assert json.dumps(outcome, sort_keys=True) == before


def test_selection_plan_omits_validation_bodies():
    document = _document()
    plan = qa.tuning_selection_plan(_json_document(document), qa.CLAUDE_AUTHOR)
    assert plan["tuning_topic_groups"] == ["c-topic-t", "cn-topic-t"]
    assert plan["validation_topic_groups"] == ["c-topic-v", "cn-topic-v"]
    assert plan["cosine_grid"][0] == 0.5 and plan["cosine_grid"][-1] == 0.98
    assert plan["margin_grid"][0] == 0.0 and plan["margin_grid"][-1] == 0.20
    assert "body" not in json.dumps(plan)


# --------------------------------------------------------------------------- #
# Pair inventory and accounting
# --------------------------------------------------------------------------- #

def test_authored_pair_key_preserves_direction_and_note_bytes() -> None:
    pair: dict[str, qa.JsonValue] = {
        "notes": [
            {"title": "Zulu", "body": "\ufeffOriginal\r\nfinal \U0001f680"},
            {"title": "Alpha", "body": "  Keep surrounding spaces.  "},
        ],
    }

    keys = qa.order_key_of(pair)

    assert keys == (
        "Zulu\x1f\ufeffOriginal\r\nfinal \U0001f680",
        "Alpha\x1f  Keep surrounding spaces.  ",
    )


def test_unordered_inventory_is_orientation_independent():
    document = _document()
    inventory = qa.unordered_pair_inventory(_json_document(document))
    keys = list(inventory[qa.SOL_AUTHOR])
    assert all(isinstance(key, tuple) and len(key) == 2 for key in keys)
    assert len(keys) == 4


def test_pair_accounting_counts_tp_fp_fn():
    document = _document()
    keys = list(qa.unordered_pair_inventory(_json_document(document))[qa.SOL_AUTHOR])
    positives = [k for k in keys if qa.unordered_pair_inventory(
        _json_document(document))[qa.SOL_AUTHOR][k]["related"]]
    negatives = [k for k in keys if not qa.unordered_pair_inventory(
        _json_document(document))[qa.SOL_AUTHOR][k]["related"]]
    offered = [positives[0], negatives[0]]
    counts = qa.pair_accounting(_json_document(document), qa.SOL_AUTHOR, offered)
    assert counts == {"tp": 1, "fp": 1, "fn": 1, "abstained": 1}


def test_offered_pair_counts_deduplicate_reversed_pairs() -> None:
    document = _parse_fixture_json(json.dumps(_document()))
    assert isinstance(document, dict)
    inventory = qa.ordered_pair_inventory(document, qa.SOL_AUTHOR)
    positive = min(inventory["positives"])
    negative = min(inventory["negatives"])
    offered = [
        positive, (positive[1], positive[0]),
        negative, (negative[1], negative[0]),
    ]

    counts = qa.count_offered(inventory, offered)

    assert counts == {"tp": 1, "fp": 1, "fn": 1, "abstained": 1}
    assert counts == qa.pair_accounting(document, qa.SOL_AUTHOR, offered)
    assert inventory["entries"] == qa.unordered_pair_inventory(document)[qa.SOL_AUTHOR]


def test_pair_accounting_rejects_foreign_pair():
    document = _document()
    with pytest.raises(qa.ProtocolError, match="not in the authored inventory"):
        qa.pair_accounting(_json_document(document), qa.SOL_AUTHOR, [("x\x1fy", "z\x1fw")])


def test_pair_accounting_scope_limits_denominator():
    document = _document()
    keys = list(qa.unordered_pair_inventory(_json_document(document))[qa.SOL_AUTHOR])
    scope = [keys[0]]
    counts = qa.pair_accounting(_json_document(document), qa.SOL_AUTHOR, [], scope=scope)
    assert counts["fn"] == 1


def test_capped_recall_is_not_complete_recall():
    totals: qa._PairCounts = {"tp": 25, "fp": 0, "fn": 5, "abstained": 5}
    # 30 positives: the public cap of 20 binds (20/30), while the MCP cap of 100
    # does not, so recall@100 is the complete recall of tp/(tp+fn) = 25/30.
    assert qa._capped_recall(totals, qa.PUBLIC_QUESTION_CAP) == round(20 / 30, 4)
    assert qa._capped_recall(totals, qa.MCP_QUESTION_CAP) == round(25 / 30, 4)
    assert qa._capped_recall(totals, qa.PUBLIC_QUESTION_CAP) < \
        qa._capped_recall(totals, qa.MCP_QUESTION_CAP)


def test_recall_capture_scenarios_cover_required_shapes():
    captures = qa.recall_capture_scenarios()
    cases = {case["case"] for case in captures}
    assert {"recall-at-20", "recall-at-100", "crowded-neighborhood",
            "multiple-translations"} <= cases
    for case in captures:
        assert case["result"] == "OBSERVED"
        assert case["product_quality_claimed"] is False
        assert case["cleanup_absent"] is True
        assert "cleanup_root" in case
        assert not Path(case["cleanup_root"]).exists()
        for cap, capture in case["captures"].items():
            counts = capture["counts"]
            assert counts["tp"] + counts["fn"] == case["positives"]
            assert capture["offered"] == counts["tp"] + counts["fp"]
            assert capture["offered"] == counts["tp"] + counts["fp"]
            assert capture["offered"] <= int(cap)


def test_recall_scenarios_are_real_executions_not_declarations():
    """The crowded/crowded-min/translation cases must run the actual pipeline."""
    captures = qa.recall_capture_scenarios()
    by_case = {case["case"]: case for case in captures}

    crowded = by_case["crowded-neighborhood"]
    assert crowded["result"] == "OBSERVED"
    assert "exceeds_threshold" in crowded
    assert crowded["exceeds_threshold"] is True
    assert crowded["notes"] > qa.CROWDED_NEIGHBORHOOD_MIN
    # 40 notes yield 780 unordered pairs, all authored positive.
    assert crowded["gold_pairs"] == 40 * 39 // 2
    assert set(crowded["captures"]) == {"10000", "20", "100"}

    translations = by_case["multiple-translations"]
    assert "variants" in translations
    assert "distinct" in translations
    assert translations["variants"] == ["en", "ko", "ja"]
    assert translations["distinct"] is True
    assert translations["notes"] == 3
    # Three mutually translated notes form three authored positive pairs.
    assert translations["positives"] == 3

    small = by_case["recall-at-20"]
    assert small["positives"] == 28 > qa.REQUIRED_TRUE_PAIRS_MIN
    # Capped recall labels must be present and distinct from complete recall.
    for case in captures:
        assert f"recall@{qa.PUBLIC_QUESTION_CAP}" in case
        assert f"recall@{qa.MCP_QUESTION_CAP}" in case
        assert 0.0 <= case[f"recall@{qa.PUBLIC_QUESTION_CAP}"] <= 1.0


def test_crowded_neighborhood_plan_is_executable_with_gold_inventory():
    document = qa.load_practice()
    plan = qa.crowded_neighborhood_plan(document, qa.CLAUDE_AUTHOR)
    assert plan["case"] == "crowded-neighborhood"
    assert plan["drivable"] is True
    assert plan["notes"] > qa.CROWDED_NEIGHBORHOOD_MIN
    assert plan["exceeds_threshold"] is True
    assert plan["gold_pairs"] == plan["notes"] * (plan["notes"] - 1) // 2
    # The plan ships counts, not only prose: the fixture is materializable.
    assert plan["distinct_notes"] == plan["notes"]


def test_mixed_vault_uses_one_case_per_topic_and_labels_cross_pairs():
    document = qa.load_practice()
    fixture = qa.mixed_vault_fixture(document, qa.CLAUDE_AUTHOR, related=True)
    selected_topics = fixture["selected_topic_groups"]
    assert len(selected_topics) == len(set(selected_topics))
    assert len(fixture["selected_pairs"]) == len(selected_topics)
    inventory = fixture["authored_inventory"]
    # Every authored positive holds within one topic; cross-topic pairs are
    # labeled false by the fixture's own disjoint-topic scope.
    for row in inventory:
        if row["related"]:
            assert row["first"] + 1 == row["second"]
    cross = [row for row in inventory if row["topic_group"] == "cross-topic-disjoint"]
    assert cross and all(not row["related"] for row in cross)


def test_mixed_vault_semantic_flag_is_forwarded(monkeypatch, tmp_path):
    """A supported semantic service in a mixed vault must be driven, not skipped."""
    from types import SimpleNamespace

    import birkin_mnemosyne

    document = qa.load_practice()
    config = tmp_path / "thresholds.json"
    config.write_text(json.dumps({"locked": True,
                                  "thresholds": {"min_cosine": 0.9}}),
                      encoding="utf-8")
    seen = []

    class Service:
        def __init__(self, vault, *, semantic=False, thresholds=None):
            self.vault = vault
            self.semantic_status = "ready"
            seen.append(semantic)

        def questions(self, limit=20):
            paths = sorted((self.vault / "knowledge").glob("*.md"))
            if len(paths) < 2 or limit == qa.PUBLIC_QUESTION_CAP:
                return ()
            return (SimpleNamespace(
                first=SimpleNamespace(path=paths[0].relative_to(self.vault).as_posix()),
                second=SimpleNamespace(path=paths[1].relative_to(self.vault).as_posix()),
            ),)

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", Service)
    monkeypatch.setattr(qa, "THRESHOLDS_PATH", config)
    fixture = qa.mixed_vault_fixture(document, qa.SOL_AUTHOR, related=True, semantic=True)
    assert fixture["result"] == "OBSERVED"
    assert fixture["semantic_status"] == "ready"
    assert seen and all(semantic is True for semantic in seen)
    assert fixture["authored_positive_pairs"] > 0


def test_counted_pairs_come_from_offered_outputs_not_gold(monkeypatch):
    """A service that never offers its authored positive pair cannot score a TP."""
    import birkin_mnemosyne

    class SilentService:
        def __init__(self, vault, **kwargs):
            self.vault = vault
            self.semantic_status = "ready"

        def questions(self, limit=20):
            return ()

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", SilentService)
    document = qa.load_practice()
    fixture = qa.mixed_vault_fixture(document, qa.SOL_AUTHOR, related=True)
    assert fixture["result"] == "OBSERVED"
    for capture in fixture["captures"].values():
        assert capture["offered"] == 0
        assert capture["counts"]["tp"] == 0
    # The authored positive pairs exist, yet none is counted without an offer.
    assert fixture["authored_positive_pairs"] > 0
    assert fixture["captures"]["10000"]["counts"]["fn"] == \
        fixture["authored_positive_pairs"]


def test_empty_real_discovery_cannot_manufacture_true_positives(monkeypatch):
    from itertools import combinations

    import birkin_mnemosyne

    limits = []

    class EmptyService:
        def __init__(self, vault):
            self.vault = vault

        def questions(self, limit=20):
            limits.append(limit)
            assert len(list((self.vault / "knowledge").glob("*.md"))) == 8
            return ()

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", EmptyService)
    notes = [{"title": f"Policy copy {index}", "body": "Approval precedes publication."}
             for index in range(8)]
    result = qa._capture_questions(notes, set(combinations(range(8), 2)))
    assert limits == [10_000, 20, 100]
    assert result["result"] == "OBSERVED"
    assert result["positives"] == 28
    for capture in result["captures"].values():
        assert capture["offered"] == 0
        assert capture["counts"] == {"tp": 0, "fp": 0, "fn": 28, "abstained": 28}


# --------------------------------------------------------------------------- #
# Public scenario plumbing (nothing here fakes product success)
# --------------------------------------------------------------------------- #

def test_startup_scenario_legacy_passes(monkeypatch):
    original_temporary = qa.tempfile.TemporaryDirectory
    owned_roots = []

    def tracked_temporary(*args, **kwargs):
        directory = original_temporary(*args, **kwargs)
        owned_roots.append(Path(directory.name))
        return directory

    monkeypatch.setattr(qa.tempfile, "TemporaryDirectory", tracked_temporary)
    result = qa.startup_scenario()
    assert result["result"] == "LEGACY-PASS"
    assert result["observed"]["bytes_reconstruct"] is True
    assert len(owned_roots) == 1
    assert not owned_roots[0].exists()


def test_startup_compact_reports_pending_without_faking(tmp_path):
    result = qa.startup_scenario(compact=True)
    assert result["result"] in {"PASS", "PENDING"}
    if result["result"] == "PENDING":
        assert "compact" in result["reason"]


def test_questions_semantic_reports_pending_without_faking(monkeypatch, tmp_path):
    # The shipped product today has no semantic constructor; the driver must
    # report PENDING against the actual API rather than fake a pass.
    result = qa.questions_scenario(semantic=True)
    assert result["result"] in {"PASS", "PENDING"}
    if result["result"] == "PENDING":
        assert "semantic" in result["reason"]

    # A genuinely ready semantic service must NOT stay permanently pending.
    from types import SimpleNamespace

    import birkin_mnemosyne

    config = tmp_path / "thresholds.json"
    config.write_text(json.dumps({"locked": True,
                                  "thresholds": {"min_cosine": 0.9}}),
                      encoding="utf-8")
    ready = {"tp": 0}

    class ReadySemanticService:
        def __init__(self, vault, *, semantic=False, thresholds=None):
            self.vault = vault
            self.semantic_status = "starting"
            assert semantic and thresholds == {"min_cosine": 0.9}

        def questions(self, limit=20):
            self.semantic_status = "ready"
            paths = sorted((self.vault / "knowledge").glob("*.md"))
            ready["tp"] = 1
            return (SimpleNamespace(
                first=SimpleNamespace(path=paths[0].relative_to(self.vault).as_posix()),
                second=SimpleNamespace(path=paths[1].relative_to(self.vault).as_posix()),
            ),)

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", ReadySemanticService)
    monkeypatch.setattr(qa, "THRESHOLDS_PATH", config)
    supported = qa.questions_scenario(semantic=True)
    assert supported["result"] == "PASS", supported
    assert supported["observed"]["semantic_status"] == "ready"
    assert supported["observed"]["confusion"]["tp"] > 0


def test_questions_lexical_scenario_reports_observed_counts():
    result = qa.questions_scenario(author=qa.SOL_AUTHOR)
    assert result["result"] == "PASS"
    observed = result["observed"]
    assert observed["tuning_pairs"] == 24
    assert set(observed["confusion"]) == {"tp", "fp", "fn", "abstained"}
    assert 0.0 <= observed["precision"] <= 1.0
    assert 0.0 <= observed["complete_recall"] <= 1.0


@pytest.mark.parametrize("final_status", ["ready", "unavailable"])
def test_semantic_questions_use_original_titles_config_and_actual_cap_calls(
        tmp_path, monkeypatch, final_status):
    from types import SimpleNamespace

    import birkin_mnemosyne
    from birkin_mnemosyne import frontmatter

    document = _document()
    constructors = []
    limits = []
    titles = []
    thresholds = {"min_cosine": 0.95, "min_margin": 0.05}
    config = tmp_path / "thresholds.json"
    config.write_text(json.dumps({"locked": True, "thresholds": thresholds}),
                      encoding="utf-8")

    class SemanticService:
        def __init__(self, vault, *, semantic=False, thresholds=None):
            self.vault = vault
            self.semantic_status = "starting"
            constructors.append((semantic, thresholds))

        def questions(self, limit=20):
            limits.append(limit)
            self.semantic_status = final_status
            paths = sorted((self.vault / "knowledge").glob("*.md"))
            for path in paths:
                metadata, _body = frontmatter.parse(path.read_text(encoding="utf-8"))
                titles.append(metadata["title"])
            if limit == 20:
                return ()
            return (SimpleNamespace(
                first=SimpleNamespace(path=paths[0].relative_to(self.vault).as_posix()),
                second=SimpleNamespace(path=paths[1].relative_to(self.vault).as_posix()),
            ),)

    monkeypatch.setattr(birkin_mnemosyne, "Consolidation", SemanticService)
    monkeypatch.setattr(qa, "load_practice", lambda _path: dict(document))
    monkeypatch.setattr(qa, "THRESHOLDS_PATH", config)
    result = qa.questions_scenario(semantic=True)
    assert all(semantic and received == thresholds
               for semantic, received in constructors)
    if final_status == "unavailable":
        assert result["result"] == "PENDING"
        assert result.get("semantic_status") == "unavailable"
        assert limits == [10_000]
        return
    assert result["result"] == "PASS"
    observed = result["observed"]
    assert observed["semantic_status"] == "ready"
    # The two tuning cases contain one authored positive and one hard negative.
    # Offering both must preserve that distinction instead of manufacturing TPs.
    assert observed["confusion"] == {"tp": 1, "fp": 1, "fn": 0, "abstained": 0}
    assert observed["precision"] == 0.5
    assert observed["complete_recall"] == 1.0
    assert observed["public_recall_at_20"] == 0.0
    assert observed["mcp_recall_at_100"] == 1.0
    # Complete, public-20 and MCP-100 are always requested in that order, once
    # per materialized vault; never a single capped call standing in for all.
    assert limits[:6] == [10_000, 20, 100] * 2
    assert all(limits[index:index + 3] == [10_000, 20, 100]
               for index in range(0, len(limits), 3))
    expected_titles = {
        note["title"] for pair in document["authors"][0]["pairs"]
        if pair["partition"] == "tuning" for note in pair["notes"]
    }
    assert expected_titles <= set(titles)
    assert len(observed["mixed_vaults"]) == 2
    assert all(fixture["authored_inventory"] for fixture in observed["mixed_vaults"])
    crowded_vault = observed["crowded_vault"]
    assert crowded_vault["notes"] > qa.CROWDED_NEIGHBORHOOD_MIN
    assert crowded_vault["exceeds_threshold"] is True
    assert crowded_vault["gold_inventory_complete"] is True
    assert crowded_vault["result"] == "OBSERVED"
    assert observed["crowded_fixture"]["notes"] > qa.CROWDED_NEIGHBORHOOD_MIN
    assert observed["crowded_fixture"]["exceeds_threshold"] is True
    assert {case["case"] for case in observed["synthetic_regressions"]} == {
        "recall-at-20", "recall-at-100", "crowded-neighborhood", "multiple-translations"}


def test_pair_inventory_scenario_reports_scale():
    result = qa.pair_inventory_scenario(author=qa.CLAUDE_AUTHOR)
    assert result["result"] == "PASS"
    assert result["unordered_pairs"] == 136
    assert result["meets_true_pair_minimum"] is True


def test_synthetic_inputs_are_deterministic_and_distinct():
    first = qa.synthetic_notes(8)
    second = qa.synthetic_notes(8)
    assert first == second
    assert len({note["body"] for note in first}) == 8
    edges = qa.edge_mutation_notes()
    assert any("\r\n" in note["body"] for note in edges)
    assert any(note["body"].startswith("\ufeff") for note in edges)
    assert any(any(ord(ch) > 0xFFFF for ch in note["body"]) for note in edges)


def test_crowded_neighborhood_threshold_matches_requirement():
    assert qa.CROWDED_NEIGHBORHOOD_MIN == 32
    assert qa.REQUIRED_TRUE_PAIRS_MIN == 20
    assert qa.PUBLIC_QUESTION_CAP == 20
    assert qa.MCP_QUESTION_CAP == 100


# --------------------------------------------------------------------------- #
# QA-2 independent presentation oracle (finding3 correction)
# --------------------------------------------------------------------------- #

_HOMOGENEOUS_DATES = (
    "TOP NOTE 2026-09-01\nOld\nTOP NOTE 2026-10-01\n"
    "Supersedes: TOP NOTE 2026-09-01\nNew\n"
)
_MIXED_PRECISION_DATES = (
    "TOP NOTE 2026-09-01\nPort: 4100\nTOP NOTE 2026-10-01\n"
    "Supersedes: TOP NOTE 2026-09-01\nPort: 4200\n"
    "TOP NOTE 2026-11-01T08:30:00Z\nPort: 4300\n"
)


def _source(text: str) -> dict[str, bytes]:
    return {"f.md": text.encode("utf-8")}


def test_natural_closure_accepts_a_noncanonical_root(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    alias_base = tmp_path / "alias"
    alias_base.mkdir()
    _ = (root / "MODE.md").write_bytes(b"MUST READ: inside.md\n")
    _ = (root / "inside.md").write_bytes(b"Required fact.\r\n")

    observed = qa._natural_closure(alias_base / ".." / "vault", ["MODE.md"])

    assert observed == {
        "MODE.md": b"MUST READ: inside.md\n",
        "inside.md": b"Required fact.\r\n",
    }


def test_natural_closure_still_refuses_escape_from_an_aliased_root(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    alias_base = tmp_path / "alias"
    alias_base.mkdir()
    _ = (root / "MODE.md").write_bytes(b"MUST READ: ../outside.md\n")
    _ = (tmp_path / "outside.md").write_bytes(b"Outside fact.\n")

    with pytest.raises(qa.ProtocolError, match="escaped the configured root"):
        qa._natural_closure(alias_base / ".." / "vault", ["MODE.md"])


def test_homogeneous_note_dates_reorder_and_supersede():
    # Equal single-precision stamps sort descending; the older group is the
    # superseded target. Byte offsets are the machine-consumed order records.
    sources = _source(_HOMOGENEOUS_DATES)
    order, expected = qa._natural_order_overrides(sources)
    assert order == [{"path": "f.md", "reorder": [[24, 0]], "superseded": [0]}]
    assert (expected[0]["start_byte"], expected[0]["state"]) == (24, "source")
    assert (expected[1]["start_byte"], expected[1]["state"]) == (
        0, "explicitly-superseded")
    assert qa._natural_compare_order(sources, order, expected)["match"] is True


def test_mixed_precision_dates_supersede_without_sort():
    # Differing precisions forbid the automatic date sort; supersession stands.
    sources = _source(_MIXED_PRECISION_DATES)
    order, expected = qa._natural_order_overrides(sources)
    assert order == [{"path": "f.md", "superseded": [0]}]
    assert [record["start_byte"] for record in expected] == [0, 31, 94]
    assert expected[0]["state"] == "explicitly-superseded"


def test_plain_rule_yields_no_order_overrides():
    sources = _source("Rule 7 keeps a final source line with no trailing newline")
    order, _expected = qa._natural_order_overrides(sources)
    assert order == []


def test_scoped_child_travels_with_the_note_group():
    # A deeper heading is a descendant of the TOP NOTE group, so its bytes move
    # with the group and the group identity is the note's natural start byte.
    sources = _source(
        "TOP NOTE 2026-09-01\n### Child\nBody\nTOP NOTE 2026-10-01\n"
        "Supersedes: TOP NOTE 2026-09-01\nNested body\n")
    order, expected = qa._natural_order_overrides(sources)
    assert order == [{"path": "f.md", "reorder": [[35, 0]], "superseded": [0]}]
    assert [(r["start_byte"], r["state"]) for r in expected] == [
        (35, "source"), (0, "explicitly-superseded"),
        (20, "explicitly-superseded")]


def test_duplicate_note_dates_forbid_sort():
    sources = _source("TOP NOTE 2026-09-01\nA\nTOP NOTE 2026-09-01\nB\n")
    order, expected = qa._natural_order_overrides(sources)
    assert order == []
    assert [record["state"] for record in expected] == ["source", "source"]


def test_separate_note_runs_keep_independent_permutations() -> None:
    first = "TOP NOTE 2026-01-01\nA\nTOP NOTE 2026-02-01\nB\n"
    barrier = "# Independent rule\nRule\n"
    second = "TOP NOTE 2026-03-01\nC\nTOP NOTE 2026-04-01\nD\n"
    sources = _source(first + barrier + second)
    offset = len((first + barrier).encode("utf-8"))
    first_next = len(b"TOP NOTE 2026-01-01\nA\n")
    second_next = len(b"TOP NOTE 2026-03-01\nC\n")
    order, expected = qa._natural_order_overrides(sources)
    assert order == [{"path": "f.md",
                     "reorder": [[first_next, 0], [offset + second_next, offset]]}]
    assert qa._natural_compare_order(sources, order, expected)["match"] is True


@pytest.mark.parametrize("reorder", [[[24, 24]], [[24, 0], [24, 0]]])
def test_repeated_reorder_groups_fail_closed(reorder: list[list[int]]) -> None:
    sources = _source(_HOMOGENEOUS_DATES)
    with pytest.raises(qa.ProtocolError):
        qa._natural_compare_order(
            sources, [{"path": "f.md", "reorder": reorder}],
            qa._natural_expected(sources))


def test_reorder_cannot_cross_a_non_note_barrier() -> None:
    sources = _source("TOP NOTE 2026-01-01\nA\n# Rule\nB\nTOP NOTE 2026-02-01\nC\n")
    newer = len(b"TOP NOTE 2026-01-01\nA\n# Rule\nB\n")
    with pytest.raises(qa.ProtocolError):
        qa._natural_compare_order(
            sources, [{"path": "f.md", "reorder": [[newer, 0]]}],
            qa._natural_expected(sources))


@pytest.mark.parametrize("advertised", [
    [],                                                    # dropped effect
    [{"path": "f.md", "reorder": [[0, 24]], "superseded": [0]}],   # reversed run
    [{"path": "f.md", "superseded": [24]}],                # wrong state target
    [{"path": "f.md", "reorder": [[24, 0]], "superseded": []}],   # noncanonical
])
def test_wrong_or_missing_order_overrides_fail_the_oracle(advertised):
    sources = _source(_HOMOGENEOUS_DATES)
    expected = qa._natural_expected(sources)
    if advertised and "superseded" in advertised[0] and advertised[0]["superseded"] == []:
        with pytest.raises(qa.ProtocolError):
            qa._natural_parse_context(
                json.dumps({"version": 2, "files": [
                    {"path": "f.md", "text": _HOMOGENEOUS_DATES}], "order": advertised}),
                sources)
        return
    verdict = qa._natural_compare_order(sources, advertised, expected)
    assert verdict["match"] is False


def test_foreign_or_unknown_group_overrides_are_rejected():
    sources = _source(_HOMOGENEOUS_DATES)
    with pytest.raises(qa.ProtocolError):
        qa._natural_compare_order(
            sources, [{"path": "foreign.md", "reorder": [[24, 0]]}],
            qa._natural_expected(sources))
    with pytest.raises(qa.ProtocolError):
        qa._natural_compare_order(
            sources, [{"path": "f.md", "reorder": [[80, 0]], "superseded": [0]}],
            qa._natural_expected(sources))


@pytest.mark.parametrize("context", [
    '{"version":2,"files":[{"path":"f.md","text":"x"}],"order":[],"version":2}',
    '{"version":2,"files":[{"path":"f.md","text":"x"}],"order":[],"\\u0076ersion":2}',
    '{"version":true,"files":[{"path":"f.md","text":"x"}],"order":[]}',
    '{"version":1,"files":[{"path":"f.md","text":"x"}],"order":[]}',
    '{"version":2,"files":[{"path":"f.md","text":"x"},{"path":"f.md","text":"x"}],"order":[]}',
    '{"version":2,"files":[{"path":"f.md","text":"y"}],"order":[]}',
    '{"version":2,"files":[{"path":"f.md","text":"x"}]}',
    '{"version":2,"files":[{"path":"f.md","text":"x"}],"order":[],"extra":1}',
    '{"version":2,"files":[{"path":"f.md","text":"x"}],"order":[{"path":"f.md"}]}',
    '{"version":2,"files":[{"path":"f.md","text":"x"}],"order":[{"path":"f.md","reorder":[],"superseded":[]}]}',
])
def test_malformed_compact_contexts_fail_closed(context):
    with pytest.raises(qa.ProtocolError):
        qa._natural_parse_context(context, {"f.md": b"x"})


def test_compact_files_must_follow_raw_source_closure_order():
    sources = {"a.md": b"x", "b.md": b"y"}
    good = ('{"version":2,"files":[{"path":"a.md","text":"x"},'
            '{"path":"b.md","text":"y"}],"order":[]}')
    assert qa._natural_parse_context(good, sources)["files"] == sources
    swapped = ('{"version":2,"files":[{"path":"b.md","text":"y"},'
               '{"path":"a.md","text":"x"}],"order":[]}')
    with pytest.raises(qa.ProtocolError):
        qa._natural_parse_context(swapped, sources)


def test_non_note_file_cannot_advertise_a_group_boundary():
    # A file without a TOP NOTE has no groups, so any reorder effect is foreign.
    sources = _source("# Head\nBody\n")
    with pytest.raises(qa.ProtocolError):
        qa._natural_compare_order(
            sources, [{"path": "f.md", "reorder": [[0, 6]], "superseded": [0]}],
            qa._natural_expected(sources))


def test_synthetic_fixture_expectation_is_superseded_only():
    # The built-in QA-2 fixture mixes date precisions, so the independent oracle
    # expects only the superseded effect, never an automatic date sort.
    sources = {name: text.encode("utf-8")
               for name, text in qa.synthetic_startup_files().items()}
    order, _expected = qa._natural_order_overrides(sources)
    assert order == [{"path": "handoff.md", "superseded": [0]}]


def test_legacy_driver_derives_the_same_presentation():
    # The independent oracle must not drift from the legacy reader it stands in
    # for: derive order/state from the real legacy blocks and require the natural
    # oracle to reproduce the identical ordered spans on the synthetic fixture.
    import tempfile

    from birkin_mnemosyne.startup import StartupReader

    sources = qa.synthetic_startup_files()
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r4-oracle-legacy-") as directory:
        root = Path(directory)
        (root / "profile").mkdir()
        for name, text in sources.items():
            (root / name).write_bytes(text.encode("utf-8"))
        payload = json.loads(StartupReader(root).read(list(qa.STARTUP_CLOSURE)).context)
        legacy = [
            (block["path"], block["start_byte"], block["end_byte"],
             block["start_line"], block["heading"], block["state"])
            for block in payload["blocks"]]
        natural = [
            (record["path"], record["start_byte"], record["end_byte"],
             record["start_line"], record["heading"], record["state"])
            for record in qa._natural_expected(qa._natural_closure(
                root, list(qa.STARTUP_CLOSURE)))]
    assert natural == legacy
    assert not Path(directory).exists()


def _disposable_compact(monkeypatch, order_mutator):
    """Install a self-consistent v2 reader with a caller-supplied order effect."""
    from types import SimpleNamespace

    import birkin_mnemosyne.startup as startup_module

    real = startup_module.StartupReader

    class WrongOrderReader:
        def __init__(self, root):
            self.reader = real(root)

        def _payload(self, paths):
            bundle = self.reader.read(paths)
            old = json.loads(bundle.context)
            files, raw = [], {}
            for record in old["files"]:
                joined = "".join(
                    block["text"] for block in sorted(
                        [b for b in old["blocks"] if b["path"] == record["path"]],
                        key=lambda b: b["start_byte"]))
                files.append({"path": record["path"], "text": joined})
                raw[record["path"]] = joined.encode("utf-8")
            order = order_mutator(raw)
            return SimpleNamespace(
                context=json.dumps({"version": 2, "files": files, "order": order}),
                coverage=bundle.coverage, cache_hit=False)

        def read(self, paths, *, compact=False):
            return self._payload(paths)

        def verify(self, context, paths):
            return SimpleNamespace(
                complete=json.loads(context) == json.loads(self._payload(paths).context))

    monkeypatch.setattr(startup_module, "StartupReader", WrongOrderReader)


def test_always_successful_verifier_with_dropped_order_cannot_pass(monkeypatch):
    # Reproduces finding3: an internally consistent reader that advertises an
    # empty order[] (dropping the real superseded effect) must not be reported
    # PASS now that the QA-local oracle decides the compact verdict.
    _disposable_compact(monkeypatch, lambda _raw: [])
    with pytest.raises(AssertionError, match="order_state_agrees"):
        qa.startup_scenario(compact=True)


def test_always_successful_verifier_with_wrong_state_cannot_pass(monkeypatch):
    # A reader that supersedes the wrong group start and omits the real effect is
    # refused; the oracle never repairs the missing presentation state for it.
    def wrong_state(raw):
        order, _expected = qa._natural_order_overrides(raw)
        _ = order
        return [{"path": next(iter(raw)), "superseded": [999999]}]

    _disposable_compact(monkeypatch, wrong_state)
    with pytest.raises(qa.ProtocolError, match="compact superseded"):
        qa.startup_scenario(compact=True)


def test_independently_correct_compact_reader_passes(monkeypatch):
    # The positive direction: a correct canonical v2 order passes the oracle.
    def correct(raw):
        return qa._natural_order_overrides(raw)[0]

    _disposable_compact(monkeypatch, correct)
    result = qa.startup_scenario(compact=True)
    assert result["result"] == "PASS"
    oracle = result["observed"]["order_state_oracle"]
    assert isinstance(oracle, dict)
    assert oracle["initial_match"] is True and oracle["fresh_match"] is True
    assert oracle["expected_initial"] == [{"path": "handoff.md", "superseded": [0]}]


# --------------------------------------------------------------------------- #
# QA-3 kibitzer public scenario (contract + truthful ranking report)
# --------------------------------------------------------------------------- #

def test_kibitzer_scenario_checks_every_contract_truthfully(monkeypatch):
    original_temporary = qa.tempfile.TemporaryDirectory
    owned_roots = []

    def tracked_temporary(*args, **kwargs):
        directory = original_temporary(*args, **kwargs)
        owned_roots.append(Path(directory.name))
        return directory

    monkeypatch.setattr(qa.tempfile, "TemporaryDirectory", tracked_temporary)
    result = qa.kibitzer_scenario()
    observed = result["observed"]
    # Exact authored-note total and the support bound are both observed.
    assert observed["vault_notes"] == 160
    assert observed["supported_note_limit"] == qa._KIBITZER_SUPPORT == 1000
    # A description-only fallback, independently supported core tag and absent miss.
    assert observed["description_only_hit"] is True
    assert observed["description_only_core_misses"] is True
    assert observed["tag_only_core_hit"] is True
    assert observed["absent_no_hit"] is True
    # Root-system excluded while a nested reference/system note stays visible.
    assert observed["root_system_excluded"] is True
    assert observed["nested_searchable"] is True
    # Warm cached deletion and rename are discovered without force_refresh.
    assert observed["deleted_note_invisible"] is True
    assert observed["renamed_note_visible"] is True
    assert observed["stale_path_invisible"] is True
    assert observed["live_edit_visible"] is True
    # XML roundtrip, redaction, astral hit and the UTF-16 budget.
    assert observed["xml_roundtrip"] is True
    assert observed["astral_hint_accepted"] is True
    assert observed["overlong_hint_rejected"] is True
    assert observed["secret_redacted"] is True
    assert observed["astral_hit"] is True
    assert observed["excerpt_utf16_within_budget"] is True
    # Exact local midnight expiry seam, no sleep.
    assert observed["expiry_boundary"] is True
    assert observed["expired_note_invisible"] is True
    assert observed["future_note_visible"] is True
    # The temp root was owned and removed.
    assert len(owned_roots) == 1
    assert not owned_roots[0].exists()


def test_kibitzer_tag_only_regression_is_in_the_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin_mnemosyne.kibitzer import KibitzerAdapter, RecallCandidate

    original = KibitzerAdapter.select

    def omit_tag_hit(
        self: KibitzerAdapter, query: str, *, limit: int = 3,
        surfaced: Collection[str] = (), exclude_paths: Collection[str] = (),
        force_refresh: bool = False,
    ) -> tuple[RecallCandidate, ...]:
        return () if query == "tagsentinel" else original(
            self, query, limit=limit, surfaced=surfaced, exclude_paths=exclude_paths,
            force_refresh=force_refresh,
        )

    monkeypatch.setattr(KibitzerAdapter, "select", omit_tag_hit)
    result = qa.kibitzer_scenario()

    assert result["result"] == "LEGACY-FAIL"
    regressions = result["observed"]["ordering_regressions"]
    ordering = result["observed"]["ordering"]
    assert isinstance(regressions, list) and isinstance(ordering, list)
    assert "tagsentinel" in regressions
    tag_row, = [row for row in ordering
                if isinstance(row, dict) and row["query"] == "tagsentinel"]
    assert tag_row["actual"] == ["knowledge/tag-carrier.md"]
    assert tag_row["adapter"] == []
    assert tag_row["agrees"] is False


def test_kibitzer_ranking_regression_is_reported_not_hidden():
    # The historical adapter/core ranking disagreement is preserved as a
    # candidate-vs-actual comparison and reported truthfully: the scenario
    # still returns, and names every regressed query instead of asserting a
    # pass or crashing the CLI.
    result = qa.kibitzer_scenario()
    observed = result["observed"]
    ordering = observed["ordering"]
    assert isinstance(ordering, list)
    rows = [row for row in ordering if isinstance(row, dict)]
    assert len(rows) == len(ordering)
    assert result["result"] == (
        "LEGACY-FAIL" if observed["ordering_regressions"] else "LEGACY-PASS")
    assert observed["core_order_matches"] is (
        observed["ordering_regressions"] == [])
    regressed = [row["query"] for row in rows if not row["agrees"]]
    assert regressed == observed["ordering_regressions"]
    for row in rows:
        assert set(row) == {"query", "candidate", "adapter", "actual", "agrees"}


def test_kibitzer_scenario_refuses_a_count_below_the_fixed_floor():
    # A note count that cannot hold the authored seed/edge material has no
    # valid size; the scenario must refuse it rather than miscount a pass.
    with pytest.raises(qa.ProtocolError, match="below the"):
        qa.kibitzer_scenario(notes=10)


def test_iso_midnight_is_the_exact_local_instant():
    from datetime import datetime, timezone

    now = datetime(2026, 3, 1, 0, 30, tzinfo=timezone.utc).astimezone()
    midnight = qa._iso_midnight(now)
    assert midnight.date() == now.date()
    assert (midnight.hour, midnight.minute, midnight.second) == (0, 0, 0)
    assert midnight.tzinfo is not None
    assert qa._past_expiry(now) < now.date().isoformat()
