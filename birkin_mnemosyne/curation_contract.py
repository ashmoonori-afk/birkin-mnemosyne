from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PLAN_VERSION = 1
ARCHIVE_CAP_FRACTION = 0.20
ARCHIVE_CAP_MIN = 2
PROTECT_TYPES = {"identity", "preference"}
OPS = {"rezone", "link", "supersede", "archive"}
# Dense zone links: each note a plan moves into a zone is linked to at most
# DENSE_LINK_LIMIT zone-mates, and one plan expands to at most
# MAX_DENSE_LINKS links (the same size as the 500-op plan limit).
DENSE_LINK_LIMIT = 10
MAX_DENSE_LINKS = 500

FORBIDDEN_PHRASE_TOKENS = ("ALL", "NOTES", "ARCHIVED", "SUCCESSFULLY")
_FORBIDDEN_RE = re.compile(r"\s*".join(FORBIDDEN_PHRASE_TOKENS),
                           re.IGNORECASE)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


@dataclass
class OpResult:
    op: dict[str, Any]
    reason: str


@dataclass
class GateResult:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[OpResult] = field(default_factory=list)
    archive_cap: int = 0

    def drop(self, op: dict[str, Any], reason: str) -> None:
        self.dropped.append(OpResult(op, reason))


@dataclass
class CurationOutcome:
    provider: str
    model: str | None
    accepted: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    effected: list[dict[str, Any]]
    archive_cap: int
    summary: str
    raw_text: str
    plan_ops: int
    dry_run: bool = False
    dense_links: int = 0   # link ops the executor added on top of the plan


def sanitize_summary(summary: str) -> str:
    import unicodedata
    out = unicodedata.normalize("NFKC", summary or "").translate(_ZERO_WIDTH)
    return _FORBIDDEN_RE.sub("[redacted-canary]", out)


def sanitize_model_record(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_summary(value)
    if isinstance(value, list):
        return [sanitize_model_record(v) for v in value]
    if isinstance(value, dict):
        return {str(k): sanitize_model_record(v) for k, v in value.items()}
    return value
