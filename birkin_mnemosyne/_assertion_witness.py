"""Literal assertion witnesses, never topic similarity or truth adjudication."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

_WORDS: Final = re.compile(r"[^\W\d_]+")
_VALUE: Final = re.compile(
    r"(?<![\w.])[+-]?(?:\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?|\.\d+)(?!\d)"
)
_VALUE_POSITION: Final = re.compile(
    r"(?:[:=<>]|\b(?:is|are|was|were|be|after|before|within|at|on|by|than|of|to|for"
    + r"|uses|has|contains|holds|weighs|measures|equals|costs|lasts|takes))"
    + r"\s*(?:[$\u20ac\u00a3\u00a5]\s*)?$"
)
_CATEGORICAL: Final = re.compile(
    r"^((?:[^\W\d_]+\s+){1,7}"
    + r"(?:color|colour|material|mode|status|type|code|name|address)"
    + r"\s+(?:is|are|was|were)\s+)[^\W_]+[.!?]?$"
)
_NEGATED: Final = re.compile(
    r"\b(is|are|was|were|does|do|did|can|could|will|would|should|must|may|might)"
    + r"\s+not\b"
)
SUBJECT_FUNCTIONS: Final = frozenset(
    (
        "i me my mine we us our ours you your yours he him his she her hers "
        + "it its they them their theirs this that these those who which whose "
        + "to in on at of by for from with about and or but if then when while "
        + "all each every"
    ).split()
)
_PREDICATE: Final = re.compile(
    r"(?:is|are|was|were|has|have|can|could|may|might|will|would|must|shall|should"
    + r"|[a-z]{3,}(?:s|ed))"
)


@dataclass(frozen=True, slots=True)
class AssertionWitness:
    """Prepared literal evidence; quantity frames retain units and operators."""

    body: str
    clauses: frozenset[str]
    quantities: frozenset[tuple[str, str]]
    negated: frozenset[str]
    categorical: frozenset[str]
    prose: tuple[str, ...]


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def assertion_witness(body: str) -> AssertionWitness:
    """Extract complete prose spans, excluding headings and fenced examples."""
    prose: list[str] = []
    fence = ""
    width = 0
    for line in body.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, rest = marker.groups()
            if not fence:
                fence, width = run[0], len(run)
            elif run[0] == fence and len(run) >= width and not rest.strip():
                fence = ""
            prose.append("")
            continue
        if not fence and not re.match(r"^ {0,3}#{1,6}(?:\s|$)", line):
            prose.append(line)

    clauses: set[str] = set()
    quantities: set[tuple[str, str]] = set()
    negated: set[str] = set()
    categorical: set[str] = set()
    for part in re.split(r"(?<=[.!?])\s+|\n\s*\n", "\n".join(prose)):
        clause = _normalize(part)
        words = [match.group() for match in _WORDS.finditer(clause)]
        category = _CATEGORICAL.fullmatch(clause)
        if category and not SUBJECT_FUNCTIONS.intersection(
            match.group() for match in _WORDS.finditer(category[1])
        ):
            # Only an explicit attribute with one atomic value is masked.
            # A bare subject ("the cistern is red/heavy") is not an attribute.
            categorical.add(category[1])
        declared = False
        for index, word in enumerate(words[1:-1], start=1):
            subject = words[:index]
            if subject[0] in {"the", "a", "an"}:
                subject = subject[1:]
            if (1 <= len(subject) <= 3
                    and not SUBJECT_FUNCTIONS.intersection(subject)
                    and word not in SUBJECT_FUNCTIONS
                    and _PREDICATE.fullmatch(word)):
                declared = True
                break
        if len(words) >= 3 and declared:
            clauses.add(clause)
            positive, count = _NEGATED.subn(r"\1", clause)
            if count == 1:
                negated.add(positive)
        if len(words) >= 2:
            for value in _VALUE.finditer(clause):
                prefix = clause[:value.start()]
                if _VALUE_POSITION.search(prefix):
                    # Mask one value only; every identifier, scope, other value,
                    # unit and comparator stays literal in the shared frame.
                    quantities.add((prefix, clause[value.end():]))
    return AssertionWitness(
        _normalize(body), frozenset(clauses),
        frozenset(quantities), frozenset(negated), frozenset(categorical),
        tuple(_normalize(part) for part in re.split(
            r"(?<=[.!?])\s+|(?<=[。！？])\s*|\n\s*\n", "\n".join(prose),
        ) if part.strip()),
    )


def lexical_reason(
    first: AssertionWitness, second: AssertionWitness,
) -> Literal["duplicate", "overlap-or-conflict"] | None:
    """Require a shared complete assertion or one bounded changed assertion."""
    if first.body and first.body == second.body:
        return "duplicate"
    if first.clauses & second.clauses or first.quantities & second.quantities or \
            first.categorical & second.categorical or \
            first.negated & second.clauses or second.negated & first.clauses:
        return "overlap-or-conflict"
    return None
