"""Nested-zone and archive-descendant curation regressions (mn-071).

The four curation surfaces (gate, snapshot, mechanical catalog/prompt and
the handoff fold snapshot) must treat ``_archive``-component zones as what
they are at every depth while keeping the exact full relative zone strings of
active nested notes. Rezone targets go through the shared
``normalize_zone`` contract (nested/human parents accepted and canonicalized
exactly as the actual core rezone would), archive-component targets are
refused so a plan cannot bypass archive caps or protection, and
snapshots/catalogs never leak archive descendants.
"""

from __future__ import annotations
import config

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from birkin_mnemosyne import (
    HANDOFFS_DIRECTORY,
    HandoffFields,
    HandoffScope,
    HandoffStore,
    VaultMemory,
    curation,
    curation_gate,
    curation_prompt,
    handoff_fold,
    mnemosyne,
)
from birkin_mnemosyne.handoff_retention import HandoffRetention
from birkin_mnemosyne.vault_paths import archived_zone

NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)


def _stamp(hour: int) -> str:
    return f"2026-10-11T{hour:02d}:00:00.000000Z"


def _seed_vault() -> tuple[Path, dict[str, str]]:
    """Active notes at several depths plus archive descendants, including a
    case-variant archive folder. Returns slug -> full zone for the entire
    index, descendants included."""
    m = VaultMemory(config.load_config())
    for title in ("Alpha idea", "Beta plan", "Gamma note"):
        m.write_note(title, f"body about {title.lower()}", zone="inbox")
    m.write_note("Work draft", "draft body", zone="work")
    m.write_note("Work log", "log body", zone="work")
    m.write_note("Writing style", "readable prose", zone="work/writing",
                 note_type="fact")
    m.write_note("Ftp danger", "ftp broke the build", zone="work/writing",
                 polarity="negative")
    m.write_note("Owner taste", "keep colors", zone="work/writing",
                 note_type="preference")
    m.write_note("Nested guide", "write plainly", zone="work/writing",
                 note_type="fact", links=["Writing style"])
    m.write_note("Writing style", "readable prose", zone="work/writing",
                 note_type="fact", links=["Nested guide"])
    m.write_note("Old work", "retired draft", zone="work")
    m.rezone("Old work", mnemosyne.ARCHIVE_ZONE)
    m.write_note("Old inbox", "retired idea", zone="inbox")
    m.rezone("Old inbox", mnemosyne.ARCHIVE_ZONE)
    vault = config.vault_dir(config.load_config())
    case = vault / "_ARCHIVE" / "Sub"
    case.mkdir(parents=True)
    (case / "case-buried.md").write_text("case retired fixture",
                                         encoding="utf-8")
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    return vault, {s: e["zone"] for s, e in dex.entries().items()}


def _full_snap(dex: mnemosyne.Mnemosyne) -> dict[str, dict[str, Any]]:
    """Gate snapshot over every indexed note, descendants included, carrying
    the real metadata so protection rules are exercised on the gate."""
    return {s: {"zone": e["zone"], "type": e["type"],
                "polarity": e["polarity"], "links": e["links"]}
            for s, e in dex.entries().items()}


def _meta(dex: mnemosyne.Mnemosyne, s: str) -> dict[str, Any]:
    entry = dex.note_meta(s)
    assert entry is not None, s
    return entry

# ---------------- rezone: shared normalization contract ----------------------


def test_gate_canonicalizes_nested_and_human_rezone_zones():
    vault, _ = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _full_snap(dex)
    pairs = [("alpha-idea", "Projects/2024", "Projects/2024"),
             ("beta-plan", "Deep Work", "Deep Work"),
             ("gamma-note", "PROJECTS", "projects"),
             ("work-draft", "work/writing", "work/writing")]
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": slug, "zone": raw, "reason": "file it"}
        for slug, raw, _ in pairs]}
    g = curation_gate.validate_clamp(plan, dex, snap, now=NOW)
    accepted = [o for o in g.accepted if o["op"] == "rezone"]
    assert [(o["slug"], o["zone"]) for o in accepted] == \
        [(slug, canon) for slug, _, canon in pairs]
    for raw, op in zip(pairs, accepted):
        assert op["zone"] == mnemosyne.normalize_zone(raw[1])
        assert op["reason"] == "file it"


