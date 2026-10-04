"""Offline assertion evidence from the existing prepared static encoder."""

from __future__ import annotations

import hashlib
import json
import math
import re
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from ._assertion_witness import AssertionWitness
from .semantic import model_dir

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

_FILES: Final = (
    "meta.json", "keys.npy", "ids.npy", "scores.npy", "scale.npy", "emb_int8.npy",
)
# Ambiguous plural nouns (records, logs, stores, locks, ...) are not predicates.
# Unsupported grammar abstains; this is not a general-purpose entailment model.
_VERB: Final = frozenset((
    "keeps retains preserves maintains closes shuts opens unlocks requires "
    + "demands permits allows prohibits forbids rejects accepts deletes removes "
    + "erases encrypts decrypts expires consumes saves"
).split())
_WORDS: Final = re.compile(r"[a-z]+")


class Encoder(Protocol):
    """Typed boundary for the existing unannotated static runtime."""

    dim: int

    def encode(self, texts: list[str]) -> NDArray[np.float32]: ...

    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Configuration:
    cosine: float
    margin: float

    @classmethod
    def parse(cls, thresholds: Mapping[str, float] | None) -> Configuration:
        """Snapshot the two protocol controls, refusing ignored parameters."""
        if thresholds is None or set(thresholds) != {"cosine", "margin"}:
            raise ValueError("semantic thresholds require exactly cosine and margin")
        cosine, margin = thresholds["cosine"], thresholds["margin"]
        if isinstance(cosine, bool) or isinstance(margin, bool) or \
                not math.isfinite(cosine) or not math.isfinite(margin) or \
                not 0 <= cosine <= 1 or not 0 <= margin <= 1:
            raise ValueError("semantic thresholds must be finite values in [0, 1]")
        return cls(float(cosine), float(margin))


@dataclass(frozen=True, slots=True)
class Assertion:
    clause: str
    subject: str
    predicate: str
    argument: str

    @property
    def topic(self) -> str:
        return f"{self.subject} {self.argument}"


def _assertions(witness: AssertionWitness) -> tuple[Assertion, ...]:
    """Only admit single finite-verb frames with literal subject and argument.

    This deliberately does not infer scope, pronoun resolution or entailment.
    Sentence cosine cannot substitute for these matching assertion anchors.
    """
    result: list[Assertion] = []
    for clause in sorted(witness.clauses):
        text = clause.rstrip(".!?")
        words = list(_WORDS.finditer(text))
        for word in words[1:-1]:
            subject = text[:word.start()].strip()
            subject_words = subject.split()
            if subject_words and subject_words[0] in {"the", "a", "an"}:
                subject_words = subject_words[1:]
            if not 1 <= len(subject_words) <= 3:
                continue
            if word.group() in _VERB:
                argument = text[word.end():].strip()
                # Refuse joined/subordinate clauses rather than resolve scope.
                if re.search(
                    r"[,;:\n]|\b(?:and|or|but|if|when|while|that|which"
                    + r"|is|are|was|were|has|have|can|may|must|will)\b",
                    argument,
                ):
                    break
                result.append(Assertion(
                    text, " ".join(subject_words), word.group(), argument,
                ))
                break
    return tuple(result)


