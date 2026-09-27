from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .curation_apply import apply_plan
from .curation_contract import (
    CurationOutcome,
    sanitize_model_record,
    sanitize_summary,
)
from .curation_gate import _dense_zone_links, validate_clamp
from .curation_prompt import (
    build_plan_prompt,
    extract_plan,
    mechanical_catalog,
)
from .mnemosyne import ARCHIVE_ZONE, Mnemosyne


def _snapshot(dex: Mnemosyne) -> dict[str, dict[str, Any]]:
    return {s: {"zone": e["zone"], "type": e["type"],
                "polarity": e["polarity"], "links": e["links"]}
            for s, e in dex.entries().items()
            if e["zone"] != ARCHIVE_ZONE}


def evaluate_plan(vault: Path, plan: dict[str, Any], *, apply: bool = False,
                  provider: str = "?", model: str | None = None,
                  raw_text: str = "",
                  now: datetime | None = None) -> CurationOutcome:
    """Run a CurationPlan/1 through the deterministic gate.

    The plan is validated and clamped against the vault's *current* state
    (archive cap, protected notes, known slugs, zone names) and expanded with
    dense zone links. With ``apply=False`` (the default) nothing is applied:
    no note or dynamics file changes (the index cache may still be refreshed)
    and ``effected`` is empty. With ``apply=True`` the accepted ops are
    applied exactly as :func:`run_curation_pass` does.
    """
    now = now or datetime.now(timezone.utc)
    dex = Mnemosyne(vault)
    dex.refresh()
    snap = _snapshot(dex)
    gate = validate_clamp(plan, dex, snap, now=now)
    accepted = _dense_zone_links(gate.accepted, snap)
    effected = apply_plan(accepted, vault, dex) if apply else []
    ops = plan.get("ops", [])
    return CurationOutcome(
        provider=provider, model=model,
        accepted=[sanitize_model_record(o) for o in accepted],
        dropped=[{"op": sanitize_model_record(d.op),
                  "reason": sanitize_summary(d.reason)}
                 for d in gate.dropped],
        effected=effected, archive_cap=gate.archive_cap,
        summary=sanitize_summary(str(plan.get("summary", ""))),
        raw_text=sanitize_summary(raw_text)[:4000],
        plan_ops=len(ops) if isinstance(ops, list) else 0,
        dry_run=not apply)


def run_curation_pass(vault: Path, complete: Callable[[str], str], *,
                      provider: str = "?", model: str | None = None,
                      untrusted: str = "",
                      now: datetime | None = None) -> CurationOutcome:
    now = now or datetime.now(timezone.utc)
    dex = Mnemosyne(vault)
    dex.refresh()
    prompt = build_plan_prompt(mechanical_catalog(dex, now=now),
                               untrusted=untrusted)
    raw = complete(prompt) or ""
    return evaluate_plan(vault, extract_plan(raw), apply=True,
                         provider=provider, model=model, raw_text=raw,
                         now=now)