def test_gate_rezone_refuses_archive_component_targets_case_insensitive():
    vault, _ = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _full_snap(dex)
    targets = ["_archive", "_ARCHIVE", " _archive ", "_ archive",
               "_ARCHIVE/sub", "work/_archive", "work/_ArChIvE"]
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": "alpha-idea", "zone": z} for z in targets]}
    g = curation_gate.validate_clamp(plan, dex, snap, now=NOW)
    assert not any(o["op"] == "rezone" for o in g.accepted)
    assert {d.reason for d in g.dropped
            if d.op.get("zone") in (" _archive ", "_ archive", "_ARCHIVE")} \
        == {"rezone_to_archive_rejected"}
    assert len(g.dropped) == len(targets)
    # component targets fall to the shared normalization refusal
    assert any(d.reason == "invalid zone name"
               for d in g.dropped
               if d.op.get("zone") in ("_ARCHIVE/sub", "work/_archive",
                                       "work/_ArChIvE"))


def test_gate_inbox_aliases_are_not_real_rezone_targets():
    vault, _ = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _full_snap(dex)
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": "alpha-idea", "zone": z}
        for z in ("", "inbox", "INBOX", " inbox ")]}
    g = curation_gate.validate_clamp(plan, dex, snap, now=NOW)
    assert not any(o["op"] == "rezone" for o in g.accepted)
    assert all(d.reason == "rezone needs a real zone" for d in g.dropped)


# ---------------- archive caps, already-archived, protection ----------------


