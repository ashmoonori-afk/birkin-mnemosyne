"""VaultMemory ↔ Mnemosyne integration: zone placement, access recording,
zone-aware render, and the new memory tools."""

from __future__ import annotations
import config

from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne
from birkin_mnemosyne import VaultMemory


def _mem() -> VaultMemory:
    return VaultMemory(config.load_config())


def _vault() -> Path:
    return config.vault_dir(config.load_config())


# ---------------- placement -------------------------------------------------

def test_new_note_lands_in_type_zone():
    m = _mem()
    p = m.write_note("Roadmap", "the plan", note_type="project")
    assert p.parent.name == "projects"
    p2 = m.write_note("Profile - lang", "korean", note_type="preference")
    assert p2.parent.name == "identity"


def test_explicit_zone_overrides_type_map():
    m = _mem()
    p = m.write_note("Budget 2026", "numbers", note_type="fact",
                     zone="finance")
    assert p.parent.name == "finance"


def test_write_note_refuses_to_write_into_archive():
    m = _mem()
    with pytest.raises(ValueError, match="archive"):
        m.write_note("Sneaky", "x", zone=mnemosyne.ARCHIVE_ZONE)
    assert m.get_note("Sneaky") is None
    assert not (_vault() / "archive").exists()


def test_write_note_inbox_zone_lands_at_vault_root():
    m = _mem()
    p = m.write_note("Rooted", "x", zone="inbox")
    assert p.parent == _vault()
    p2 = m.write_note("Rooted too", "x", zone="  INBOX ")
    assert p2.parent == _vault()


@pytest.mark.parametrize("bad", ["\u65e5\u672c\u8a9e", "Ops Notes", "a_b",
                                 "-lead", "x" * 33])
def test_write_note_rejects_zone_names_rezone_would_reject(bad):
    m = _mem()
    with pytest.raises(ValueError, match="zone"):
        m.write_note("Odd zone", "x", zone=bad)
    assert m.get_note("Odd zone") is None


def test_write_note_zone_is_lowercased_like_the_mcp_tool():
    m = _mem()
    p = m.write_note("Cased", "x", zone="DevOps")
    assert p.parent.name == "devops"
    m.rezone("Cased", "devops")           # rezone accepts what write_note made


def test_write_note_enforces_zone_cap_for_new_zones_only():
    m = _mem()
    for i in range(mnemosyne.MAX_ZONES):
        m.write_note(f"Cap {i}", "x", zone=f"z{i}")
    with pytest.raises(ValueError, match="zone cap"):
        m.write_note("One too many", "x", zone="brand-new")
    assert m.get_note("One too many") is None
    m.write_note("Fits", "x", zone="z0")  # an existing zone is still fine
    m.write_note("Typed", "x", note_type="project")   # default map unaffected


def test_search_zone_inbox_finds_root_notes():
    m = _mem()
    m.write_note("Loose banana", "banana split", zone="inbox")
    m.write_note("Filed banana", "banana bread", zone="baking")
    hits = m.dex.search("banana", zone="inbox")
    assert [h["slug"] for h in hits] == ["loose-banana"]


def test_update_never_moves_an_existing_note():
    m = _mem()
    # legacy flat note (inbox = vault root)
    p1 = m.write_note("Legacy", "old world", zone="inbox")
    assert p1.parent == _vault()
    p2 = m.write_note("Legacy", "updated body", note_type="project")
    assert p2 == p1                       # stayed in place despite type zone
    assert "updated body" in m.get_note("Legacy")


def test_get_note_finds_note_inside_zone_dir():
    m = _mem()
    m.write_note("Deep", "inside a zone", note_type="person")
    assert "inside a zone" in m.get_note("Deep")


# ---------------- access recording ------------------------------------------

def test_write_and_get_note_potentiate_but_search_does_not():
    m = _mem()
    m.write_note("Tracked", "observable body")
    s = mnemosyne.slug("Tracked")
    assert m.dex.dynamics_of(s)["access_count"] == 1     # write = access
    m.get_note("Tracked")
    assert m.dex.dynamics_of(s)["access_count"] == 2     # read = access
    m.search("observable")
    assert m.dex.dynamics_of(s)["access_count"] == 2     # browse ≠ access


def test_dynamics_survive_index_rebuild():
    m = _mem()
    m.write_note("Durable", "state outlives cache")
    s = mnemosyne.slug("Durable")
    m.get_note("Durable")
    before = m.dex.dynamics_of(s)["access_count"]
    (_vault() / mnemosyne.INDEX_FILE).unlink()           # kill the cache
    m2 = _mem()
    m2.search("state")                                    # forces rebuild
    assert m2.dex.dynamics_of(s)["access_count"] == before


# ---------------- search facade ----------------------------------------------

def test_search_returns_compat_keys_plus_zone_and_related():
    m = _mem()
    m.write_note("Linked", "target of links")
    m.write_note("Source", "carrot payload", links=["Linked"])
    hits = m.search("carrot")
    assert hits and hits[0]["title"] == "source"          # slug (compat)
    assert "snippet" in hits[0] and hits[0]["zone"]
    assert "linked" in hits[0].get("related", [])


def test_search_korean_via_vaultmemory():
    m = _mem()
    m.write_note("회의 기록", "구역 우선순위 논의")
    hits = m.search("우선순위")
    assert hits and hits[0]["title"] == mnemosyne.slug("회의 기록")


# ---------------- render -----------------------------------------------------

def test_render_orders_identity_first_and_labels_inbox():
    m = _mem()
    m.write_note("Profile - name", "ash", note_type="preference")
    m.write_note("Some Fact", "knowledge item", note_type="fact")
    m.write_note("Loose", "unfiled thing", zone="inbox")
    digest = m.render()
    assert digest.index("identity") < digest.index("knowledge")
    assert "inbox" in digest
    assert "[[Profile - name]]" in digest


def test_render_keeps_polarity_warning():
    m = _mem()
    m.write_note("Bad Path", "this failed before", polarity="negative")
    assert "known failure" in m.render()


def test_render_excludes_archive_zone():
    m = _mem()
    m.write_note("Buried", "archived away")
    m.rezone("Buried", mnemosyne.ARCHIVE_ZONE)
    assert "Buried" not in m.render()


# ---------------- tools -------------------------------------------------------


# ---------------- maintenance --------------------------------------------------

def test_purge_expired_reaches_zone_subdirectories():
    import re
    m = _mem()
    m.write_note("Ephemeral", "gone soon", note_type="fact", ttl_days=1)
    p = _vault() / "knowledge" / "ephemeral.md"
    text = re.sub(r"expires_at: .+", "expires_at: 2020-01-01",
                  p.read_text(encoding="utf-8"))
    p.write_text(text, encoding="utf-8")
    assert m.purge_expired() == 1
    assert not p.exists()


def test_reindex_returns_stats():
    m = _mem()
    m.write_note("S1", "alpha", note_type="fact")
    m.write_note("S2", "beta", note_type="project")
    stats = m.reindex()
    assert stats["notes"] == 2 and stats["zones"] >= 2