class SemanticQuestions:
    """Read prepared assets only; readiness requires a finite nonzero encode."""

    def __init__(self, configuration: Configuration) -> None:
        self.configuration: Configuration = configuration
        self.status: str = "unavailable"
        self.error: str = ""
        self.encoded_chunks: int = 0
        self.identity: str = ""
        self._path: Path = model_dir().resolve()
        self._assets: tuple[tuple[str, int, int, str], ...] = ()
        self._model: Encoder | None = None
        self._vectors: dict[str, tuple[float, ...]] = {}
        try:
            from .static_model import StaticModel

            self._assets = self._fingerprint()
            self._model = StaticModel(self._path)
            self._encode(["The amber relay retains audit records."])
            self.identity = hashlib.sha256(json.dumps(
                ("assertion-frame-v1", configuration.cosine, configuration.margin,
                 str(self._path), self._assets,
                 hashlib.sha256((self._path / "meta.json").read_bytes()).hexdigest()),
                separators=(",", ":"),
            ).encode()).hexdigest()
            self.status = "ready"
        except (ImportError, OSError, ValueError, KeyError, TypeError, IndexError,
                EOFError) as exc:
            self.error = str(exc)
        finally:
            if self._model is not None:
                self._model.release()
            self.encoded_chunks = 0
            self._vectors.clear()

    def _fingerprint(self) -> tuple[tuple[str, int, int, str], ...]:
        assets: list[tuple[str, int, int, str]] = []
        for name in _FILES:
            path = self._path / name
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            assets.append((name, stat.st_size, stat.st_mtime_ns, digest.hexdigest()))
        return tuple(assets)

    def _encode(self, texts: list[str]) -> None:
        if self._model is None:
            raise ValueError("prepared encoder is unavailable")
        missing = list(dict.fromkeys(t for t in texts if t and t not in self._vectors))
        if not missing:
            return
        vectors = self._model.encode(missing)
        if vectors.shape != (len(missing), self._model.dim):
            raise ValueError("prepared encoder produced an invalid shape")
        flat = array("f", vectors.tobytes())
        width = self._model.dim
        for index, text in enumerate(missing):
            vector = tuple(flat[index * width:(index + 1) * width])
            norm = math.sqrt(sum(value * value for value in vector))
            if not norm or not math.isfinite(norm) or \
                    not all(math.isfinite(value) for value in vector):
                raise ValueError("prepared encoder produced invalid or zero vectors")
            self._vectors[text] = tuple(value / norm for value in vector)
        self.encoded_chunks += len(missing)

    def _cosine(self, first: str, second: str) -> float:
        return max(-1.0, min(1.0, sum(
            a * b for a, b in zip(self._vectors[first], self._vectors[second])
        )))

    def current(self) -> bool:
        """Refuse a changed runtime before either discovery or applying answers."""
        if self.status != "ready":
            return False
        try:
            if self._fingerprint() != self._assets:
                raise ValueError("prepared model assets changed; construct a new service")
        except (OSError, ValueError) as exc:
            self.status = "unavailable"
            self.error = str(exc)
            return False
        return True

    def evidence(
        self, witnesses: Sequence[AssertionWitness],
    ) -> dict[tuple[int, int], float] | None:
        """Require aligned anchors, semantic predicates and a topic margin.

        The margin compares predicate agreement with each predicate's affinity
        to the shared topic. It is not a nearest-neighbor gap: unrelated notes
        cannot change whether an assertion pair qualifies.
        """
        self.encoded_chunks = 0
        if not self.current():
            return None
        try:
            assertions = [_assertions(w) for w in witnesses]
            texts = [w.body for w in witnesses]
            for group in assertions:
                for assertion in group:
                    texts.extend((assertion.clause, assertion.predicate, assertion.topic))
            self._encode(texts)
            result: dict[tuple[int, int], float] = {}
            frames: dict[tuple[str, str], list[tuple[int, Assertion]]] = {}
            for index, group in enumerate(assertions):
                for assertion in group:
                    key = (assertion.subject, assertion.argument)
                    for other_index, other in frames.get(key, ()):
                        if index == other_index:
                            continue
                        cosine = self._cosine(assertion.clause, other.clause)
                        predicate = self._cosine(assertion.predicate, other.predicate)
                        topic = max(
                            self._cosine(assertion.predicate, assertion.topic),
                            self._cosine(other.predicate, other.topic),
                        )
                        if cosine >= self.configuration.cosine and \
                                predicate > 0 and \
                                predicate - topic >= self.configuration.margin:
                            pair = (other_index, index)
                            result[pair] = max(result.get(pair, -1.0), cosine)
                    frames.setdefault(key, []).append((index, assertion))
            return result
        except (OSError, ValueError, KeyError, TypeError, IndexError, EOFError) as exc:
            self.status = "unavailable"
            self.error = str(exc)
            self._vectors.clear()
            return None
        finally:
            if self._model is not None:
                self._model.release()