def test_gate_archive_cap_and_already_archived_exclude_descendants():
    vault, zones = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _full_snap(dex)
    plan = {"plan_version": 1,
            "ops": [{"op": "archive", "slug": s} for s in snap]}
    g = curation_gate.validate_clamp(plan, dex, snap, now=NOW)
    active = [s for s, z in zones.items() if not archived_zone(z)]
    cap = min(max(2, -(-len(active) * 20 // 100)), max(0, len(active) - 1))
    assert g.archive_cap == cap == 2
    archived = {o["slug"] for o in g.accepted if o["op"] == "archive"}
    assert not archived & {"old-work", "old-inbox", "case-buried"}
    by_slug = {d.op.get("slug"): d.reason for d in g.dropped
               if d.op.get("op") == "archive"}
    assert by_slug["old-work"] == "already archived"
    assert by_slug["old-inbox"] == "already archived"
    assert by_slug["case-buried"] == "already archived"
    assert any(r.startswith("archive_capped") for r in
               {d.reason for d in g.dropped})
    assert "protected note" in {d.reason for d in g.dropped}


def test_gate_protection_rules_apply_to_nested_active_notes():
    vault, _ = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = _full_snap(dex)
    plan = {"plan_version": 1, "ops": [
        {"op": "archive", "slug": "ftp-danger"},
        {"op": "archive", "slug": "owner-taste"},
        {"op": "archive", "slug": "nested-guide"},
        {"op": "archive", "slug": "writing-style"},
        {"op": "archive", "slug": "old-work"},
    ]}
    g = curation_gate.validate_clamp(plan, dex, snap, now=NOW)
    assert not {o["slug"] for o in g.accepted} & {
        "ftp-danger", "owner-taste", "nested-guide", "writing-style",
        "old-work"}
    by_slug = {d.op.get("slug"): d.reason for d in g.dropped}
    assert by_slug["ftp-danger"] == "protected note"
    assert by_slug["owner-taste"] == "protected note"
    assert by_slug["nested-guide"] == "protected note"
    assert by_slug["writing-style"] == "protected note"
    # archived descendants are not filed+linked protected; they are simply
    # already archived
    assert by_slug["old-work"] == "already archived"


# ---------------- snapshot / catalog / prompt exclusion ----------------------


def test_snapshot_and_catalog_exclude_archive_descendants():
    vault, zones = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    snap = curation._snapshot(dex)
    assert "old-work" not in snap and "old-inbox" not in snap
    assert "case-buried" not in snap
    assert "work-draft" in snap and "writing-style" in snap
    catalog = curation_prompt.mechanical_catalog(dex, now=NOW)
    slugs = [n["slug"] for n in catalog["notes"]]
    assert "old-work" not in slugs and "case-buried" not in slugs
    assert catalog["existing_zones"] == ["work", "work/writing"]
    assert {n["zone"] for n in catalog["notes"]
            if n["slug"] == "writing-style"} == {"work/writing"}
    out = curation.evaluate_plan(
        vault, {"plan_version": 1,
                "ops": [{"op": "archive", "slug": "old-work"}]},
        now=NOW)
    # the flow-level snapshot excludes descendants, so an archive op against
    # one is an unknown slug, never a bypass of caps/protection
    assert out.accepted == []
    assert out.dropped == [{"op": {"op": "archive", "slug": "old-work"},
                            "reason": "unknown slug"}]


# ---------------- dense grouping compares complete parents -------------------


def test_dense_zone_links_group_by_complete_parent():
    snap = {s: {"zone": z, "type": "fact", "polarity": "neutral", "links": []}
            for s, z in {"w1": "writing", "w2": "writing", "w3": "writing",
                         "mate": "work/writing", "mover": ""}.items()}
    accepted = [{"op": "rezone", "slug": "mover", "zone": "work/writing"}]
    expanded = curation_gate._dense_zone_links(accepted, snap)
    added = [o for o in expanded[1:] if o["op"] == "link"]
    assert len(added) == 1
    assert {added[0]["a"], added[0]["b"]} == {"mover", "mate"}
    # "writing" shares the final component with "work/writing" but is a
    # different complete parent: no links leak across it
    assert all("w1" not in {o["a"], o["b"]} and "w2" not in {o["a"], o["b"]}
               and "w3" not in {o["a"], o["b"]} for o in added)


# ---------------- actual apply + undo preserve nested paths/bytes ------------


def test_apply_nested_rezone_then_restore_preserves_paths_and_bytes():
    vault, _ = _seed_vault()
    dex = mnemosyne.Mnemosyne(vault)
    deep = (vault / "work" / "deep-note.md")
    deep.write_text("exact original bytes\n", encoding="utf-8")
    spare = (vault / "spare-idea.md")
    spare.write_text("exact old bytes\n", encoding="utf-8")
    dex.refresh()
    deep_bytes, old_bytes = deep.read_bytes(), spare.read_bytes()
    plan = {"plan_version": 1, "ops": [
        {"op": "rezone", "slug": "deep-note", "zone": "Projects/2026"},
        {"op": "archive", "slug": "spare-idea"}]}
    out = curation.evaluate_plan(vault, plan, apply=True, now=NOW)
    dex.refresh()
    assert _meta(dex, "deep-note")["zone"] == "Projects/2026"
    assert _meta(dex, "deep-note")["rel"] == "Projects/2026/deep-note.md"
    assert _meta(dex, "spare-idea")["zone"] == "_archive"
    assert _meta(dex, "spare-idea")["rel"] == "_archive/spare-idea.md"
    assert (vault / "Projects/2026/deep-note.md").read_bytes() == deep_bytes
    assert (vault / "_archive/spare-idea.md").read_bytes() == old_bytes
    # Restore through the existing core rezone, the path memory_restore uses.
    dex.rezone("deep-note", "work")
    dex.rezone("spare-idea", "")
    dex.refresh()
    assert _meta(dex, "deep-note")["rel"] == "work/deep-note.md"
    assert _meta(dex, "spare-idea")["rel"] == "spare-idea.md"
    assert (vault / "work/deep-note.md").read_bytes() == deep_bytes
    assert (vault / "spare-idea.md").read_bytes() == old_bytes
    assert out.dry_run is False


# ---------------- handoff ordinary snapshot exclusion ------------------------


def test_handoff_fold_snapshot_excludes_archive_descendants(tmp_path: Path):
    vault = tmp_path / "vault"
    memory = VaultMemory({"vault_path": str(vault)})
    memory.write_note("Normal note", "body text", source="test")
    memory.write_note("Buried work", "dead", zone="work")
    memory.rezone("Buried work", mnemosyne.ARCHIVE_ZONE)
    case = vault / "_ARCHIVE" / "Sub"
    case.mkdir(parents=True)
    (case / "case-buried.md").write_text("case retired", encoding="utf-8")
    store = HandoffStore(vault)
    scope = HandoffScope("mn-070", "handoff")
    for i in range(8):
        store.capture(scope, HandoffFields(
            work=f"fold work {i}", next_step="n", decisions=(),
            open_items=(), open_questions=(), links=(),
        ), capture_id=f"cap-{i}", now=_stamp(1 + i))
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    managed = handoff_fold.managed_active_notes(vault)
    snap = handoff_fold.snapshot(vault, dex, managed)
    assert "normal-note" in snap
    assert "buried-work" not in snap and "case-buried" not in snap
    managed_keys = [k for k in snap if k.startswith(HANDOFFS_DIRECTORY + "/")]
    assert len(managed_keys) == 8
    result = HandoffRetention(vault).preview(scope, keep=1)
    # the cap counts only active rows: 1 normal + 8 captures = 9
    assert result.plan_archive_cap == min(max(2, -(-9 * 20 // 100)), 8) == 2
    assert len(result.accepted) == 2
