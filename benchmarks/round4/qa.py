# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# How to run (protocol checks, no product execution):
#   python benchmarks/round4/qa.py --check-practice --practice benchmarks/round4/practice.json
# How to run (public-API scenarios; requires the matching product surface):
#   python benchmarks/round4/qa.py --feature startup
#   python benchmarks/round4/qa.py --feature kibitzer
#   python benchmarks/round4/qa.py --feature consolidation [--semantic]
"""Round 4 public QA drivers, practice schema/provenance checks and pair accounting.

This module owns the round-4 practice protocol and the public-API scenarios that
verify the shipped product surfaces:

* :func:`check_practice` validates ``benchmarks/round4/practice.json`` for schema,
  per-author provenance, verbatim author identity, tuning/validation topic
  disjointness and nonempty positive/negative inventories. Tuning reports never
  expose validation bodies; only labels, counts and digests cross the boundary.
* :func:`startup_scenario` (QA-2), :func:`kibitzer_scenario` (QA-3) and
  :func:`questions_scenario` (QA-4) drive the real public APIs and report
  observed results. Scenarios for not-yet-implemented optional surfaces report a
  pending status with the exact reason; they never fake success and never crash.

Every scenario creates exactly one owned temporary root and asserts its absence
before returning. Nothing here reads frozen questions, gold or fixtures.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from itertools import combinations
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeGuard,
    TypeVar,
)

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


class _JsonDecoder(Protocol):
    def __call__(
        self, text: str, /, *,
        object_pairs_hook: Callable[
            [list[tuple[str, JsonValue]]], dict[str, JsonValue],
        ] | None = None,
    ) -> JsonValue: ...


_json: _JsonDecoder = json.loads

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if TYPE_CHECKING:
    from typing_extensions import override

    from birkin_mnemosyne.consolidation import Consolidation as _Consolidation
    from birkin_mnemosyne.memory import VaultMemory
    from birkin_mnemosyne.startup import StartupBundle, StartupReader
else:
    _Method = TypeVar("_Method", bound=Callable[..., object])

    def override(method: _Method) -> _Method:
        """Runtime stand-in for ``typing.override`` (Python 3.12+); marks nothing."""
        return method

_PRACTICE_DEFAULT = str(Path(__file__).resolve().parent / "practice.json")
THRESHOLDS_PATH = Path(__file__).resolve().parent / "detection-thresholds.json"

# The exact independent practice deliverable this protocol binds to. A practice
# file whose delivered Claude payload digests differently is a different set.
CLAUDE_PRACTICE_SHA256 = (
    "cd24ed0509428f2a9d2738102cdbdde91e3b7714da7186998ccca2b355350eac"
)
CLAUDE_AUTHOR = "anthropic-subscription/claude-opus-5-5"
SOL_AUTHOR = "chatgpt-subscription/gpt-6.1-sol"
SOURCE_PAIR_SHA256 = {
    SOL_AUTHOR: "8f710cebd2e87eb55262a1daf3aff1f0e8fe8b8e8492ab82c198fd3aa0b07b0a",
    CLAUDE_AUTHOR: "fdf0037925c8a8c0011d85c1641f118b6c73f707bd5681a2185467a70bc58ec0",
}
PARTITIONS = ("tuning", "validation")

# Optional semantic surfaces introduced by the product phase. Absence is observed
# at construction time and reported PENDING; support is driven, never faked.
SEMANTIC_CONSTRUCTOR_KEYWORDS = ("semantic", "thresholds")

# Tuning selection searches this grid; a locked choice cannot be validated on the
# data it was chosen from, so validation groups stay untouched during selection.
COSINE_GRID = tuple(round(0.50 + 0.01 * i, 2) for i in range(49))   # 0.50..0.98
MARGIN_GRID = tuple(round(0.00 + 0.01 * i, 2) for i in range(21))   # 0.00..0.20

# QA-4 required scenario sizes and public cap surfaces.
CROWDED_NEIGHBORHOOD_MIN = 32
REQUIRED_TRUE_PAIRS_MIN = 20
PUBLIC_QUESTION_CAP = 20
MCP_QUESTION_CAP = 100

# QA-2 reviewed closure and its expected complete coverage totals, all derived
# from the synthetic bytes below (never from a frozen fixture).
STARTUP_CLOSURE = ("MODE.md",)
STARTUP_FILES = 5
STARTUP_LINES = 62
STARTUP_BYTES = 2221
STARTUP_BLOCK_VERSION = 1


class ProtocolError(ValueError):
    """The practice protocol itself is malformed or misattributed."""


class _ValidatedAuthor(TypedDict):
    author: str
    positives: dict[str, int]
    negatives: dict[str, int]
    pairs: list[JsonValue]
    topic_groups: list[JsonValue]
    group_partition: dict[str, str]


class _ValidatedPractice(TypedDict):
    authors: list[_ValidatedAuthor]


class _AuthorCounts(TypedDict):
    author: str
    pairs: int
    topic_groups: int
    positives: dict[str, int]
    negatives: dict[str, int]
    pairs_digest: str


class _PracticeReport(TypedDict):
    feature: str
    result: str
    schema_version: JsonValue
    split: JsonValue
    authors: list[_AuthorCounts]
    claude_source_sha256: str


class _PairLabel(TypedDict):
    pair_id: str
    topic_group: str
    partition: str
    category: str
    related: bool


class _AuthorInventory(TypedDict):
    entries: dict[tuple[str, str], _PairLabel]
    positives: set[tuple[str, str]]
    negatives: set[tuple[str, str]]


class _PairCounts(TypedDict):
    tp: int
    fp: int
    fn: int
    abstained: int


class _TuningSelectionPlan(TypedDict):
    author: str
    tuning_topic_groups: list[str]
    validation_topic_groups: list[str]
    cosine_grid: list[float]
    margin_grid: list[float]
    selection_rule: str


class _TuningAuthorReport(TypedDict):
    author: str
    tuning_pairs: int
    tuning_pairs_digest: str
    outcomes: list[dict[str, JsonValue]]


class _TuningReport(TypedDict):
    feature: str
    authors: list[_TuningAuthorReport]


class _BlockedTuningAuthor(TypedDict):
    author: str
    tuning_pairs: int
    tuning_positives: int
    tuning_negatives: int
    tuning_topic_groups: list[str]


class _BlockedTuningReport(TypedDict):
    feature: str
    authors: list[_BlockedTuningAuthor]


class _StartupReportRequired(TypedDict):
    feature: str
    mode: str
    result: Literal["PASS", "LEGACY-PASS"]
    observed: dict[str, JsonValue]
    cleanup: str


class _StartupReport(_StartupReportRequired, total=False):
    note: str


class _KibitzerReport(TypedDict):
    feature: str
    mode: str
    result: Literal["LEGACY-FAIL", "LEGACY-PASS"]
    observed: dict[str, JsonValue]
    seed: list[_KibitzerSeed]
    cleanup: str
    note: str


class _PendingRequired(TypedDict):
    feature: str
    result: Literal["PENDING"]
    reason: str
    verified_at: str


class _PendingOptional(TypedDict, total=False):
    legacy_mode: str
    legacy_read_available: bool
    lexical_scenario_available: bool
    observed: _QuestionsObserved
    cleanup: str
    notes: int
    positives: int
    gold_pairs: int
    product_quality_claimed: bool
    semantic_status: str | None
    cleanup_absent: bool
    complete_limit: int
    cleanup_root: str


class _PendingExtra(_PendingOptional, total=False):
    feature: str
    result: Literal["PENDING"]
    reason: str
    verified_at: str


class _PendingReport(_PendingRequired, _PendingOptional):
    pass


class _InventoryEntry(TypedDict):
    first: int
    second: int
    related: bool
    category: str
    topic_group: str


class _CrowdedPlan(TypedDict):
    case: str
    notes: int
    gold_pairs: int
    distinct_notes: int
    exceeds_threshold: bool
    practice_max_pairs_in_topic: int
    practice_max_neighborhood_notes: int
    drivable: bool


class _CrowdedExtras(TypedDict):
    case: str
    exceeds_threshold: bool
    gold_inventory_complete: bool
    authored_positive_pairs: int
    authored_negative_pairs: int


class _MixedExtras(TypedDict):
    author: str
    scenario: str
    partition: str
    selected_pairs: list[str]
    selected_topic_groups: list[str]
    authored_inventory: list[_InventoryEntry]
    authored_positive_pairs: int
    authored_negative_pairs: int
    cross_topic_label: str


class _PairInventoryReport(TypedDict):
    feature: str
    result: str
    author: str
    unordered_pairs: int
    positive_pairs: int
    negative_pairs: int
    crowded_neighborhood: _CrowdedPlan
    crowded_gold_pairs: int
    crowded_notes: int
    meets_true_pair_minimum: bool
    meets_crowded_minimum: bool


class _KibitzerQuery(TypedDict):
    query: str
    expect: list[str]


# --------------------------------------------------------------------------- #
# Practice schema and provenance
# --------------------------------------------------------------------------- #

def load_practice(path: str | Path = _PRACTICE_DEFAULT) -> dict[str, JsonValue]:
    """Parse the practice protocol document, rejecting duplicate JSON members."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        document = _as_dict(
            _json(text, object_pairs_hook=_no_duplicate_members),
            "practice document must be an object",
        )
    except ProtocolError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"practice file is not valid JSON: {exc}") from exc
    validated = validate_practice(document)
    for item in validated["authors"]:
        canonical_pairs = json.dumps(item["pairs"], ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(canonical_pairs).hexdigest()
        _require(digest == SOURCE_PAIR_SHA256[item["author"]],
                 f"author-pairs-digest-drift: {item['author']}")
    return document


def _no_duplicate_members(
    members: list[tuple[str, JsonValue]],
) -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for name, member in members:
        if name in value:
            raise ProtocolError(f"duplicate JSON member: {name}")
        value[name] = member
    return value


def _require(condition: JsonValue, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _require_list(value: JsonValue, message: str) -> list[JsonValue]:
    """Return ``value`` as a list or fail the protocol check."""
    if isinstance(value, list) and value:
        return value
    raise ProtocolError(message)


def _as_dict(value: JsonValue, message: str) -> dict[str, JsonValue]:
    """Return ``value`` as an object or fail the protocol check."""
    if isinstance(value, dict):
        return value
    raise ProtocolError(message)


def _as_list(value: JsonValue, message: str) -> list[JsonValue]:
    """Return ``value`` as a (possibly empty) list or fail the protocol check."""
    if isinstance(value, list):
        return value
    raise ProtocolError(message)


def _str_field(record: Mapping[str, JsonValue], key: str) -> str:
    value = record[key]
    assert isinstance(value, str)
    return value


def _int_field(record: Mapping[str, JsonValue], key: str) -> int:
    value = record[key]
    assert isinstance(value, int)
    return value


def _note_key(note: Mapping[str, JsonValue]) -> str:
    """Canonical ``title\\x1fbody`` key for one authored note."""
    return f"{note['title']}\x1f{note['body']}"


def _ordered_key(pair: Mapping[str, JsonValue]) -> tuple[str, str]:
    """Canonical unordered key for one authored pair (two notes)."""
    first, second = order_key_of(pair)
    return (first, second) if first <= second else (second, first)


def _canonical_sha256(value: JsonValue | list[str]) -> str:
    """Content digest that ignores insignificant JSON formatting only."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_author(author: dict[str, JsonValue]) -> _ValidatedAuthor:
    name = author.get("author")
    _require(isinstance(name, str) and name.strip(),
             "author identity must be a nonempty string")
    assert isinstance(name, str)
    _require(author.get("license") == "CC0-1.0", f"{name}: license must be CC0-1.0")
    _require(author.get("source_blind") not in (None, False, "", []),
             f"{name}: source-blind provenance is missing or false")
    groups = _require_list(author.get("topic_groups"),
                           f"{name}: topic_groups must be a nonempty list")
    group_ids: list[str] = []
    by_id: dict[str, str] = {}
    for raw_group in groups:
        group = _as_dict(raw_group, f"{name}: every topic group must be an object")
        gid = group.get("id")
        _require(isinstance(gid, str) and gid,
                 f"{name}: topic group id must be a nonempty string")
        assert isinstance(gid, str)
        partition = group.get("partition")
        _require(partition in PARTITIONS,
                 f"{name}/{gid}: partition must be tuning or validation")
        assert isinstance(partition, str)
        group_ids.append(gid)
        by_id[gid] = partition
    _require(len(set(group_ids)) == len(group_ids), f"{name}: duplicate topic group ids")

    pairs = _require_list(author.get("pairs"), f"{name}: pairs must be a nonempty list")
    seen_ids: set[str] = set()
    pos: dict[str, int] = dict.fromkeys(PARTITIONS, 0)
    neg: dict[str, int] = dict.fromkeys(PARTITIONS, 0)
    for raw_pair in pairs:
        pair = _as_dict(raw_pair, f"{name}: every pair must be an object")
        pid = pair.get("id")
        _require(isinstance(pid, str) and pid, f"{name}: pair id must be a nonempty string")
        assert isinstance(pid, str)
        _require(pid not in seen_ids, f"{name}: duplicate pair id {pid!r}")
        seen_ids.add(pid)
        partition = pair.get("partition")
        _require(partition in PARTITIONS,
                 f"{name}/{pid}: partition must be tuning or validation")
        assert partition in PARTITIONS
        assert isinstance(partition, str)
        topic = pair.get("topic_group")
        _require(isinstance(topic, str) and topic, f"{name}/{pid}: topic_group is required")
        assert isinstance(topic, str)
        _require(topic in by_id, f"{name}/{pid}: topic_group {topic!r} is not declared")
        _require(by_id[topic] == partition,
                 f"{name}/{pid}: pair partition disagrees with its topic group")
        related = pair.get("related")
        _require(isinstance(related, bool), f"{name}/{pid}: related must be a boolean")
        category = pair.get("category")
        _require(isinstance(category, str) and category,
                 f"{name}/{pid}: category is required")
        notes = pair.get("notes")
        _require(isinstance(notes, list) and len(notes) == 2,
                 f"{name}/{pid}: each pair requires exactly two notes")
        assert isinstance(notes, list)
        for raw_note in notes:
            note = _as_dict(raw_note, f"{name}/{pid}: every note must be an object")
            title = note.get("title")
            body = note.get("body")
            _require(isinstance(title, str) and title.strip(),
                     f"{name}/{pid}: note title must be a nonempty string")
            _require(isinstance(body, str) and body.strip(),
                     f"{name}/{pid}: note body must be a nonempty string")
        if related:
            pos[partition] += 1
        else:
            neg[partition] += 1
    for partition in PARTITIONS:
        _require(pos[partition] > 0, f"{name}:{partition}: no positive pairs")
        _require(neg[partition] > 0, f"{name}:{partition}: no negative pairs")
    return {"author": name, "positives": pos, "negatives": neg,
            "pairs": pairs, "topic_groups": groups, "group_partition": by_id}


def validate_practice(document: dict[str, JsonValue]) -> _ValidatedPractice:
    """Validate schema, provenance, author identity and topic disjointness."""
    _require(document.get("schema_version") == 1, "unsupported practice schema_version")
    _require(document.get("split") == "practice",
             "this protocol only covers practice data, not a held-out set")
    _require(document.get("license") == "CC0-1.0", "practice license must be CC0-1.0")
    authors = _require_list(document.get("authors"), "authors must be a nonempty list")
    validated = [_validate_author(_as_dict(author, "every author must be an object"))
                 for author in authors]
    names = [item["author"] for item in validated]
    _require(len(set(names)) == len(names), "author identities must be unique")

    # Tuning/validation topic groups never cross partitions within one author.
    for item in validated:
        tuning: set[str] = set()
        validation: set[str] = set()
        for raw_pair in item["pairs"]:
            pair = _as_dict(raw_pair, f"{item['author']}: every pair must be an object")
            topic = pair["topic_group"]
            assert isinstance(topic, str)
            if pair["partition"] == "tuning":
                tuning.add(topic)
            if pair["partition"] == "validation":
                validation.add(topic)
        _require(not (tuning & validation),
                 f"{item['author']}: tuning and validation topic groups overlap")

    # Real author identity must match the delivered source-blind practice. Absent
    # or misattributed author material fails closed; it is never fabricated.
    claude = _find_author(validated, CLAUDE_AUTHOR)
    _require(claude is not None, f"required independent author {CLAUDE_AUTHOR!r} is absent")
    claimed = _find_author_entry(document, CLAUDE_AUTHOR).get("source_sha256")
    _require(claimed == CLAUDE_PRACTICE_SHA256,
             f"{CLAUDE_AUTHOR}: practice payload does not match the delivered "
             + f"source digest {CLAUDE_PRACTICE_SHA256}")
    sol = _find_author(validated, SOL_AUTHOR)
    _require(sol is not None, f"required main author {SOL_AUTHOR!r} is absent")
    sol_note = str(_find_author_entry(document, SOL_AUTHOR).get("authoring", ""))
    _require("not held-out" in sol_note or "practice" in sol_note,
             f"{SOL_AUTHOR}: provenance must state this is practice, not held-out")
    return {"authors": validated}


def _find_author(
    validated: Sequence[_ValidatedAuthor], name: str,
) -> _ValidatedAuthor | None:
    return next((item for item in validated if item["author"] == name), None)


def _find_author_entry(
    document: Mapping[str, JsonValue], name: str,
) -> dict[str, JsonValue]:
    authors = document.get("authors")
    if not isinstance(authors, list):
        return {}
    for entry in authors:
        if isinstance(entry, dict) and entry.get("author") == name:
            return entry
    return {}


def check_practice(path: str | Path = _PRACTICE_DEFAULT) -> _PracticeReport:
    """CLI-visible schema/provenance summary: aggregate counts and digests only."""
    document = load_practice(path)
    validated = validate_practice(document)
    authors: list[_AuthorCounts] = [{
        "author": item["author"],
        "pairs": len(item["pairs"]),
        "topic_groups": len(item["topic_groups"]),
        "positives": dict(item["positives"]),
        "negatives": dict(item["negatives"]),
        "pairs_digest": _canonical_sha256(item["pairs"]),
    } for item in validated["authors"]]
    return {
        "feature": "practice-protocol",
        "result": "PASS",
        "schema_version": document["schema_version"],
        "split": document["split"],
        "authors": authors,
        "claude_source_sha256": CLAUDE_PRACTICE_SHA256,
    }


# --------------------------------------------------------------------------- #
# Topic groups, pair inventories and tuning reports (pure protocol functions)
# --------------------------------------------------------------------------- #

def topic_partitions(document: dict[str, JsonValue], author: str) -> dict[str, str]:
    """Return topic_group -> partition for one author, enforcing disjointness."""
    item = _require_author(document, author)
    mapping: dict[str, str] = {}
    for raw_pair in item["pairs"]:
        pair = _as_dict(raw_pair, f"{author}: every pair must be an object")
        topic = pair["topic_group"]
        partition = pair["partition"]
        assert isinstance(topic, str)
        assert isinstance(partition, str)
        _ = mapping.setdefault(topic, partition)
    return mapping


def author_pairs(
    document: dict[str, JsonValue], author: str,
) -> tuple[dict[str, JsonValue], ...]:
    """All authored practice pairs for one author, in file order."""
    return tuple(
        _as_dict(pair, f"{author}: every pair must be an object")
        for pair in _require_author(document, author)["pairs"]
    )


def _require_author(document: dict[str, JsonValue], author: str) -> _ValidatedAuthor:
    item = _find_author(validate_practice(document)["authors"], author)
    if item is None:
        raise ProtocolError(f"unknown author {author!r}")
    return _ValidatedAuthor(item)


def tuning_selection_plan(
    document: dict[str, JsonValue], author: str,
) -> _TuningSelectionPlan:
    """Calibration metadata for one author.

    Validation bodies and labels are deliberately excluded: the selection grid is
    fixed and only tuning topic-group ids leave this function.
    """
    mapping = topic_partitions(document, author)
    tuning = sorted(topic for topic, part in mapping.items() if part == "tuning")
    validation = sorted(topic for topic, part in mapping.items() if part == "validation")
    return {
        "author": author,
        "tuning_topic_groups": tuning,
        "validation_topic_groups": validation,
        "cosine_grid": list(COSINE_GRID),
        "margin_grid": list(MARGIN_GRID),
        "selection_rule": (
            "zero false positives per author on tuning, then maximal minimum-author "
            "complete recall, then larger cosine, then larger margin"
        ),
    }


def tuning_report(
    document: dict[str, JsonValue],
    results: Mapping[str, Iterable[dict[str, JsonValue]]],
) -> _TuningReport:
    """Tuning-side report that cannot leak validation rows.

    ``results`` maps author -> tuning-outcome rows. The report emits tuning pair
    ids, labels and counts only: it never copies note bodies and rejects any row
    that references a validation pair or carries note text.
    """
    validated = validate_practice(document)
    report: _TuningReport = {"feature": "tuning-report", "authors": []}
    for item in validated["authors"]:
        author = item["author"]
        tuning_ids: set[str] = set()
        for raw_pair in item["pairs"]:
            pair = _as_dict(raw_pair, f"{author}: every pair must be an object")
            if pair["partition"] == "tuning":
                pid = pair["id"]
                assert isinstance(pid, str)
                tuning_ids.add(pid)
        rows = list(results.get(author, ()))
        for row in rows:
            pid = row.get("id")
            if not isinstance(pid, str) or pid not in tuning_ids:
                raise ProtocolError(
                    f"{author}: tuning report references non-tuning pair {pid!r}")
            if "body" in row or "notes" in row:
                raise ProtocolError(f"{author}/{pid}: tuning report must not carry note text")
        report["authors"].append({
            "author": author,
            "tuning_pairs": len(tuning_ids),
            "tuning_pairs_digest": _canonical_sha256(sorted(tuning_ids)),
            "outcomes": rows,
        })
    return report


def blocked_tuning_report(document: dict[str, JsonValue]) -> _BlockedTuningReport:
    """Structural tuning report used before any product detection exists."""
    validated = validate_practice(document)
    summary: list[_BlockedTuningAuthor] = []
    for item in validated["authors"]:
        tuning: list[dict[str, JsonValue]] = []
        topics: set[str] = set()
        for raw_pair in item["pairs"]:
            pair = _as_dict(raw_pair, f"{item['author']}: every pair must be an object")
            if pair["partition"] == "tuning":
                tuning.append(pair)
                topic = pair["topic_group"]
                assert isinstance(topic, str)
                topics.add(topic)
        summary.append({
            "author": item["author"],
            "tuning_pairs": len(tuning),
            "tuning_positives": sum(1 for p in tuning if p["related"]),
            "tuning_negatives": sum(1 for p in tuning if not p["related"]),
            "tuning_topic_groups": sorted(topics),
        })
    return {"feature": "tuning-report", "authors": summary}


LITERAL_SPREAD = 5


def order_key_of(pair: Mapping[str, JsonValue]) -> tuple[str, str]:
    """First authored note key, then second — the case's own orientation."""
    notes = pair["notes"]
    assert isinstance(notes, list)
    first = _as_dict(notes[0], "every authored note must be an object")
    second = _as_dict(notes[1], "every authored note must be an object")
    return _note_key(first), _note_key(second)


def _pair_label(pair: Mapping[str, JsonValue]) -> _PairLabel:
    """Retain the label fields already checked by the practice validator."""
    pid = pair["id"]
    topic = pair["topic_group"]
    partition = pair["partition"]
    category = pair["category"]
    related = pair["related"]
    assert isinstance(pid, str)
    assert isinstance(topic, str)
    assert isinstance(partition, str)
    assert isinstance(category, str)
    assert isinstance(related, bool)
    return {
        "pair_id": pid, "topic_group": topic, "partition": partition,
        "category": category, "related": related,
    }


def ordered_pair_inventory(document: dict[str, JsonValue], author: str) -> _AuthorInventory:
    """Every unordered note pair of one author, keyed canonically and label-tagged.

    The inventory is derived from the authored labels alone. It is never used to
    score a run: the driver counts matches from the product's own offered pairs
    and only reads this to decide whether an offered pair was true or false.
    """
    entries: dict[tuple[str, str], _PairLabel] = {}
    positives: set[tuple[str, str]] = set()
    negatives: set[tuple[str, str]] = set()
    for pair in author_pairs(document, author):
        key = _ordered_key(pair)
        _require(key not in entries, f"{author}: duplicate unordered note pair")
        label = _pair_label(pair)
        entries[key] = label
        (positives if label["related"] else negatives).add(key)
    return {"entries": entries, "positives": positives, "negatives": negatives}


def count_offered(
    inventory: _AuthorInventory, observed: Sequence[tuple[str, str]],
) -> _PairCounts:
    """Count TP/FP/FN against the authored labels from a product's own offered pairs.

    ``observed`` holds the pairs the product actually surfaced in its own
    orientation; each entry is an ordered note-key pair. Ground truth is never
    used to fabricate an offered pair, so a product that offers nothing scores
    zero true positives and one false negative per authored positive.
    """
    entries = inventory["entries"]
    positives = inventory["positives"]
    seen: set[tuple[str, str]] = set()
    tp = fp = 0
    for first, second in observed:
        key = (first, second) if (first, second) in entries else (second, first)
        if key in seen:
            continue
        seen.add(key)
        entry = entries.get(key)
        if entry is None:
            raise ProtocolError("offered pair is not in the authored inventory")
        if entry["related"]:
            tp += 1
        else:
            fp += 1
    fn = len(positives - seen)
    return {"tp": tp, "fp": fp, "fn": fn, "abstained": fn}


def unordered_pair_inventory(
    document: dict[str, JsonValue],
) -> dict[str, dict[tuple[str, str], _PairLabel]]:
    """Every unordered note pair per author, labeled related/negative and partition.

    The inventory is independent of any product: it is derived from the authored
    labels, keyed by the two note texts in canonical (sorted) order.
    """
    validated = validate_practice(document)
    inventory: dict[str, dict[tuple[str, str], _PairLabel]] = {}
    for item in validated["authors"]:
        author = item["author"]
        entries: dict[tuple[str, str], _PairLabel] = {}
        for raw_pair in item["pairs"]:
            pair = _as_dict(raw_pair, f"{author}: every pair must be an object")
            key = _ordered_key(pair)
            _require(key not in entries,
                     f"{author}: duplicate unordered note pair {pair['id']!r}")
            entries[key] = _pair_label(pair)
        inventory[author] = entries
    return inventory


def pair_accounting(document: dict[str, JsonValue], author: str,
                    offered: Iterable[tuple[str, str]],
                    *, scope: Iterable[tuple[str, str]] | None = None) -> _PairCounts:
    """Count TP/FP/FN for offered pairs against the authored labels.

    ``offered`` yields note-key pairs (``title\\x1fbody``) in any order. A related
    pair the product never offers is a false negative (also an abstention); an
    offered unrelated pair is a false positive. Offered pairs must belong to the
    authored inventory, else the driver refuses to score. ``scope`` restricts the
    positive denominator to a subset of the inventory (for example one topic
    vault); without it every authored pair is in scope.
    """
    inventory = unordered_pair_inventory(document)
    if author not in inventory:
        raise ProtocolError(f"unknown author {author!r}")
    known = inventory[author]
    in_scope = set(scope) if scope is not None else set(known)
    _require(in_scope <= set(known),
             f"{author}: accounting scope contains unknown pairs")
    positives = {key for key in in_scope if known[key]["related"]}
    seen: set[tuple[str, str]] = set()
    tp = fp = 0
    for first, second in offered:
        key = (first, second) if (first, second) in known else (second, first)
        if key in seen:
            continue
        seen.add(key)
        entry = known.get(key)
        if entry is None:
            raise ProtocolError(f"{author}: offered pair is not in the authored inventory")
        if entry["related"]:
            tp += 1
        else:
            fp += 1
    fn = len(positives - seen)
    return {"tp": tp, "fp": fp, "fn": fn, "abstained": fn}


# --------------------------------------------------------------------------- #
# Synthetic inputs built at runtime (no frozen fixture rows)
# --------------------------------------------------------------------------- #

def synthetic_notes(count: int, *, seed_text: str = "practice") -> list[dict[str, str]]:
    """Deterministic distinct notes for the scale scenarios.

    The text is generated here, never read from frozen files or practice rows.
    """
    if count < 1:
        raise ProtocolError("note count must be positive")
    return [{
        "title": f"{seed_text} unit {index:04d}",
        "body": (
            f"{seed_text} unit {index:04d} handles task {index:04d} with "
            f"reference code {index * 7 + 11} and cycle {index % 5}."
        ),
    } for index in range(count)]


def edge_mutation_notes() -> list[dict[str, str]]:
    """Boundary material for QA-3 (CRLF/BOM/empty/final-line/astral/secret)."""
    return [
        {"title": "Edge CRLF", "body": "Edge line one.\r\nEdge line two.\r\n"},
        {"title": "Edge BOM", "body": "\ufeffEdge document with a leading byte-order mark."},
        {"title": "Edge empty", "body": "Empty body placeholder for the edge suite."},
        {"title": "Edge final line", "body": "No trailing newline at the end"},
        {"title": "Edge astral", "body": "Astral symbols: \U0001f600 \U0001f680 \U0001f9e0."},
        {"title": "Edge secret", "body": "Credential placeholder token=REDACTED-VALUE-0001."},
    ]


def synthetic_startup_files() -> dict[str, str]:
    """Synthetic startup root for QA-2 with BOM, fenced/cyclic/date/supersede cases.

    Nothing here is read from a frozen fixture: every byte is generated below.
    ``STARTUP_{FILES,LINES,BYTES}`` are the exact complete-closure totals of the
    closure declared below and are asserted by the scenario.
    """
    return {
        "MODE.md": (
            "\ufeff# Boot\nMUST READ: handoff.md\nMUST READ: profile/soul.md\n"
            + "MUST READ: registry.json\n"
            + "<fence>MUST READ: ignored-inside-fence.md</fence>\n"
            + "```\nMUST READ: also-ignored-inside-fence.md\n```\n"
            + "".join(
                f"Rule {i} retains evidence for operation {i}.\n" for i in range(40)
                if i != 7)
            + "Rule 7 keeps a final source line with no trailing newline"
        ),   # 2221 bytes / 62 lines with the four files below (asserted, not assumed)
        "handoff.md": (
            "TOP NOTE 2026-09-01\nPort: 4100\n"
            "TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: 4200\n"
            "TOP NOTE 2026-11-01T08:30:00Z\nPort: 4300\n"
        ),
        "profile/soul.md": "# Soul\nMUST READ: human.md\nMUST READ: soul.md\nVoice: direct\n",
        "profile/human.md": "# Human\nApproval: publication needs granted consent\n",
        "registry.json": '{"must_read":[],"jobs":[{"state":"active","pending":"capture CI receipt"}]}\n',
    }


# --------------------------------------------------------------------------- #
# QA-2 independent presentation oracle (natural parser, never the candidate)
# --------------------------------------------------------------------------- #
# This oracle re-derives the reviewed legacy TOP NOTE presentation semantics
# directly from raw source bytes. It deliberately does NOT call the candidate's
# ``read``/``verify``/``_blocks`` or any shared candidate parsing helper: a
# candidate that grades itself can only prove self-consistency, not parity with
# the independent legacy contract. The oracle is the QA authority for QA-2's
# ``order[]`` comparison, so an always-successful candidate verifier that
# advertises a wrong ``order[]`` cannot be reported PASS.

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.+?)|[ \t]*)$")
_SETEXT = re.compile(r" {0,3}(=+|-+)[ \t]*$")
_BARE_NOTE = re.compile(r"^ {0,3}TOP NOTE\b", re.IGNORECASE)
_NOTE_STAMP = re.compile(
    r"(?<!\w)(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?Z)?)(?![\w:+-])")
