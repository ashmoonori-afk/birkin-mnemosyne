"""Protected-memory capacity: report, budget warning, retire candidates.

The "filed + linked" protection rule is unchanged. A budget only warns and,
through the review flow, asks the user about the oldest/least-used protected
notes. Nothing here moves or deletes a note: every function is read-only and
uses index metadata only (no note bodies are read).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .curation import _snapshot
from .curation_gate import _is_protected
from .memory_index import MemoryIndex
from .mnemosyne import Mnemosyne, _parse_dt

ENV_MAX_PROTECTED = "MNEMOSYNE_MAX_PROTECTED_NOTES"
ENV_MAX_BYTES = "MNEMOSYNE_MAX_VAULT_BYTES"
DEFAULT_MAX_PROTECTED = 1000
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
_OLDEST = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class CapacityBudget:
    """Limits for active notes; ``None`` or ``0`` means no limit."""

    max_protected: int | None
    max_bytes: int | None

    def __post_init__(self) -> None:
        for name in ("max_protected", "max_bytes"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer")


DEFAULT_BUDGET = CapacityBudget(DEFAULT_MAX_PROTECTED, DEFAULT_MAX_BYTES)


def parse_limit(name: str, raw: str) -> int:
    """One budget value; invalid input raises a ValueError naming ``name``."""
    text = raw.strip()
    if not text.isdigit():
        raise ValueError(f"{name} must be a non-negative integer "
                         f"(0 disables the limit), got {raw!r}")
    return int(text)


def budget_from_env(environ: Mapping[str, str] = os.environ) -> CapacityBudget:
    def read(name: str, default: int) -> int:
        raw = environ.get(name)
        return default if raw is None else parse_limit(name, raw)
    return CapacityBudget(read(ENV_MAX_PROTECTED, DEFAULT_MAX_PROTECTED),
                          read(ENV_MAX_BYTES, DEFAULT_MAX_BYTES))


def _over(value: int, limit: int | None) -> bool:
    return bool(limit) and value > (limit or 0)


def _scan(dex: Mnemosyne) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Active entries and the protected subset, on the gate's own snapshot."""
    entries = dex.entries()
    snap = _snapshot(dex)
    active = {s: entries[s] for s in snap if s in entries}
    return active, {s for s in active if _is_protected(dex, s, snap)}


def capacity_report(dex: Mnemosyne, budget: CapacityBudget) -> dict[str, Any]:
    active, protected = _scan(dex)
    index = MemoryIndex(dex.vault).read()
    size = sum(int(e.get("size") or 0) for e in active.values())
    over = {"protected": _over(len(protected), budget.max_protected),
            "bytes": _over(size, budget.max_bytes)}
    warnings: list[str] = []
    if over["protected"]:
        warnings.append(
            f"{len(protected)} protected notes exceed the budget of "
            f"{budget.max_protected}; ask the user which old ones to retire "
            "(memory_review_questions). Nothing is deleted automatically.")
    if over["bytes"]:
        warnings.append(
            f"active notes use {size} bytes, over the budget of "
            f"{budget.max_bytes}; ask the user which old protected notes to "
            "retire (memory_review_questions). Nothing is deleted "
            "automatically.")
    warnings.extend(index.warnings)
    return {"notes": len(active), "protected": len(protected), "bytes": size,
            "budget": {"max_protected": budget.max_protected,
                       "max_bytes": budget.max_bytes},
            "always_loaded": {
                "enabled": index.enabled, "index_entries": len(index.entries),
                "estimated_tokens": index.estimated_tokens,
                "max_tokens": index.max_tokens, "over_budget": index.over_budget,
                "estimator": "ceil(UTF-8 bytes / 4)",
            },
            "over_budget": over, "warnings": warnings}


def retire_candidates(dex: Mnemosyne, budget: CapacityBudget,
                      limit: int) -> list[dict[str, Any]]:
    """Oldest/least-used protected notes, only as many as bring the vault
    back under budget (at most ``limit``). Empty when under budget."""
    active, protected = _scan(dex)
    count = len(protected)
    size = sum(int(e.get("size") or 0) for e in active.values())
    if limit < 1 or not (_over(count, budget.max_protected)
                         or _over(size, budget.max_bytes)):
        return []
    rows: list[tuple[tuple[datetime, int, float, str], dict[str, Any]]] = []
    for s in protected:
        e = active[s]
        dyn = dex.dynamics_of(s)
        last = str(dyn.get("last_access") or "")
        try:
            uses = int(dyn.get("access_count") or 0)
        except (TypeError, ValueError):
            uses = 0
        key = (_parse_dt(last) or _OLDEST, uses, float(e.get("mtime") or 0.0), s)
        rows.append((key, {"slug": s, "rel": e["rel"], "title": e["title"],
                           "last_access": last,
                           "access_count": uses,
                           "size": int(e.get("size") or 0)}))
    rows.sort(key=lambda r: r[0])
    picks: list[dict[str, Any]] = []
    for _, row in rows:
        if len(picks) >= limit or not (_over(count, budget.max_protected)
                                       or _over(size, budget.max_bytes)):
            break
        picks.append(row)
        count -= 1
        size -= row["size"]
    return picks
