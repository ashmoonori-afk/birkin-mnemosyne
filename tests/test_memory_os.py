"""Tests for Memory OS (P5): polarity (positive / negative known-failures),
version (optimistic lock), and opt-in evidence-gated writes."""

from __future__ import annotations
import config

import pytest

from birkin_mnemosyne import VaultMemory, VersionMismatchError


# ---------------- Polarity --------------------------------------------------

def test_polarity_defaults_to_positive():
    m = VaultMemory(config.load_config())
    p = m.write_note("PolarityDefault", "alpha", note_type="fact",
                     source="manual")
    txt = p.read_text(encoding="utf-8")
    assert "polarity: positive" in txt


def test_polarity_negative_persisted():
    m = VaultMemory(config.load_config())
    p = m.write_note("KnownFailureX", "do not retry without context",
                     note_type="fact", polarity="negative", source="manual")
    txt = p.read_text(encoding="utf-8")
    assert "polarity: negative" in txt


def test_polarity_rejected_when_invalid():
    m = VaultMemory(config.load_config())
    with pytest.raises(ValueError):
        m.write_note("BadPolarity", "x", polarity="confused", source="manual")


def test_render_marks_negative_notes():
    m = VaultMemory(config.load_config())
    m.write_note("GoodNote", "ok", note_type="fact", source="manual")
    m.write_note("BadOutcome", "do not do this again", note_type="fact",
                 polarity="negative", source="manual")
    digest = m.render()
    # GoodNote unmarked, BadOutcome flagged as a known failure.
    assert "[[GoodNote]] (fact):" in digest
    assert "⚠ known failure — re-verify" in digest
    assert "[[BadOutcome]] (fact) ⚠ known failure — re-verify" in digest


def test_polarity_preserved_on_subsequent_write():
    """Re-writing a note without specifying polarity must keep the prior value."""
    m = VaultMemory(config.load_config())
    m.write_note("KeepFlag", "first", note_type="fact",
                 polarity="negative", source="manual")
    # second write — no polarity argument; existing "negative" must survive.
    m.write_note("KeepFlag", "second", note_type="fact", source="manual",
                 append=True)
    nodes = {n["title"]: n for n in m.list_notes()}
    assert nodes["KeepFlag"]["polarity"] == "negative"


# ---------------- Version (optimistic lock) ---------------------------------

def test_version_starts_at_one_and_increments():
    m = VaultMemory(config.load_config())
    p = m.write_note("VersionA", "v1", source="manual")
    assert "version: 1" in p.read_text(encoding="utf-8")
    p = m.write_note("VersionA", "v2", source="manual", append=True)
    assert "version: 2" in p.read_text(encoding="utf-8")
    p = m.write_note("VersionA", "v3", source="manual", append=True)
    assert "version: 3" in p.read_text(encoding="utf-8")


def test_expected_version_matches_passes():
    m = VaultMemory(config.load_config())
    m.write_note("OptLock", "v1", source="manual")
    # current version is 1 — matched expectation succeeds and bumps to 2.
    p = m.write_note("OptLock", "v2", source="manual",
                     expected_version=1, append=True)
    assert "version: 2" in p.read_text(encoding="utf-8")


def test_expected_version_mismatch_raises():
    m = VaultMemory(config.load_config())
    m.write_note("OptLockB", "v1", source="manual")
    m.write_note("OptLockB", "v2", source="manual", append=True)   # now v2
    with pytest.raises(VersionMismatchError):
        m.write_note("OptLockB", "concurrent edit", source="manual",
                     expected_version=1, append=True)


def test_expected_version_zero_on_brand_new_note():
    """For a not-yet-existing note, on-disk version is 0; expected_version=0 OK."""
    m = VaultMemory(config.load_config())
    p = m.write_note("FreshLock", "v1", source="manual", expected_version=0)
    assert "version: 1" in p.read_text(encoding="utf-8")


def test_expected_version_mismatch_on_new_note_raises():
    m = VaultMemory(config.load_config())
    with pytest.raises(VersionMismatchError):
        m.write_note("FreshLockBad", "v1", source="manual",
                     expected_version=5)


# ---------------- Evidence gate (opt-in) ------------------------------------

def test_evidence_gate_off_by_default_allows_sourceless_writes():
    """Default config has no evidence_required flag; sourceless writes are
    still accepted (preserving backwards-compatible behavior)."""
    cfg = config.load_config()
    assert not cfg.get("evidence_required")
    m = VaultMemory(cfg)
    p = m.write_note("NoSourceDefault", "x", note_type="fact")
    assert p.is_file()


def test_evidence_gate_when_enabled_blocks_new_note_without_source():
    cfg = config.load_config()
    cfg["evidence_required"] = True
    m = VaultMemory(cfg)
    with pytest.raises(ValueError):
        m.write_note("NoSourceStrict", "x", note_type="fact")


def test_evidence_gate_when_enabled_allows_when_source_present():
    cfg = config.load_config()
    cfg["evidence_required"] = True
    m = VaultMemory(cfg)
    p = m.write_note("WithSourceStrict", "x", note_type="fact",
                     source="manual")
    assert p.is_file()


def test_evidence_gate_when_enabled_allows_subsequent_writes_via_prior_source():
    """If a note already has sources, evidence_required is satisfied on update."""
    cfg = config.load_config()
    m = VaultMemory(cfg)
    m.write_note("Carryover", "first", source="manual")
    cfg["evidence_required"] = True   # turn on for the *next* write
    m2 = VaultMemory(cfg)
    p = m2.write_note("Carryover", "second", append=True)
    assert p.is_file()


# ---------------- Tool layer (memory_write_note) ----------------------------


