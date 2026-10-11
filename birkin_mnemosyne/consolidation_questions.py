"""Pure similarity scoring, independent of review services and snapshot types."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CandidateScore:
    first: int
    second: int
    reason: Literal["duplicate", "overlap-or-conflict"]
    similarity: float


def score_pairs(
    bodies: Sequence[str], terms: Sequence[set[str]], pairs: Iterable[tuple[int, int]],
) -> tuple[CandidateScore, ...]:
    """Score the existing bounded pairs without filesystem, cache or service imports."""
    result: list[CandidateScore] = []
    for i, j in sorted(pairs):
        common = terms[i] & terms[j]
        union = terms[i] | terms[j]
        similarity = len(common) / len(union) if union else 0.0
        same = " ".join(bodies[i].split()).casefold() == " ".join(bodies[j].split()).casefold()
        if not same and (len(common) < 3 or similarity < 0.55):
            continue
        result.append(CandidateScore(i, j, "duplicate" if same else "overlap-or-conflict", similarity))
    return tuple(result)