_MUST_READ = re.compile(r" {0,3}(?:-\s*)?MUST READ:\s*(.*?)\s*$", re.IGNORECASE)


def _natural_offsets(data: bytes) -> tuple[list[str], list[int]]:
    """Split ``data`` into keepends lines and their cumulative byte offsets.

    Natural bytes: a UTF-8 BOM is a real leading byte and only the first line's
    syntax view drops it; bare CR is not treated as a line break.
    """
    text = data.decode("utf-8")
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    return lines, offsets


def _natural_references(text: str) -> tuple[str, ...]:
    """Outside-fence literal ``MUST READ`` declarations from raw text bytes.

    Independent of the candidate's closure walk: fenced declarations are ignored
    and a JSON file declares its own ``must_read`` array. No candidate import or
    helper is consulted.
    """
    stripped = text.removeprefix("\ufeff")
    if stripped.lstrip().startswith("{"):
        try:
            value = _json(stripped, object_pairs_hook=_no_duplicate_members)
        except (ValueError, ProtocolError):
            return ()
        if isinstance(value, dict):
            must_read = value.get("must_read")
            if isinstance(must_read, list):
                return tuple(str(ref) for ref in must_read)
        return ()
    refs: list[str] = []
    fence, width = "", 0
    for line in stripped.splitlines():
        marker = _FENCE_OPEN.match(line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            continue
        if fence:
            continue
        match = _MUST_READ.fullmatch(line)
        if match:
            reference = match.group(1).strip("`\"'")
            if reference:
                refs.append(reference)
    return tuple(refs)


def _natural_closure(root: Path, paths: Sequence[str],
                     ) -> dict[str, bytes]:
    """Walk ``paths`` and their declarations with the natural parser only."""
    base = root.resolve()
    pending = [base / path for path in paths]
    sources: dict[str, bytes] = {}
    while pending:
        resolved = pending.pop(0).resolve()
        if not resolved.is_relative_to(base):
            raise ProtocolError("oracle closure escaped the configured root")
        relative = resolved.relative_to(base).as_posix()
        if relative in sources:
            continue
        data = resolved.read_bytes()
        sources[relative] = data
        for reference in _natural_references(data.decode("utf-8")):
            pending.append(resolved.parent / reference)
    return sources


def _natural_sections(data: bytes) -> list[tuple[int, int, str, int]]:
    """Natural heading spans ``(firstLine, endLineExclusive, heading, level)``.

    Reimplements the reviewed recognition rules from raw bytes: an optional
    leading frontmatter block, fenced code exclusion, ATX headings, setext
    headings, and bare startup ``TOP NOTE`` labels acting as level-2 headings.
    """
    lines, _ = _natural_offsets(data)
    syntax = list(lines)
    if syntax:
        syntax[0] = syntax[0].removeprefix("\ufeff")
    start = 0
    if syntax and syntax[0].strip() == "---":
        close = next((i for i in range(1, len(lines))
                      if lines[i].strip() == "---"), None)
        if close is not None:
            start = close + 1
    headings: list[tuple[int, int, str]] = []
    fence, width = "", 0
    i = start
    while i < len(lines):
        line = syntax[i].rstrip("\r\n")
        marker = _FENCE_OPEN.match(line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            i += 1
            continue
        if fence:
            i += 1
            continue
        atx = _ATX.match(line)
        if atx:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", atx.group(2) or "")
            headings.append((i, len(atx.group(1)), title))
        elif _BARE_NOTE.match(line):
            headings.append((i, 2, line.strip()))
        elif i + 1 < len(lines) and line.strip():
            underline = _SETEXT.fullmatch(lines[i + 1].rstrip("\r\n"))
            if underline:
                headings.append(
                    (i, 1 if underline.group(1)[0] == "=" else 2, line.strip()))
                i += 1
        i += 1
    if not headings or headings[0][0] > start:
        headings.insert(0, (start, 0, "Preamble"))
    spans: list[tuple[int, int, str, int]] = []
    for position, (begin, level, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        if not "".join(lines[begin:end]).strip():
            continue
        spans.append((begin, end, heading, level))
    return spans


class _NoteSpan(TypedDict):
    begin: int
    end: int
    heading: str
    level: int


class _NoteUnit(TypedDict):
    begin: int
    end: int
    heading: str
    level: int
    path: str | None
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    text: str
    state: str


class _NoteGroup(TypedDict):
    start: int
    end: int
    state: str
    starts: list[int]


class _OrderOverrideBase(TypedDict):
    path: str


class _OrderOverride(_OrderOverrideBase, total=False):
    reorder: list[list[int]]
    superseded: list[int]


def _natural_note_units(data: bytes) -> list[_NoteUnit]:
    """Natural per-file block records carrying raw source spans and state.

    Each record holds the natural ``start_byte``/``end_byte``/``start_line``/
    ``end_line``/``heading``/``state`` and the raw ``text`` of one contiguous
    source span. Files with no recognized TOP NOTE return their plain spans with
    state ``source`` so a non-note file cannot fabricate an override.
    """
    _, offsets = _natural_offsets(data)
    spans = _natural_sections(data)
    partial: list[_NoteSpan] = []
    cursor = 0
    for begin, end, heading, _level in spans:
        if begin > cursor:
            partial.append({"begin": cursor, "end": begin, "heading": "Source preamble",
                            "level": 0})
        partial.append({"begin": begin, "end": end, "heading": heading,
                        "level": _level})
        cursor = end
    if cursor < len(offsets) - 1 or not partial:
        partial.append({"begin": cursor, "end": len(offsets) - 1,
                        "heading": "Source remainder", "level": 0})
    records: list[_NoteUnit] = []
    for span in partial:
        start_byte, end_byte = offsets[span["begin"]], offsets[span["end"]]
        records.append({
            "begin": span["begin"], "end": span["end"],
            "heading": span["heading"], "level": span["level"],
            "path": None,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "start_line": span["begin"] + 1 if data else 0,
            "end_line": span["end"],
            "text": data[start_byte:end_byte].decode("utf-8"),
            "state": "source",
        })
    return records


def _natural_active_lines(text: str) -> list[str]:
    """Outside-fence lines of ``text`` for supersession declarations."""
    result: list[str] = []
    fence, width = "", 0
    for line in text.removeprefix("\ufeff").splitlines():
        marker = _FENCE_OPEN.match(line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            continue
        if not fence:
            result.append(line)
    return result


def _natural_expected(sources: Mapping[str, bytes]) -> list[_NoteUnit]:
    """Independently expected ordered presentation: ``(path, start_byte, ...)``.

    Applies the reviewed legacy TOP NOTE semantics to the natural spans: groups
    are a ``TOP NOTE`` heading plus its deeper descendants; a changed contiguous
    run keeps the natural order unless every group in it has a distinct stamp of
    one identical precision, in which case the run sorts descending; a group
    whose heading a ``Supersedes:`` line names becomes ``explicitly-superseded``.
    No automatic date sort or state repair is invented beyond this contract.
    """
    ordered: list[_NoteUnit] = []
    for path, data in sources.items():
        records = _natural_note_units(data)
        for record in records:
            record["path"] = path
        groups: list[list[_NoteUnit]] = []
        units: list[tuple[bool, list[_NoteUnit]]] = []
        note_level: int | None = None
        for record in records:
            if record["heading"].upper().startswith("TOP NOTE"):
                groups.append([record])
                units.append((True, groups[-1]))
                note_level = record["level"]
            elif note_level is not None and record["level"] > note_level:
                groups[-1].append(record)
            else:
                units.append((False, [record]))
                note_level = None
        if groups:
            dates: list[datetime | None] = []
            precisions: set[int] = set()
            for group in groups:
                stamp = _NOTE_STAMP.search(group[0]["heading"])
                value = stamp.group(1) if stamp else ""
                parsed: datetime | None = None
                if value:
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                    precisions.add(len(value))
                dates.append(parsed)
            if all(date is not None for date in dates) and \
                    len(set(dates)) == len(dates) and len(precisions) == 1:
                stamps = {group[0]["start_byte"]: date
                          for group, date in zip(groups, dates) if date is not None}
                begin = 0
                while begin < len(units):
                    if not units[begin][0]:
                        begin += 1
                        continue
                    end = begin + 1
                    while end < len(units) and units[end][0]:
                        end += 1
                    units[begin:end] = sorted(
                        units[begin:end],
                        key=lambda unit: stamps[unit[1][0]["start_byte"]],
                        reverse=True)
                    begin = end
            superseded = {
                line.partition(":")[2].strip().casefold()
                for group in groups for record in group
                for line in _natural_active_lines(record["text"])
                if line.strip().casefold().startswith("supersedes:")
            }
            for group in groups:
                if group[0]["heading"].casefold() in superseded:
                    for record in group:
                        record["state"] = "explicitly-superseded"
        ordered.extend(record for _is_note, unit in units for record in unit)
    return ordered


def _natural_note_groups(data: bytes) -> list[_NoteGroup]:
    """Natural TOP NOTE groups for one file, each with a stable identity.

    A group is one ``TOP NOTE`` record plus its deeper descendants. Its identity
    is the group's smallest natural start byte, stable under reordering, and its
    state is its leading record's derived state.
    """
    units = _natural_note_units(data)
    groups: list[_NoteGroup] = []
    current: _NoteGroup | None = None
    note_level: int | None = None
    for item in units:
        if item["heading"].upper().startswith("TOP NOTE"):
            current = {"start": item["start_byte"], "end": item["end_byte"],
                       "state": item["state"],
                       "starts": [item["start_byte"]]}
            groups.append(current)
            note_level = item["level"]
        elif note_level is not None and item["level"] > note_level and current is not None:
            current["starts"].append(item["start_byte"])
            current["end"] = item["end_byte"]
        else:
            current = None
            note_level = None
    return groups


def _natural_order_overrides(sources: Mapping[str, bytes],
                             ) -> tuple[list[_OrderOverride], list[_NoteUnit]]:
    """Minimal canonical v2 overrides derived from the natural presentation.

    Returns ``(order, expected_ordered)``. ``order`` holds one record per
    affected file in source-closure order and omits absent effects and
    unaffected files; ``reorder`` lists only the target permutation of each
    changed contiguous TOP NOTE run after trimming the equal prefix/suffix
    against the natural order, and ``superseded`` lists superseded group starts
    in byte order. Empty optional arrays are omitted. The derived override for
    the current synthetic fixture is ``superseded`` only (mixed precision, so no
    automatic date sort); the homogeneous fixture adds a ``reorder`` array.
    """
    expected = _natural_expected(sources)
    order: list[_OrderOverride] = []
    for path, data in sources.items():
        natural_groups = _natural_note_groups(data)
        natural_order = [group["start"] for group in natural_groups]
        target_order = [group["start"] for group in _expected_groups(
            path, expected, natural_groups)]
        reorder_groups: list[list[int]] = []
        begin = 0
        while begin < len(natural_groups):
            end = begin + 1
            while end < len(natural_groups) and \
                    natural_groups[end - 1]["end"] == natural_groups[end]["start"]:
                end += 1
            run = natural_order[begin:end]
            reorder_groups.extend(_reorder_group_starts(
                run, [start for start in target_order if start in run]))
            begin = end
        # A group is superseded when the independent expected semantics mark its
        # leading record; the natural pass deliberately derives no state itself.
        superseded_groups = [group["start"] for group in natural_groups
                             if _expected_group_state(path, expected, group)
                             == "explicitly-superseded"]
        record_out: _OrderOverride = {"path": path}
        if reorder_groups:
            record_out["reorder"] = reorder_groups
        if superseded_groups:
            record_out["superseded"] = sorted(superseded_groups)
        if len(record_out) > 1:
            order.append(record_out)
    return order, expected


def _expected_groups(path: str, expected: Sequence[_NoteUnit],
                     natural_groups: Sequence[_NoteGroup],
                     ) -> list[_NoteGroup]:
    """Map expected per-file records back to their natural group identities.

    Each group identity is recovered by matching an expected ``TOP NOTE`` record
    to the natural group whose note start equals a member start.
    """
    identity_of: dict[int, _NoteGroup] = {}
    for group in natural_groups:
        for start in group["starts"]:
            identity_of[start] = group
    seen: list[_NoteGroup] = []
    for record in expected:
        if record["path"] != path:
            continue
        group = identity_of.get(record["start_byte"])
        if group is not None and (not seen or seen[-1] is not group):
            seen.append(group)
    return seen


def _expected_group_state(path: str, expected: Sequence[_NoteUnit],
                          group: _NoteGroup) -> str:
    """Independent expected state of one natural group's leading record."""
    starts = set(group["starts"])
    for record in expected:
        if record["path"] == path and record["start_byte"] in starts:
            return str(record["state"])
    return "source"


def _reorder_group_starts(natural_order: Sequence[int],
                          target_order: Sequence[int],
                          ) -> list[list[int]]:
    """Changed contiguous TOP NOTE runs as target group-start permutations.

    Equal prefix/suffix group starts are trimmed, and the remaining target order
    is emitted only when it differs from the natural order. An unchanged run or
    a run with a single group yields no reorder array.
    """
    natural = list(natural_order)
    target = list(target_order)
    prefix = 0
    while (prefix < len(natural) and prefix < len(target)
           and natural[prefix] == target[prefix]):
        prefix += 1
    suffix = 0
    while (suffix < len(natural) - prefix and suffix < len(target) - prefix
           and natural[-1 - suffix] == target[-1 - suffix]):
        suffix += 1
    remaining = target[prefix:len(target) - suffix]
    if len(remaining) <= 1 or remaining == natural[prefix:len(natural) - suffix]:
        return []
    return [list(remaining)]


class _ParsedContext(TypedDict):
    files: dict[str, bytes]
    order: list[_OrderOverride]
    expected: list[_NoteUnit]


_OrderKey: TypeAlias = tuple[str | None, int, int, int, str, str]


class _OrderVerdict(TypedDict):
    match: bool
    advertised: list[_OrderKey]
    expected: list[_OrderKey]


def _natural_parse_context(context: str, sources: Mapping[str, bytes],
                           ) -> _ParsedContext:
    """Validate a compact v2 context independently and recover its advertised order.

    The oracle never trusts the candidate's verifier. It parses the JSON with
    duplicate-key rejection (including escaped-name collisions), requires exactly
    ``version: 2`` (bools are rejected), exact file keys ``{path,text}`` with raw
    UTF-8 source bytes and closure order, then validates each ``order`` record's
    ``path``/``reorder``/``superseded`` shape before any dict construction.
    """
    parsed = _json(context, object_pairs_hook=_no_duplicate_members)
    if not isinstance(parsed, dict):
        raise ProtocolError("compact context is not a JSON object")
    if set(parsed) != {"version", "files", "order"}:
        raise ProtocolError("compact context has unexpected top-level keys")
    version = parsed["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 2:
        raise ProtocolError("compact context must declare exactly version 2")
    files = parsed["files"]
    if not isinstance(files, list) or not files:
        raise ProtocolError("compact context files must be a nonempty array")
    recovered: dict[str, bytes] = {}
    file_paths: list[str] = []
    for record in files:
        if not isinstance(record, dict) or set(record) != {"path", "text"}:
            raise ProtocolError("compact file records require exactly path and text")
        path, text = record["path"], record["text"]
        if not isinstance(path, str) or not isinstance(text, str):
            raise ProtocolError("compact file path/text must be strings")
        if path in recovered:
            raise ProtocolError(f"duplicate compact file path: {path}")
        recovered[path] = text.encode("utf-8")
        file_paths.append(path)
    if file_paths != list(sources):
        raise ProtocolError("compact files must appear in raw source closure order")
    if recovered != dict(sources):
        raise ProtocolError("compact file text does not equal the raw source bytes")
    order = parsed["order"]
    if not isinstance(order, list):
        raise ProtocolError("compact order must be an array")
    seen_paths: set[str] = set()
    validated: list[_OrderOverride] = []
    for record in order:
        if not isinstance(record, dict) or not record or \
                not set(record) <= {"path", "reorder", "superseded"}:
            raise ProtocolError("compact order records have an invalid shape")
        path = record.get("path")
        if not isinstance(path, str) or path not in sources:
            raise ProtocolError(f"compact order names a foreign path: {path!r}")
        if path in seen_paths:
            raise ProtocolError(f"duplicate compact order path: {path}")
        seen_paths.add(path)
        entry: _OrderOverride = {"path": path}
        if "reorder" in record:
            reorder = record["reorder"]
            if not isinstance(reorder, list) or not reorder:
                raise ProtocolError("compact reorder must be a nonempty array")
            reorder_out: list[list[int]] = []
            for group in reorder:
                ints: list[int] = []
                if isinstance(group, list):
                    for value in group:
                        if isinstance(value, int) and not isinstance(value, bool):
                            ints.append(value)
                if not isinstance(group, list) or len(group) < 2 or \
                        len(ints) != len(group):
                    raise ProtocolError("compact reorder groups must list >=2 integers")
                reorder_out.append(ints)
            entry["reorder"] = reorder_out
        if "superseded" in record:
            superseded = record["superseded"]
            superseded_out: list[int] = []
            if isinstance(superseded, list):
                for value in superseded:
                    if isinstance(value, int) and not isinstance(value, bool):
                        superseded_out.append(value)
            if not isinstance(superseded, list) or not superseded or \
                    len(superseded_out) != len(superseded):
                raise ProtocolError("compact superseded must be a nonempty integer array")
            entry["superseded"] = superseded_out
        if len(entry) == 1:
            raise ProtocolError("compact order records must carry an effect")
        validated.append(entry)
    return {"files": recovered, "order": validated, "expected": _natural_expected(sources)}


def _natural_compare_order(sources: Mapping[str, bytes],
                           advertised: Sequence[_OrderOverride],
                           expected: Sequence[_NoteUnit],
                           ) -> _OrderVerdict:
    """Compare advertised overrides with the independently expected semantics.

    Applies the advertised ``reorder``/``superseded`` to the NATURAL spans
    without any automatic date sort or state repair, then compares the full
    ordered ``(path, start_byte, end_byte, start_line, heading, state)`` tuples to
    the independent expected sequence and requires canonical override equality.
    Returns the independent verdict; a self-consistent wrong ``order[]`` fails.
    """
    advertised_by_path = {record["path"]: record for record in advertised}
    order_paths = [path for path in sources if path in advertised_by_path]
    order_paths += [path for path in advertised_by_path if path not in sources]
    applied_by_path: dict[str, list[_NoteUnit]] = {}
    for path in order_paths:
        if path not in sources:
            raise ProtocolError(f"compact order names a foreign path: {path!r}")
        record = advertised_by_path[path]
        natural = _natural_note_units(sources[path])
        for item in natural:
            item["path"] = path
        groups: list[list[_NoteUnit]] = []
        units: list[tuple[bool, list[_NoteUnit]]] = []
        note_level: int | None = None
        for item in natural:
            if item["heading"].upper().startswith("TOP NOTE"):
                groups.append([item])
                units.append((True, groups[-1]))
                note_level = item["level"]
            elif note_level is not None and item["level"] > note_level:
                groups[-1].append(item)
            else:
                units.append((False, [item]))
                note_level = None
        if "reorder" in record:
            index = {unit[1][0]["start_byte"]: position
                     for position, unit in enumerate(units) if unit[0]}
            touched: set[int] = set()
            for group in record["reorder"]:
                positions = [index[start] for start in group if start in index]
                if len(positions) != len(group):
                    raise ProtocolError("compact reorder names an unknown group start")
                span = list(range(min(positions), max(positions) + 1))
                if len(set(group)) != len(group) or set(group) & touched or \
                        set(positions) != set(span) or any(not units[pos][0] for pos in span):
                    raise ProtocolError("compact reorder must permute a distinct contiguous run")
                touched.update(group)
                reordered = [units[index[start]] for start in group]
                for offset, position in enumerate(span):
                    units[position] = reordered[offset]
        if "superseded" in record:
            starts = {group[0]["start_byte"] for group in groups}
            if len(set(record["superseded"])) != len(record["superseded"]) or \
                    not set(record["superseded"]) <= starts:
                raise ProtocolError("compact superseded names invalid or repeated groups")
            for start in record["superseded"]:
                for group in groups:
                    if group[0]["start_byte"] == start:
                        for member in group:
                            member["state"] = "explicitly-superseded"
        applied_by_path[path] = [item for _is_note, unit in units for item in unit]
    applied: list[_NoteUnit] = []
    for path in sources:
        if path in applied_by_path:
            applied.extend(applied_by_path[path])
            continue
        for item in _natural_note_units(sources[path]):
            item["path"] = path
            applied.append(item)
    def key(record: _NoteUnit) -> _OrderKey:
        return (record["path"], record["start_byte"], record["end_byte"],
                record["start_line"], record["heading"], record["state"])

    advertised_key = [key(record) for record in applied]
    expected_key = [key(record) for record in expected]
    return {"match": advertised_key == expected_key,
            "advertised": advertised_key, "expected": expected_key}


class _CompactReader(Protocol):
    """A ``StartupReader`` whose ``read`` accepts the reviewed compact keyword."""

    def read(self, paths: Sequence[str], *, compact: bool) -> StartupBundle: ...


def compact_read_supported(reader: StartupReader) -> TypeGuard[_CompactReader]:
    """True only when the real reader advertises the reviewed compact keyword."""
    try:
        return "compact" in inspect.signature(reader.read).parameters
    except (TypeError, ValueError):
        return False


def _compact_reader(reader: StartupReader) -> _CompactReader | None:
    return reader if compact_read_supported(reader) else None


def _order_json(order: Sequence[_OrderOverride]) -> list[JsonValue]:
    """JSON-typed copy of canonical order overrides, keeping key order."""
    records: list[JsonValue] = []
    for override in order:
        record: dict[str, JsonValue] = {"path": override["path"]}
        if "reorder" in override:
            record["reorder"] = [list(group) for group in override["reorder"]]
        if "superseded" in override:
            record["superseded"] = list(override["superseded"])
        records.append(record)
    return records


_STARTUP_SHAPE = "startup context has an unexpected JSON shape"


def startup_scenario(*, compact: bool = False) -> _StartupReport | _PendingReport:
    """QA-2 against the real public ``StartupReader``, legacy or compact mode.

    ``compact=False`` exercises today's legacy v1 reader and is labeled as the
    legacy mode in its report. ``compact=True`` calls ``read(paths, compact=True)``
    and verifies the compact payload's own format; it is reported conditionally
    PENDING only when the public keyword is genuinely absent after inspecting the
    real reader. Legacy bytes are never reported as a compact PASS.

    The compact verdict is decided by the QA-local natural oracle
    (:func:`_natural_compare_order`), not by the candidate's verifier, so an
    always-successful candidate that advertises a wrong ``order[]`` cannot PASS.
    """
    from birkin_mnemosyne.startup import StartupError, StartupReader

    mode = "compact" if compact else "legacy"
    feature = f"startup-{mode}"
    sources = synthetic_startup_files()
    observed: dict[str, JsonValue] = {}
    with tempfile.TemporaryDirectory(prefix=f"mnemosyne-r4-startup-{mode}-") as directory:
        root = Path(directory)
        (root / "profile").mkdir()
        for name, text in sources.items():
            _ = (root / name).write_bytes(text.encode("utf-8"))
        # Snapshot the raw byte map, in the independent natural closure order,
        # while the sources are pristine; the mutation phase below changes
        # ``profile/human.md`` in place.
        initial_raw = _natural_closure(root, list(STARTUP_CLOSURE)) if compact else {}
        reader = StartupReader(root)
        compact_reader = _compact_reader(reader) if compact else None
        if compact and compact_reader is None:
            return _pending(
                feature,
                "public StartupReader.read(paths, compact=True) is not implemented; "
                + "compact coverage is verified at T13",
                {"legacy_mode": "startup-legacy",
                 "legacy_read_available": True},
            )
        bundle = (compact_reader.read(list(STARTUP_CLOSURE), compact=True)
                  if compact_reader is not None
                  else reader.read(list(STARTUP_CLOSURE)))
        observed["mode"] = mode
        observed["complete"] = bundle.coverage.complete
        observed["files"] = bundle.coverage.files
        observed["lines"] = bundle.coverage.lines
        observed["bytes"] = bundle.coverage.bytes
        payload = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
        observed["version"] = payload.get("version")
        observed["payload_keys"] = [*sorted(payload)]
        if compact and payload.get("version") == 1:
            raise AssertionError("compact mode returned the legacy v1 payload")
        observed["expected_totals"] = (
            bundle.coverage.files == STARTUP_FILES
            and bundle.coverage.lines == STARTUP_LINES
            and bundle.coverage.bytes == STARTUP_BYTES)
        recovered: dict[str, bytes] = {}
        if compact:
            for raw_record in _as_list(payload["files"], _STARTUP_SHAPE):
                file_record = _as_dict(raw_record, _STARTUP_SHAPE)
                recovered[_str_field(file_record, "path")] = (
                    _str_field(file_record, "text").encode("utf-8"))
        else:
            for relative in sources:
                blocks = sorted(
                    (block for block in (
                        _as_dict(raw_block, _STARTUP_SHAPE)
                        for raw_block in _as_list(payload["blocks"], _STARTUP_SHAPE))
                        if block["path"] == relative),
                    key=lambda block: _int_field(block, "start_byte"))
                position = 0
                parts: list[bytes] = []
                for block in blocks:
                    raw = _str_field(block, "text").encode("utf-8")
                    _require(_int_field(block, "start_byte") == position,
                             "startup context has a gap or overlapping source spans")
                    _require(len(raw) == _int_field(block, "end_byte") - position,
                             "startup span text does not match its byte range")
                    parts.append(raw)
                    position = _int_field(block, "end_byte")
                recovered[relative] = b"".join(parts)
        observed["bytes_reconstruct"] = recovered == {
            relative: text.encode("utf-8") for relative, text in sources.items()
        }
        _require(observed["bytes_reconstruct"],
                 "startup context does not reconstruct every original source byte")

        failed: list[str] = []

        def rejected(
            label: Literal[
                "drop_rejected", "alter_rejected", "foreign_block_rejected",
                "foreign_order_rejected", "permuted_order_rejected",
                "changed_bytes_rejected",
            ],
            context: str,
        ) -> None:
            """Record an independent verifier refusal for one mutation."""
            try:
                coverage = reader.verify(context, list(STARTUP_CLOSURE))
            except StartupError:
                observed[label] = True
                return
            observed[label] = not coverage.complete
            if coverage.complete:
                failed.append(label)

        dropped = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
        dropped_blocks = dropped.get("blocks")
        if isinstance(dropped_blocks, list) and dropped_blocks:
            _ = dropped_blocks.pop()
        else:
            _ = _as_list(dropped["files"], _STARTUP_SHAPE).pop()
        rejected("drop_rejected", json.dumps(dropped))

        altered = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
        altered_blocks = altered.get("blocks")
        if isinstance(altered_blocks, list) and altered_blocks:
            last_block = _as_dict(altered_blocks[-1], _STARTUP_SHAPE)
            last_block["text"] = str(last_block["text"]) + "mutated"
        else:
            files = altered.get("files")
            if isinstance(files, list) and files:
                first_file = _as_dict(files[0], _STARTUP_SHAPE)
                first_file["text"] = _str_field(first_file, "text") + "mutated"
        rejected("alter_rejected", json.dumps(altered))

        foreign = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
        foreign_blocks = foreign.get("blocks")
        if isinstance(foreign_blocks, list) and foreign_blocks:
            clone = dict(_as_dict(foreign_blocks[-1], _STARTUP_SHAPE))
            clone["path"] = "foreign/never-declared.md"
            foreign_blocks.append(clone)
        else:
            foreign_files = foreign.get("files")
            if isinstance(foreign_files, list) and foreign_files:
                _as_dict(foreign_files[0], _STARTUP_SHAPE)["path"] = (
                    "foreign-never-declared.md")
        rejected("foreign_block_rejected", json.dumps(foreign))
        if compact:
            permuted = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
            permuted_order = permuted.get("order")
            _require(isinstance(permuted_order, list),
                     "the compact context must expose its presentation overrides")
            assert isinstance(permuted_order, list)
            permuted_order.append({"path": "foreign/never-declared.md"})
            rejected("foreign_order_rejected", json.dumps(permuted))
            if len(_as_list(payload["order"], _STARTUP_SHAPE)) > 1:
                permuted = _as_dict(_json(bundle.context), _STARTUP_SHAPE)
                _as_list(permuted["order"], _STARTUP_SHAPE).reverse()
                rejected("permuted_order_rejected", json.dumps(permuted))

        # An empty/missing declaration set must fail closed, not return a bundle.
        try:
            _ = reader.read([])
        except StartupError:
            observed["empty_declaration_fails_closed"] = True
        else:
            observed["empty_declaration_fails_closed"] = False
            failed.append("empty_declaration_fails_closed")

        # An escaping declaration must fail closed.
        try:
            _ = reader.read(["../escape.md"])
        except StartupError:
            observed["escape_rejected"] = True
        else:
            observed["escape_rejected"] = False
            failed.append("escape_rejected")

        # Same-stat changed bytes: restore mtime_ns and size after an in-place
        # byte swap, so only the content differs when verify() rereads it.
        target = root / "profile" / "human.md"
        before = target.stat()
        original = sources["profile/human.md"]
        # Equal byte length, different bytes: only the content changes.
        replacement = original.replace("publication requires consent",
                                       "permission for publication required")
        if len(replacement) != len(original) or replacement == original:
            replacement = "# Human\nApproval: consent is required\n".ljust(
                len(original) - 1, " ") + "\n"
        if len(replacement) == len(original) and replacement != original:
            with target.open("r+b") as handle:
                _ = handle.write(replacement.encode("utf-8"))
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
            after = target.stat()
            observed["preserved_mtime"] = (
                after.st_mtime_ns == before.st_mtime_ns and after.st_size == before.st_size)
            if not observed["preserved_mtime"]:
                failed.append("same_stat_preservation")
            rejected("changed_bytes_rejected", bundle.context)
        else:
            failed.append("preserved_mtime_construction")

        # A fresh reader must, from the mutated sources, produce a payload whose
        # index/state fields agree with what the legacy reader derives for the
        # SAME bytes at the same fixpoint: the unchanged files keep byte-identical
        # certificates and only the mutated file's certificate changes there.
        fresh = StartupReader(root)
        fresh_compact = _compact_reader(fresh) if compact else None
        if compact:
            assert fresh_compact is not None
        fresh_bundle = (fresh_compact.read(list(STARTUP_CLOSURE), compact=True)
                        if fresh_compact is not None
                        else fresh.read(list(STARTUP_CLOSURE)))
        legacy = StartupReader(root).read(list(STARTUP_CLOSURE))
        fixed = _json(legacy.context)               # legacy derives the fixpoint
        fresh_payload = _json(fresh_bundle.context)
        if compact:
            # The compact verdict must come from the QA-local natural oracle,
            # never from the candidate's own verifier: a self-consistent reader
            # can prove only its own consistency. Validate the parsed context and
            # compare its advertised order overrides against the independently
            # expected span/state semantics derived from raw source bytes, then
            # require canonical override equality.
            fresh_raw = _natural_closure(root, list(STARTUP_CLOSURE))
            initial_parsed = _natural_parse_context(bundle.context, initial_raw)
            fresh_parsed = _natural_parse_context(fresh_bundle.context, fresh_raw)
            initial_verdict = _natural_compare_order(
                initial_raw, initial_parsed["order"], initial_parsed["expected"])
            fresh_verdict = _natural_compare_order(
                fresh_raw, fresh_parsed["order"], fresh_parsed["expected"])
            canonical_initial = _natural_order_overrides(initial_raw)[0]
            canonical_fresh = _natural_order_overrides(fresh_raw)[0]
            agrees = (initial_verdict["match"] and fresh_verdict["match"]
                      and fresh_parsed["files"] == fresh_raw
                      and initial_parsed["order"] == canonical_initial
                      and fresh_parsed["order"] == canonical_fresh)
            observed["order_state_oracle"] = {
                "initial_match": initial_verdict["match"],
                "fresh_match": fresh_verdict["match"],
                "fresh_bytes_reconstruct": fresh_parsed["files"] == fresh_raw,
                "initial_order": _order_json(initial_parsed["order"]),
                "fresh_order": _order_json(fresh_parsed["order"]),
                "expected_initial": _order_json(canonical_initial),
                "expected_fresh": _order_json(canonical_fresh),
            }
        else:
            agrees = fresh_payload == fixed
        observed["order_state_agrees"] = agrees
        if not agrees:
            failed.append("order_state_agrees")

        if not bundle.coverage.complete or not observed["expected_totals"]:
            raise AssertionError(f"startup coverage incomplete: {observed}")
        if failed:
            raise AssertionError(f"startup QA-2 checks failed: {failed}; {observed}")
    assert not Path(directory).exists(), "startup temp root leaked"
    cleanup = f"temporary startup {mode} root removed: {directory}"
    if compact:
        return {"feature": feature, "mode": "compact", "result": "PASS",
                "observed": observed, "cleanup": cleanup}
    return {"feature": feature, "mode": "legacy", "result": "LEGACY-PASS",
            "observed": observed, "cleanup": cleanup,
            "note": ("legacy v1 proof only; the reviewed QA-2 compact proof is "
                     + "--feature startup")}


# --------------------------------------------------------------------------- #
# QA-3: kibitzer recall public scenario
# --------------------------------------------------------------------------- #

def kibitzer_query_plan() -> list[_KibitzerQuery]:
    """Field-contrast queries whose BM25 ordering the core also determines.

    Every query's terms sit on one attribute (title, tags, body, source) so the
    adapter's flat BM25 and the core's BM25 × boosts rank the same way; the
    expected ordered path list is authored here, not read from a fixture.
    """
    return [
        {"query": "espresso", "expect": ["title"]},
        {"query": "harbor permission", "expect": ["tags"]},
        {"query": "retention diagnostics", "expect": ["body"]},
        {"query": "audit", "expect": ["source"]},
    ]


_KIBITZER_SUPPORT = 1000


class _KibitzerSeedFields(TypedDict):
    title: str
    body: str


class _KibitzerSeed(_KibitzerSeedFields, total=False):
    tags: list[str]
    source: str


def _iso_midnight(now: datetime) -> datetime:
    """The exact instant local midnight began on ``now``'s calendar day.

    Used as an exact, sleep-free clock seam: a note written just before this
    instant is expired (its date is ``now.date() - 1 day``) and a note written
    at or after it is not, so the boundary between the two is proven without
    waiting for a real midnight.
    """
    return datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)


def _past_expiry(now: datetime) -> str:
    """Return the date before the supplied local calendar day."""
    return (now.date() - timedelta(days=1)).isoformat()


def _seed_kibitzer_vault(memory: VaultMemory, notes: int
                         ) -> list[_KibitzerSeed]:
    """Materialize the seed + scale + edge notes, returning the seed rows.

    The authored-note total is exact: seed rows + two authored path notes +
    edge material + generated scale rows sum to ``notes`` for every accepted
    size at or above that fixed floor. A vacuous count (a query with no
    material) is refused rather than counted as a pass.
    """
    seed: list[_KibitzerSeed] = [
        {"title": "espresso bar", "body": "Espresso bar service opens daily.",
         "tags": ["harbor", "permission"]},
        {"title": "Harbor notice",
         "body": "Retention diagnostics describe the archive sweep.",
         "source": "audit:review"},
        {"title": "espresso ledger", "body": "Espresso ledger entries close daily."},
        {"title": "espresso schedule", "body": "Espresso schedule tracks deliveries."},
    ]
    for note in seed:
        _ = memory.write_note(note["title"], note["body"],
                          tags=note.get("tags"), source=note.get("source", "user:seed"))
    # Protected system-zone material (``system/...`` is excluded by ``_allowed``)
    # plus a nested reference/system note that must stay searchable.
    _ = memory.write_note("System root note", "Root system note about espresso stewardship.",
                      zone="system", source="user:system")
    _ = memory.write_note("Nested tree note",
                      "Nested tree instruction about retention diagnostics.",
                      note_type="project", source="user:tree")
    # A genuinely description-only note: its one marker lives only in the
    # frontmatter description, absent from the title, body and tags, so only an
    # adapter that indexes the description can return it.
    described = memory.write_note(
        "Quiet note", "Nothing relevant is written in this body text.",
        tags=["descnomarker"], source="user:desc")
    text = described.read_text(encoding="utf-8")
    _ = described.write_text(
        text.replace("type: topic",
                     "type: topic\ndescription: audittrail uniquemarker description only"),
        encoding="utf-8")
    # A tag-only note: its marker exists only inside the tag list, never in the
    # description or body. The core indexes tags; adapter parity is observed
    # separately from the genuinely description-only fallback above.
    _ = memory.write_note("Tag carrier", "No marker word appears in this body prose.",
                      tags=["tagsentinel"], source="user:tag")
    # Page material: five stored notes for the top-two-exclusion proof.
    for index in range(5):
        _ = memory.write_note(
            "paginated marker" if index == 0 else f"paginated marker {index}",
            "paginated marker body shared marker context.", source="user:page")
    edge_titles = [item["title"] for item in edge_mutation_notes()]
    fixed = (len(seed) + 2 + 1 + 1 + 5 + len(edge_titles))
    if notes < fixed:
        raise ProtocolError(
            f"kibitzer notes={notes} is below the {fixed}-note fixed floor; "
            + "a count that cannot hold the authored material has no valid size")
    for note in synthetic_notes(notes - fixed):
        _ = memory.write_note(note["title"], note["body"])
    for note in edge_mutation_notes():
        _ = memory.write_note(note["title"], note["body"])
    return seed


def kibitzer_scenario(*, notes: int = 160, cap: int = 3) -> _KibitzerReport:
    """QA-3 exercised against the real public ``KibitzerAdapter`` and ``VaultMemory``.

    Required observations: an exact ``notes``-count vault, a genuine
    description-only hit that no tag supplies,
    root-system exclusion with a nested reference/system path still searchable,
    exclusion before cap, warm deletion and rename visibility, an exact local
    midnight expiry seam driven through a fixed clock without sleeping, XML-safe
    nudge roundtrip, secrets redaction, astral text and the UTF-16 excerpt
    budget.

    The field-contrast block preserves a *candidate vs actual* comparison: the
    authored per-query ordering is the candidate, and the core's own ranking is
    the actual baseline. Ranking regression is never claimed as PASS -- the
    disagreement produces LEGACY-FAIL while the invariants QA-3
    really owns (read-only, exclusions before cap, exact local-day expiry) are
    asserted.
    """
    if TYPE_CHECKING:
        from birkin_mnemosyne.memory import VaultMemory
    else:
        from birkin_mnemosyne import VaultMemory
    from unittest.mock import patch

    from birkin_mnemosyne import kibitzer as kibitzer_module
    from birkin_mnemosyne import mnemosyne as core_module
    from birkin_mnemosyne.kibitzer import (
        KibitzerAdapter,
        RecallNudge,
        admit,
        render_recall,
        utf16_length,
    )

    observed: dict[str, JsonValue] = {}
    with tempfile.TemporaryDirectory(prefix="mnemosyne-r4-kibitzer-") as directory:
        root = Path(directory)
        vault = root / "vault"
        memory = VaultMemory({"vault_path": str(vault)})
        memory.dex.refresh()
        seed = _seed_kibitzer_vault(memory, notes)
        memory.dex.refresh()
        observed["seed_notes"] = len(seed)
        observed["supported_note_limit"] = _KIBITZER_SUPPORT

        before = {p.relative_to(vault).as_posix(): p.read_bytes()
                  for p in vault.rglob("*.md")}
        observed["vault_notes"] = len(before)
        observed["root_system_note"] = "system/system-root-note.md" in before
        observed["nested_note"] = any("/" in path for path in before)
        described_rel = "knowledge/quiet-note.md"
        observed["described_rel"] = described_rel

        adapter = KibitzerAdapter(vault)
        start = time.perf_counter()
        hits = adapter.select("espresso", limit=cap)
        observed["select_ms"] = round((time.perf_counter() - start) * 1000, 3)
        observed["ordered_paths"] = [hit.path for hit in hits]
        observed["adapter_read_only"] = before == {
            p.relative_to(vault).as_posix(): p.read_bytes() for p in vault.rglob("*.md")}

        # Root exclusion: a query whose term lives only in the root-system note
        # must not surface it, while the same term in a nested reference/system
        # note stays searchable. The core baseline is only consulted as
        # supporting evidence -- the exclusion belongs to the adapter contract.
        root_only = [hit.path for hit in adapter.select("stewardship", limit=notes)]
        observed["root_system_excluded"] = "system/system-root-note.md" not in root_only
        observed["nested_searchable"] = any(
            hit.path == "projects/nested-tree-note.md"
            for hit in adapter.select("retention diagnostics", limit=notes))

        # Genuine description-only hit: the marker exists only in the note's
        # description, and no tag carries it; core cannot resolve it.
        described_hits = [hit.path for hit in adapter.select("audittrail", limit=cap)]
        tag_sentinel_hits = [hit.path for hit in adapter.select("tagsentinel", limit=cap)]
        core_described = [row["rel"] for row in memory.dex.search("audittrail", limit=cap)]
        core_tag_sentinel = [row["rel"] for row in memory.dex.search("tagsentinel", limit=cap)]
        observed["description_only_hit"] = described_rel in described_hits
        observed["description_only_core_misses"] = described_rel not in core_described
        observed["tag_only_no_hit"] = tag_sentinel_hits == []
        observed["tag_only_core_hit"] = core_tag_sentinel == ["knowledge/tag-carrier.md"]
        observed["absent_no_hit"] = len(adapter.select("zzzqqqwx", limit=cap)) == 0

        # Candidate vs actual field-contrast ordering. ``candidate`` values are
        # the authored expectations from the plan; ``actual`` is the core's own
        # ranking, and ``adapter`` is what the surface returns. Ordering
        # regression is reported, never asserted as a pass.
        agreements: list[bool] = [tag_sentinel_hits == core_tag_sentinel]
        ordering: list[JsonValue] = [{
            "query": "tagsentinel", "candidate": ["knowledge/tag-carrier.md"],
            "adapter": list(tag_sentinel_hits), "actual": list(core_tag_sentinel),
            "agrees": agreements[0],
        }]
        regressed: list[str] = [] if agreements[0] else ["tagsentinel"]
        for plan in kibitzer_query_plan():
            query = str(plan["query"])
            paths = [hit.path for hit in adapter.select(query, limit=cap)]
            core_paths = [row["rel"] for row in memory.dex.search(query, limit=cap)]
            agrees = paths == core_paths
            agreements.append(agrees)
            ordering.append({"query": query, "candidate": list(plan["expect"]),
                             "adapter": list(paths), "actual": list(core_paths),
                             "agrees": agrees})
            if not agrees:
                regressed.append(query)
        observed["ordering"] = ordering
        observed["core_order_matches"] = all(agreements) and bool(agreements)
        observed["ordering_regressions"] = list(regressed)

        # Exclusion before cap on a deliberately even page beyond the seed.
        page_paths = [hit.path for hit in adapter.select("paginated", limit=notes)]
        surfaced = page_paths[:2]
        excluded = [hit.path for hit in
                    adapter.select("paginated", limit=cap, exclude_paths=surfaced)]
        observed["page_ranked"] = list(page_paths)
        observed["exclusion_before_cap"] = (
            len(surfaced) == 2 and len(page_paths) > 2
            and excluded == [p for p in page_paths if p not in surfaced][:cap])

        # Warm cached deletion: after the cache is warm, an unlink must vanish
        # from the next selection without force_refresh.
        target = next((p for p in vault.rglob("espresso-ledger.md")), None)
        _require(target is not None and target.is_file(), "espresso-ledger seed missing")
        _ = adapter.select("espresso", limit=notes)  # warm the snapshot cache
        assert target is not None
        target.unlink()
        after_delete = [hit.path for hit in adapter.select("espresso ledger", limit=notes)]
        observed["deleted_note_invisible"] = all(
            "espresso-ledger" not in path for path in after_delete)

        # Warm cached rename: a same-bytes, same-size move to a new path must be
        # discovered by the fingerprint (path is part of the signature).
        sched = next(vault.rglob("espresso-schedule.md"), None)
        _require(sched is not None and sched.is_file(), "espresso-schedule seed missing")
        assert sched is not None
        renamed_rel = sched.parent / "espresso-schedule-renamed.md"
        _ = sched.rename(renamed_rel)
        renamed_seen = [hit.path for hit in
                        adapter.select("espresso schedule deliveries", limit=notes)]
        observed["renamed_note_visible"] = any(
            path.endswith("espresso-schedule-renamed.md") for path in renamed_seen)
        observed["stale_path_invisible"] = all(
            not path.endswith("espresso-schedule.md") for path in renamed_seen)

        # Live edit visibility without an explicit force_refresh: the adapter's
        # fingerprint must notice a same-size body change in a changed file.
        _ = memory.write_note("espresso bar", "Espresso bar service closed nightly.")
        edited = adapter.select("nightly", limit=notes)
        observed["live_edit_visible"] = any(
            h.path.endswith("espresso-bar.md") for h in edited)

        # Edge material: redaction, astral characters and UTF-16 excerpt budget.
        secret_path = next((p for p in before if p.endswith("edge-secret.md")), "")
        secret_doc = next((d for d in adapter.documents() if d.path == secret_path), None)
        planted_secrets = ("REDACTED-VALUE-0001", "token=REDACTED-VALUE-0001")
        secret_body = secret_doc.body.casefold() if secret_doc is not None else ""
        observed["secret_redacted"] = (
            secret_doc is not None
            and all(s.casefold() not in secret_body for s in planted_secrets)
            and "[redacted]" in secret_body)
        astral_path = next((p for p in before if p.endswith("edge-astral.md")), "")
        astral = adapter.select("Astral", limit=cap)
        observed["astral_hit"] = any(h.path == astral_path for h in astral)
        observed["excerpt_utf16_within_budget"] = bool(astral) and all(
            utf16_length(hit.excerpt) <= 200 for hit in astral)

        # XML-safe nudge roundtrip: escaping preserves the raw path and hint
        # through render_recall, and admit keeps an astral hint under 200 units.
        raw_path = 'knowledge/quoted"tagged<note>.md'
        raw_hint = "Stored observation with <angle> & 'quote' \U0001f680."
        admitted = admit([RecallNudge(raw_path, raw_hint)],
                         offered={raw_path}, max_items=1)
        rendered = render_recall(admitted.accepted[0]) if admitted.accepted else ""
        from xml.etree import ElementTree

        parsed_xml = ElementTree.fromstring(rendered.encode("utf-8"))
        observed["xml_roundtrip"] = (
            parsed_xml.attrib["source"] == f"[[{raw_path}]]"
            and (parsed_xml.text or "").splitlines()[-1] == raw_hint)
        astral_nudge = RecallNudge(raw_path, "\U0001f600" * 100)
        observed["astral_hint_accepted"] = bool(
            admit([astral_nudge], offered={raw_path}, max_items=1).accepted)
        over_nudge = RecallNudge(raw_path, "a" * 201)
        observed["overlong_hint_rejected"] = not admit(
            [over_nudge], offered={raw_path}, max_items=1).accepted

        # Exact local midnight expiry seam, no sleep. A frozen clock fixes a
        # real local date; a note whose expires_at is the previous local day is
        # expired, and a note expiring only tomorrow is not. The adapter's day
        # comes from what it sees as local today, so the authored date is
        # derived from the frozen instant rather than a hard-coded offset.
        local_zone = timezone(timedelta(hours=9))
        midnight = _iso_midnight(datetime(2026, 10, 3, tzinfo=local_zone))
        clock = [midnight - timedelta(minutes=1)]
        expired_path = memory.write_note(
            "Expired guard", "Expired guard note about guardrail.", source="user:ttl")
        _ = expired_path.write_text(
            "---\ntitle: Expired guard\nexpires_at: "
            + f"{_past_expiry(midnight)}\n---\nExpired guard note about guardrail.\n",
            encoding="utf-8")
        future_path = memory.write_note(
            "Future guard", "Future guard note about guardrail.", source="user:ttl")
        _ = future_path.write_text(
            "---\nexpires_at: 2026-10-04\n---\nFuture guard note about guardrail.\n",
            encoding="utf-8")

        class _MidnightClock(datetime):
            """Local-datetime subclass whose ``now`` is the captured midnight."""

            @classmethod
            @override
            def now(cls, tz: tzinfo | None = None) -> datetime:
                return cls.fromtimestamp(clock[0].timestamp(), tz=tz)

            @override
            def astimezone(self, tz: tzinfo | None = None) -> datetime:
                return super().astimezone(local_zone if tz is None else tz)

        class _LocalDay(date):
            @classmethod
            @override
            def today(cls) -> date:
                return clock[0].date()

        with (
            patch.object(kibitzer_module, "datetime", _MidnightClock),
            patch.object(core_module, "datetime", _MidnightClock),
            patch.object(core_module, "date", _LocalDay),
        ):
            before_midnight = {hit.path for hit in adapter.select("guardrail", limit=notes)}
            clock[0] += timedelta(minutes=2)
            expired_seen = {hit.path for hit in adapter.select("guardrail", limit=notes)}
        observed["expired_note_invisible"] = not any(
            "expired-guard" in path for path in expired_seen)
        observed["future_note_visible"] = any(
            "future-guard" in path for path in expired_seen)
        observed["expiry_boundary"] = (
            any("expired-guard" in path for path in before_midnight)
            and observed["expired_note_invisible"] and observed["future_note_visible"])

        _require(observed["adapter_read_only"],
                 "KibitzerAdapter.select mutated the vault")
        _require(observed["root_system_excluded"],
                 "a root-system note surfaced as a recall candidate")
        _require(observed["nested_searchable"],
                 "a nested reference/system note was unreachable")
        _require(observed["description_only_hit"],
                 "a genuine description-only note was not returned")
        _require(observed["description_only_core_misses"],
                 "the description-only marker leaked into the core index")
        _require(observed["tag_only_core_hit"],
                 "the tag-only fixture was not independently supported by the core")
        _require(observed["absent_no_hit"], "a no-hit query returned candidates")
        _require(observed["exclusion_before_cap"],
                 "surfaced paths leaked into the returned candidates")
        _require(observed["deleted_note_invisible"],
                 "a warm-cached deletion stayed visible")
        _require(observed["renamed_note_visible"] and observed["stale_path_invisible"],
                 "a warm-cached rename kept the stale path")
        _require(observed["live_edit_visible"],
                 "a live edit was invisible without force_refresh")
        _require(observed["secret_redacted"], "secret material was not redacted")
        _require(observed["xml_roundtrip"],
                 "an XML nudge did not preserve its raw path and hint")
        _require(observed["astral_hint_accepted"] and observed["overlong_hint_rejected"],
                 "UTF-16 hint budget did not match the 200-unit rule")
        _require(observed["excerpt_utf16_within_budget"],
                 "an excerpt exceeded the 200 UTF-16 budget")
        _require(observed["expiry_boundary"],
                 "expiry boundary disagreed with the exact local midnight rule")
        _require(observed["vault_notes"] == notes,
                 f"authored note total was {observed['vault_notes']}, expected {notes}")
    assert not Path(directory).exists(), "kibitzer temp vault leaked"
    note = ("legacy public surface; cache warm-edit/delete/rename, exact local "
            + "midnight expiry and the XML nudge roundtrip are verified here")
    if regressed:
        note += ("; field-contrast ranking regression reported: "
                 + ", ".join(regressed))
    result: Literal["LEGACY-FAIL", "LEGACY-PASS"] = (
        "LEGACY-FAIL" if regressed else "LEGACY-PASS")
    return {"feature": "kibitzer", "mode": "legacy", "result": result,
            "observed": observed, "seed": seed,
            "cleanup": f"temporary vault removed: {directory}", "note": note}


# --------------------------------------------------------------------------- #
# QA-4: consolidation question public scenario
# --------------------------------------------------------------------------- #

def questions_scenario(*, semantic: bool = False, author: str = SOL_AUTHOR,
                       practice: str | Path = _PRACTICE_DEFAULT,
                       ) -> _QuestionsReport | _PendingReport:
    """QA-4 pair accounting against the real public ``Consolidation``.

    Every authored tuning case is materialized as its own two-note vault, the
    real pipeline offers unordered pairs, and TP/FP/FN are counted from those
    offered pairs. Complete recall and capped recall@20/@100 come from separate
    real ``questions`` calls. When ``semantic`` is requested the public semantic
    surface is inspected and, if present, driven with the locked configuration
    and required to report ``ready``; a genuinely absent surface is PENDING.
    """
    document = load_practice(practice)
    thresholds = None
    if semantic:
        try:
            thresholds = semantic_thresholds()
        except ProtocolError as exc:
            return _pending("questions-semantic", str(exc),
                            {"lexical_scenario_available": True})
        if not semantic_service_supported(Path.cwd(), thresholds):
            return _pending(
                "questions-semantic",
                "public Consolidation(vault, semantic=True, thresholds=...) is not "
                + "implemented; semantic recall is verified at T14",
                {"lexical_scenario_available": True})

    item = _require_author(document, author)
    authored = [_as_dict(raw, f"{author}: every pair must be an object")
                for raw in item["pairs"]]
    tuning = [p for p in authored if p["partition"] == "tuning"]
    tuning_topics = {_str_field(p, "topic_group") for p in tuning}

    by_cap: dict[int, _PairCounts] = {cap: {"tp": 0, "fp": 0, "fn": 0, "abstained": 0}
              for cap in (10_000, PUBLIC_QUESTION_CAP, MCP_QUESTION_CAP)}
    for pair in tuning:
        notes = _pair_notes(pair)
        positives: set[tuple[int, int]] = {(0, 1)} if pair["related"] else set()
        capture = _capture_questions(notes, positives, semantic=semantic)
        if capture["result"] != "OBSERVED":
            return _pending("questions-semantic",
                            "semantic question pipeline is not ready",
                            {**capture, "cleanup": "all temporary question vaults removed"})
        for cap, totals in by_cap.items():
            counts = capture["captures"][str(cap)]["counts"]
            totals["tp"] += counts["tp"]
            totals["fp"] += counts["fp"]
            totals["fn"] += counts["fn"]
            totals["abstained"] += counts["abstained"]

    totals = by_cap[10_000]
    positive_total = totals["tp"] + totals["fn"]
    complete_recall = (round(totals["tp"] / positive_total, 4)
                       if positive_total else 0.0)
    issued = totals["tp"] + totals["fp"]
    precision = round(totals["tp"] / issued, 4) if issued else 0.0
    public_recall = (round(by_cap[PUBLIC_QUESTION_CAP]["tp"] / positive_total, 4)
                     if positive_total else 0.0)
    mcp_recall = (round(by_cap[MCP_QUESTION_CAP]["tp"] / positive_total, 4)
                  if positive_total else 0.0)
    cap_confusion = {str(cap): counts for cap, counts in by_cap.items()}

    mixed = [mixed_vault_fixture(document, author, related=related, semantic=semantic)
             for related in (True, False)]
    crowded_vault = crowded_vault_fixture(semantic=semantic)
    crowded_fixture = crowded_neighborhood_plan(document, author)
    synthetic_regressions = recall_capture_scenarios(semantic=semantic)
    observed: _QuestionsObserved = {
        "author": author,
        "tuning_topic_groups": len(tuning_topics),
        "confusion": totals,
        "complete_recall": complete_recall,
        "precision": precision,
        "public_recall_at_20": public_recall,
        "mcp_recall_at_100": mcp_recall,
        "cap_confusion": cap_confusion,
        "semantic_status": "ready" if semantic else "lexical",
        "tuning_pairs": len(tuning),
        "mixed_vaults": mixed,
        "crowded_vault": crowded_vault,
        "crowded_fixture": crowded_fixture,
        "synthetic_regressions": synthetic_regressions,
    }

    fixtures: list[_MixedVault | _CrowdedVault | _RecallCase] = [
        *mixed, crowded_vault, *synthetic_regressions]
    if semantic and any(capture["result"] != "OBSERVED" for capture in fixtures):
        return _pending(
            "questions-semantic", "semantic mixed or synthetic discovery is not ready",
            {"observed": observed, "cleanup": "all temporary question vaults removed"})
    if not semantic and any(capture["result"] != "OBSERVED" for capture in fixtures):
        raise ProtocolError("a lexical mixed or synthetic discovery produced no result")
    return {"feature": "questions", "result": "PASS", "observed": observed,
            "product_quality_claimed": False,
            "cleanup": "all temporary question vaults removed"}


def _capped_recall(totals: _PairCounts, cap: int) -> float:
    """Capped recall label: never equated with complete recall."""
    positives = totals["tp"] + totals["fn"]
    if positives == 0:
        return 0.0
    return round(min(totals["tp"], cap) / positives, 4)


def crowds_notes_per_topic(count: int) -> list[dict[str, str]]:
    """Authored ``count``-note crowd covering the required >32-note neighborhood.

    The notes are original material written here: a shared release-policy topic
    over distinct archive units. Every unordered pair is an authored positive, so
    the fixture ships a full gold inventory rather than a count-only plan.
    """
    _require(count >= 2, "a shared-topic fixture needs at least two notes")
    return [{
        "title": f"Windglass archive unit {index:04d}",
        "body": (
            "The Windglass release policy requires the release steward's approval "
            f"before publishing production package {index:04d}; approval expires "
            "after one day and the archive unit records the granting steward."
        ),
    } for index in range(count)]


def translation_notes() -> list[dict[str, str]]:
    """Three language variants of one original release-approval assertion."""
    return [
        {"title": "Windglass release approval",
         "body": ("The Windglass release policy requires the release steward's "
                  "approval before publishing a production package. Approval "
                  "expires after one day.")},
        {"title": "Windglass 출시 승인",
         "body": ("Windglass의 운영 패키지는 공개 전에 출시 책임자의 승인을 받아야 한다. "
                  "승인은 하루 뒤 만료된다.")},
        {"title": "Windglass 公開承認",
         "body": ("Windglassの本番パッケージは公開前にリリース責任者の承認を得る必要がある。"
                  "承認は一日後に失効する。")},
    ]


def positive_pair_count(notes: int) -> int:
    """Number of unordered pairs in a fully positive ``notes``-note fixture."""
    return notes * (notes - 1) // 2


def _pair_notes(pair: Mapping[str, JsonValue]) -> list[dict[str, str]]:
    """The two authored notes of one validated pair as title/body strings."""
    return [{"title": _str_field(note, "title"), "body": _str_field(note, "body")}
            for note in (_as_dict(raw, "every authored note must be an object")
                         for raw in _as_list(pair["notes"], "pair notes must be a list"))]


def _select_one_case_per_topic(
        item: _ValidatedAuthor, related: bool,
        topics: Sequence[str] | None = None, *,
        partition: str = "tuning") -> list[tuple[dict[str, JsonValue], int, int]]:
    """One authored case per topic for one label, starting at its first topic.

    Picking a single case per topic keeps every cross-topic pair in the mixed
    vault unrelated by construction, so the fixture's authored inventory can
    label those pairs false without inventing extra cases. ``topics`` restricts
    selection to explicit authored topic groups (the crowded plan uses one).
    """
    selected: list[tuple[dict[str, JsonValue], int, int]] = []
    seen: set[str] = set()
    offset = 0
    for raw_pair in item["pairs"]:
        pair = _as_dict(raw_pair, "every pair must be an object")
        topic = _str_field(pair, "topic_group")
        if pair["partition"] != partition:
            continue
        if bool(pair["related"]) != related:
            continue
        if topics is not None and topic not in topics:
            continue
        if topic in seen:
            continue
        seen.add(topic)
        selected.append((pair, offset, offset + 1))
        offset += 2
    return selected


def crowded_vault_fixture(*, semantic: bool = False) -> _CrowdedVault:
    """A genuinely >32-note crowd with an explicitly authored full gold inventory.

    Every unordered pair among the crowd notes is an authored positive, so the
    fixture ships the complete pair inventory and the caller executes the real
    pipeline against it. This is the executable >32-note neighborhood case, not
    a count-only plan.
    """
    notes = crowds_notes_per_topic(CROWDED_NEIGHBORHOOD_MIN + 8)
    positives = set(combinations(range(len(notes)), 2))
    capture = _capture_questions(notes, positives, semantic=semantic)
    if "cleanup_root" in capture:
        _require(not Path(capture["cleanup_root"]).exists(),
                 "crowded question vault leaked")
        _ = capture.pop("cleanup_root")
    extras: _CrowdedExtras = {
        "case": "crowded-neighborhood",
        "exceeds_threshold": len(notes) > CROWDED_NEIGHBORHOOD_MIN,
        "gold_inventory_complete": len(positives) == len(notes) * (len(notes) - 1) // 2,
        "authored_positive_pairs": len(positives),
        "authored_negative_pairs": 0,
    }
    if capture["result"] == "OBSERVED":
        return {**capture, **extras}
    return {**capture, **extras}


def mixed_vault_fixture(document: dict[str, JsonValue], author: str, *, related: bool,
                        semantic: bool = False,
                        topics: Sequence[str] | None = None,
                        partition: str = "tuning") -> _MixedVault:
    """One concrete mixed vault with an explicit authored pair inventory.

    Exactly one authored case per topic carries the requested label, so every
    cross-topic pair is unrelated by the fixture's own disjoint-topic scope. The
    inventory labels every unordered pair. No same-topic decoys with unknown
    cross-relationships are introduced, and validation is a separate invocation.
    """
    item = _require_author(document, author)
    _require(partition in PARTITIONS, "unknown practice partition")
    selected = _select_one_case_per_topic(item, related, topics, partition=partition)
    _require(bool(selected), f"{author}: no authored case carries label {related}")
    notes = [note for pair, _, _ in selected for note in _pair_notes(pair)]
    positives = {(first, second) for pair, first, second in selected if pair["related"]}

    inventory: list[_InventoryEntry] = []
    for first, second in combinations(range(len(notes)), 2):
        same_case = first // 2 == second // 2
        source = selected[first // 2][0]
        inventory.append({
            "first": first, "second": second,
            "related": (first, second) in positives,
            "category": _str_field(source, "category") if same_case else "unrelated",
            "topic_group": (_str_field(source, "topic_group") if same_case
                            else "cross-topic-disjoint"),
        })

    capture = _capture_questions(notes, positives, semantic=semantic)
    if "cleanup_root" in capture:
        _require(not Path(capture["cleanup_root"]).exists(), "mixed question vault leaked")
        _ = capture.pop("cleanup_root")
    extras: _MixedExtras = {
        "author": author,
        "scenario": "mixed-positive" if related else "mixed-negative",
        "partition": partition,
        "selected_pairs": [_str_field(pair, "id") for pair, _, _ in selected],
        "selected_topic_groups": sorted({_str_field(pair, "topic_group")
                                         for pair, _, _ in selected}),
        "authored_inventory": inventory,
        "authored_positive_pairs": len(positives),
        "authored_negative_pairs": len(inventory) - len(positives),
        "cross_topic_label": "unrelated-disjoint-topics",
    }
    if capture["result"] == "OBSERVED":
        return {**capture, **extras}
    return {**capture, **extras}


def pair_inventory_scenario(*, author: str = SOL_AUTHOR,
                            practice: str | Path = _PRACTICE_DEFAULT,
                            ) -> _PairInventoryReport:
    """Full unordered pair inventory and the authoured crowded-neighborhood plan."""
    document = load_practice(practice)
    inventory = unordered_pair_inventory(document)
    if author not in inventory:
        raise ProtocolError(f"unknown author {author!r}")
    entries = inventory[author]
    positives = sum(1 for entry in entries.values() if entry["related"])
    crowded = crowded_neighborhood_plan(document, author)
    return {
        "feature": "pair-inventory",
        "result": "PASS",
        "author": author,
        "unordered_pairs": len(entries),
        "positive_pairs": positives,
        "negative_pairs": len(entries) - positives,
        "crowded_neighborhood": crowded,
        "crowded_gold_pairs": crowded["gold_pairs"],
        "crowded_notes": crowded["notes"],
        "meets_true_pair_minimum": positives >= REQUIRED_TRUE_PAIRS_MIN,
        "meets_crowded_minimum": crowded["exceeds_threshold"],
    }


def crowded_neighborhood_plan(document: dict[str, JsonValue], author: str) -> _CrowdedPlan:
    """Executable >32-note crowded fixture with a full authored pair inventory.

    The fixture is materialized from authored synthetic notes (not a frozen row)
    and declares every unordered pair positive in advance; the caller runs the
    real pipeline against it. ``max_neighborhood_notes`` records whether the
    authored practice itself already exceeds the threshold in one topic.
    """
    item = _require_author(document, author)
    counts: dict[str, int] = {}
    for raw_pair in item["pairs"]:
        topic = _str_field(_as_dict(raw_pair, f"{author}: every pair must be an object"),
                           "topic_group")
        counts[topic] = counts.get(topic, 0) + 1
    largest = max(counts.values()) if counts else 0
    practice_neighborhood = largest * 2  # one topic with n pairs touches up to 2n notes
    crowd_notes = CROWDED_NEIGHBORHOOD_MIN + 8
    fixture = crowds_notes_per_topic(crowd_notes)
    return {
        "case": "crowded-neighborhood",
        "notes": len(fixture),
        "gold_pairs": positive_pair_count(len(fixture)),
        "distinct_notes": len({note["body"] for note in fixture}),
        "exceeds_threshold": len(fixture) > CROWDED_NEIGHBORHOOD_MIN,
        "practice_max_pairs_in_topic": largest,
        "practice_max_neighborhood_notes": practice_neighborhood,
        "drivable": True,
    }


# --------------------------------------------------------------------------- #
# QA-4 semantic recall capture (disposable-engine proof, no frozen access)
# --------------------------------------------------------------------------- #

def semantic_thresholds() -> dict[str, JsonValue]:
    """The locked practice-calibrated config required for semantic QA.

    Loaded from ``detection-thresholds.json``; a missing, unlocked or empty
    config refuses to run semantic selection rather than falling back.
    """
    if not THRESHOLDS_PATH.is_file():
        raise ProtocolError("locked semantic thresholds are absent")
    config = _json(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    if isinstance(config, dict):
        thresholds = config.get("thresholds")
        if config.get("locked") is True and isinstance(thresholds, dict) and thresholds:
            return thresholds
    raise ProtocolError("semantic QA requires locked practice thresholds")


class _OfferedNote(Protocol):
    @property
    def path(self) -> str: ...


class _OfferedQuestion(Protocol):
    @property
    def first(self) -> _OfferedNote: ...

    @property
    def second(self) -> _OfferedNote: ...


class _QuestionService(Protocol):
    def questions(self, limit: int = 20) -> Sequence[_OfferedQuestion]: ...


class _SemanticFactory(Protocol):
    """A ``Consolidation`` constructor that accepts the semantic keywords."""

    def __call__(self, vault: Path, *, semantic: bool,
                 thresholds: dict[str, JsonValue]) -> _QuestionService: ...


def _accepts_semantic(cls: type[_Consolidation]) -> TypeGuard[_SemanticFactory]:
    return {"semantic", "thresholds"} <= set(inspect.signature(cls.__init__).parameters)


class _CaptureMetadata(TypedDict):
    notes: int
    positives: int
    gold_pairs: int
    product_quality_claimed: bool


class _CaptureRecordRequired(_CaptureMetadata):
    semantic_status: str | None
    cleanup_absent: bool
    complete_limit: int


class _CaptureRecord(_CaptureRecordRequired, total=False):
    cleanup_root: str


class _CapturedLimit(TypedDict):
    offered: int
    counts: _PairCounts


class _ObservedCaptureRequired(_CaptureRecordRequired):
    result: Literal["OBSERVED"]
    captures: dict[str, _CapturedLimit]


class _ObservedCapture(_ObservedCaptureRequired, total=False):
    cleanup_root: str


class _PendingCaptureRequired(_CaptureMetadata):
    feature: str
    result: Literal["PENDING"]
    reason: str
    verified_at: str


class _PendingCapture(_PendingCaptureRequired, total=False):
    semantic_status: str | None
    cleanup_absent: bool
    complete_limit: int
    cleanup_root: str


_CaptureResult: TypeAlias = _ObservedCapture | _PendingCapture

_RecallKeys = TypedDict("_RecallKeys", {"recall@20": float, "recall@100": float})


class _RecallExtras(TypedDict, total=False):
    exceeds_threshold: bool
    variants: list[str]
    distinct: bool


class _ObservedCase(_ObservedCapture, _RecallKeys, _RecallExtras):
    case: str


class _PendingCase(_PendingCapture, _RecallExtras):
    case: str


_RecallCase: TypeAlias = _ObservedCase | _PendingCase


class _ObservedCrowded(_ObservedCapture, _CrowdedExtras):
    pass


class _PendingCrowded(_PendingCapture, _CrowdedExtras):
    pass


_CrowdedVault: TypeAlias = _ObservedCrowded | _PendingCrowded


class _ObservedMixed(_ObservedCapture, _MixedExtras):
    pass


class _PendingMixed(_PendingCapture, _MixedExtras):
    pass


_MixedVault: TypeAlias = _ObservedMixed | _PendingMixed


class _QuestionsObserved(TypedDict):
    author: str
    tuning_topic_groups: int
    confusion: _PairCounts
    complete_recall: float
    precision: float
    public_recall_at_20: float
    mcp_recall_at_100: float
    cap_confusion: dict[str, _PairCounts]
    semantic_status: str
    tuning_pairs: int
    mixed_vaults: list[_MixedVault]
    crowded_vault: _CrowdedVault
    crowded_fixture: _CrowdedPlan
    synthetic_regressions: list[_RecallCase]


class _QuestionsReport(TypedDict):
    feature: str
    result: Literal["PASS"]
    observed: _QuestionsObserved
    product_quality_claimed: bool
    cleanup: str


def _pending_capture(feature: str, reason: str, extra: _CaptureMetadata
                     ) -> _PendingCapture:
    return {"feature": feature, "result": "PENDING",
            "reason": reason, "verified_at": "T13/T14 product phase", **extra}


def semantic_service_supported(vault: Path, thresholds: dict[str, JsonValue]) -> bool:
    """True only when the real public service accepts semantic mode and config.

    Absence of the optional surface is inspected on the shipped product class
    before any construction; it is a genuine capability observation, not a
    placeholder. A supported constructor is returned to the caller, which must
    then construct it and require an actual ``ready`` semantic status.
    """
    if TYPE_CHECKING:
        from birkin_mnemosyne.consolidation import Consolidation
    else:
        from birkin_mnemosyne import Consolidation

    del vault, thresholds
    parameters = inspect.signature(Consolidation.__init__).parameters
    return {"semantic", "thresholds"} <= set(parameters)


def build_service(vault: Path, *, semantic: bool,
                  thresholds: dict[str, JsonValue] | None) -> _QuestionService:
    """Construct the public Consolidation, forwarding semantic mode when supported."""
    if TYPE_CHECKING:
        from birkin_mnemosyne.consolidation import Consolidation
    else:
        from birkin_mnemosyne import Consolidation

    if semantic:
        assert thresholds is not None
        if _accepts_semantic(Consolidation):
            return Consolidation(vault, semantic=True, thresholds=thresholds)
        raise ProtocolError("public Consolidation(vault, semantic=True, thresholds=...) is absent")
    return Consolidation(vault)


def _capture_questions(notes: list[dict[str, str]], positives: set[tuple[int, int]],
                       *, semantic: bool = False) -> _CaptureResult:
    """Discover real proposals and score the entire explicitly labeled vault."""
    universe = set(combinations(range(len(notes)), 2))
    _require(positives <= universe, "positive inventory names a nonexistent note pair")
    metadata: _CaptureMetadata = {"notes": len(notes), "positives": len(positives),
                "gold_pairs": len(universe), "product_quality_claimed": False}
    thresholds: dict[str, JsonValue] | None = None
    if semantic:
        try:
            thresholds = semantic_thresholds()
        except ProtocolError as exc:
            return _pending_capture("questions-semantic", str(exc), metadata)
        if not semantic_service_supported(Path.cwd(), thresholds):
            return _pending_capture(
                "questions-semantic",
                "public Consolidation(vault, semantic=True, thresholds=...) is absent; "
                + "semantic recall is verified at T14", metadata)
    captured: dict[str, _CapturedLimit] = {}
    complete_limit = max(10_000, len(universe))
    status: str | None = None
    directory = tempfile.mkdtemp(prefix="mnemosyne-r4-inventory-")
    try:
        vault = Path(directory)
        knowledge = vault / "knowledge"
        knowledge.mkdir()
        paths: dict[str, int] = {}
        for index, note in enumerate(notes):
            _require("\n" not in note["title"] and "\r" not in note["title"],
                     "question titles must fit one metadata line")
            path = knowledge / f"note-{index:04d}.md"
            _ = path.write_bytes((f"---\ntitle: '{note['title']}'\n---\n\n"
                              + note["body"]).encode("utf-8"))
            paths[path.relative_to(vault).as_posix()] = index
        service = build_service(vault, semantic=semantic, thresholds=thresholds)
        for cap in (complete_limit, PUBLIC_QUESTION_CAP, MCP_QUESTION_CAP):
            offered: set[tuple[int, int]] = set()
            proposals = service.questions(limit=cap)
            status = getattr(service, "semantic_status", None) if semantic else "lexical"
            if semantic and status != "ready":
                break
            for proposal in proposals:
                _require(proposal.first.path in paths and proposal.second.path in paths,
                         "the question pipeline offered a foreign path")
                first, second = paths[proposal.first.path], paths[proposal.second.path]
                pair = (min(first, second), max(first, second))
                _require(pair in universe, "the question pipeline offered a self-pair")
                offered.add(pair)
            tp = len(offered & positives)
            fp = len(offered - positives)
            fn = len(positives) - tp
            captured[str(cap)] = {"offered": tp + fp, "counts": {
                "tp": tp, "fp": fp, "fn": fn, "abstained": fn}}
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    _require(not Path(directory).exists(), "question inventory vault leaked")
    record: _CaptureRecord = {**metadata, "semantic_status": status,
              "cleanup_root": directory, "cleanup_absent": True,
              "complete_limit": complete_limit}
    if semantic and status != "ready":
        return _pending_capture(
            "questions-semantic", "semantic discovery is not ready", record)
    return {**record, "result": "OBSERVED", "captures": captured}


def _recall_case(result: _CaptureResult, case: str) -> _RecallCase:
    """Attach capped recall labels to one captured inventory, if observed."""
    if result["result"] == "OBSERVED":
        return {
            **result, "case": case,
            "recall@20": _capped_recall(
                result["captures"][str(PUBLIC_QUESTION_CAP)]["counts"],
                PUBLIC_QUESTION_CAP),
            "recall@100": _capped_recall(
                result["captures"][str(MCP_QUESTION_CAP)]["counts"], MCP_QUESTION_CAP),
        }
    return {**result, "case": case}


def recall_capture_scenarios(*, semantic: bool = False) -> list[_RecallCase]:
    """Real capped discovery, the >32-note crowd, and the multi-translation set.

    Each case materializes its own vault and full explicit gold inventory, then
    invokes the real pipeline at the complete, public-20 and MCP-100 limits.
    These original synthetic inventories are pipeline regression scenarios, not
    a replacement for either author's quality evaluation.
    """
    results: list[_RecallCase] = []

    # >20 true pairs within one topic: 8 shared-topic notes give 28 pairs.
    small = crowds_notes_per_topic(8)
    small_positives = set(combinations(range(len(small)), 2))
    results.append(_recall_case(
        _capture_questions(small, small_positives, semantic=semantic),
        f"recall-at-{PUBLIC_QUESTION_CAP}"))
    results.append(_recall_case(
        _capture_questions(small, small_positives, semantic=semantic),
        f"recall-at-{MCP_QUESTION_CAP}"))

    # A >32-note crowded neighborhood with an authored full gold inventory.
    crowded = crowds_notes_per_topic(CROWDED_NEIGHBORHOOD_MIN + 8)
    crowded_result = _capture_questions(
        crowded, set(combinations(range(len(crowded)), 2)), semantic=semantic)
    crowded_case = _recall_case(crowded_result, "crowded-neighborhood")
    crowded_case["exceeds_threshold"] = len(crowded) > CROWDED_NEIGHBORHOOD_MIN
    results.append(crowded_case)

    # Multiple valid translations of one assertion share no Latin identifier.
    translations = translation_notes()
    translation_case = _recall_case(
        _capture_questions(translations, set(combinations(range(3), 2)), semantic=semantic),
        "multiple-translations")
    translation_case["variants"] = ["en", "ko", "ja"]
    translation_case["distinct"] = len({note["body"] for note in translations}) == 3
    results.append(translation_case)
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _pending(feature: str, reason: str, extra: _PendingExtra | None = None
             ) -> _PendingReport:
    payload: _PendingReport = {
        "feature": feature, "result": "PENDING",
        "reason": reason, "verified_at": "T13/T14 product phase"}
    if extra:
        payload.update(extra)
    return payload


_ScenarioReport: TypeAlias = (
    _StartupReport | _KibitzerReport | _QuestionsReport | _PendingReport)

SCENARIOS: dict[str, Callable[[], _ScenarioReport]] = {
    # ``startup`` is the reviewed QA-2 compact invocation. The legacy v1 reader
    # proof has its own explicit mode so it can never be reported as compact.
    "startup": lambda: startup_scenario(compact=True),
    "startup-legacy": lambda: startup_scenario(compact=False),
    "kibitzer": kibitzer_scenario,
    "consolidation": questions_scenario,
}


def _emit(payload: _ScenarioReport | _PracticeReport) -> None:
    print(json.dumps(payload, ensure_ascii=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _emit(check_practice())
        return 0
    if args[0] == "--check-practice":
        practice = _PRACTICE_DEFAULT
        if len(args) == 3 and args[1] == "--practice":
            practice = args[2]
        elif len(args) != 1:
            raise SystemExit("usage: qa.py --check-practice [--practice PATH]")
        _emit(check_practice(practice))
        return 0
    if args[0] == "--feature":
        if len(args) < 2 or args[1] not in SCENARIOS:
            raise SystemExit(
                "usage: qa.py --feature startup|startup-legacy|kibitzer|"
                + "consolidation [--semantic]")
        feature = args[1]
        semantic = "--semantic" in args[2:]
        if feature == "consolidation":
            _emit(questions_scenario(semantic=semantic))
        else:
            if semantic:
                raise SystemExit("--semantic applies only to --feature consolidation")
            # QA-2's reviewed invocation is the compact mode: --feature startup
            # executes read(paths, compact=True), never the legacy read.
            result = SCENARIOS[feature]()
            _emit(result)
            if result["result"] in {"FAIL", "LEGACY-FAIL"}:
                return 1
        return 0
    raise SystemExit(
        "usage: qa.py [--check-practice [--practice PATH]] | "
        + "--feature startup|startup-legacy|kibitzer|consolidation [--semantic]")


if __name__ == "__main__":
    raise SystemExit(main())
