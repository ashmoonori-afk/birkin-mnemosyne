"""Opt-in experiment contracts exercised through real vaults and search."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def note(vault: Path, slug: str, title: str, body: str,
         tags: str = "") -> Path:
    path = vault / f"{slug}.md"
    _ = path.write_text(
        f"---\ntitle: {title}\ntags: [{tags}]\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_field_weight_rewards_title_and_tags_without_changing_length(tmp_path: Path) -> None:
    # Given: equal aggregate token frequencies in different fields.
    note(tmp_path, "body", "memo", "orchard memo")
    note(tmp_path, "title", "orchard", "memo memo")
    note(tmp_path, "tags", "memo", "memo", "orchard")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    base = plain.search("orchard", now=NOW)
    # When: title and tag frequencies are weighted.
    weighted = mnemosyne.Mnemosyne(
        tmp_path, semantic=False, field_aware=True, title_weight=2, tag_weight=1.5)
    hits = weighted.search("orchard", now=NOW)
    # Then: field evidence increases saturation score, not document length.
    assert [h["slug"] for h in hits] == ["title", "tags", "body"]
    assert len({h["score"] for h in base}) == 1
    assert {s: e["doclen"] for s, e in weighted.entries().items()} == {
        s: e["doclen"] for s, e in plain.entries().items()}


@pytest.mark.parametrize("query", ["김장 배추", "豚骨スープ", "搬家准备", "orchard deployment"])
def test_unit_field_weights_have_exact_score_parity(tmp_path: Path, query: str) -> None:
    # Given: multilingual fields with repeats and script transitions.
    note(tmp_path, "a", "김장 豚骨スープ", "배추 搬家准备 orchard deployment", "김장, orchard")
    note(tmp_path, "b", "orchard", "deployment 배추 배추 豚骨スープ")
    plain = mnemosyne.Mnemosyne(tmp_path, semantic=False).search(query, now=NOW)
    # When: separate frequencies all receive unit weights.
    unit = mnemosyne.Mnemosyne(
        tmp_path, semantic=False, field_aware=True, title_weight=1, tag_weight=1)
    # Then: serialized hits are exactly identical, including scores.
    assert json.dumps(unit.search(query, now=NOW)) == json.dumps(plain)


def test_field_cache_is_backfilled_and_default_entries_remain_original(tmp_path: Path) -> None:
    # Given: a legacy cache created by the default parser.
    note(tmp_path, "a", "orchard", "deployment", "project")
    original = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    original.rebuild()
    original_entries = original.entries()
    # When: opt-in scoring loads the old cache and then is disabled.
    enabled = mnemosyne.Mnemosyne(tmp_path, semantic=False, field_aware=True)
    enabled.search("orchard", now=NOW)
    disabled = mnemosyne.Mnemosyne(tmp_path, semantic=False)
    # Then: fields are populated only for the opt-in engine.
    assert enabled.entries()["a"]["field_terms"]["title"] == {"orchard": 1, "orcha~": 1}
    assert disabled.entries() == original_entries


@pytest.mark.parametrize("weight", [0, -1, float("inf"), float("nan")])
def test_invalid_field_weights_are_rejected_at_constructor(tmp_path: Path, weight: float) -> None:
    # Given/When: an invalid public configuration.
    with pytest.raises(ValueError, match="finite and positive"):
        mnemosyne.Mnemosyne(tmp_path, field_aware=True, title_weight=weight)
