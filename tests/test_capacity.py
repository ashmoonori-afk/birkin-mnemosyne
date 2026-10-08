"""Protected-memory capacity report, budget parsing and retire candidates."""

from __future__ import annotations

import pytest

from birkin_mnemosyne import VaultMemory
from birkin_mnemosyne.capacity import (
    DEFAULT_BUDGET,
    CapacityBudget,
    budget_from_env,
    capacity_report,
    retire_candidates,
)


def seed(vault):
    """Two protected notes (zoned + linked, negative polarity), one plain."""
    memory = VaultMemory({"vault_path": str(vault)})
    memory.write_note("Linked plan", "Quarterly plan body.", zone="work",
                      links=["Plain note"])
    memory.write_note("Bad deploy", "ftp corrupted the build.", zone="inbox",
                      polarity="negative")
    memory.write_note("Plain note", "Nothing special here.", zone="inbox")
    return memory


def test_report_counts_protected_notes_and_index_bytes(tmp_path):
    memory = seed(tmp_path)
    report = capacity_report(memory.dex, DEFAULT_BUDGET)
    assert report["notes"] == 3
    assert report["protected"] == 2
    sizes = sum(p.stat().st_size for p in tmp_path.rglob("*.md"))
    assert report["bytes"] == sizes
    assert report["over_budget"] == {"protected": False, "bytes": False}
    assert report["warnings"] == []
    assert report["budget"] == {"max_protected": 1000, "max_bytes": 104857600}


def test_report_ignores_archived_notes(tmp_path):
    memory = seed(tmp_path)
    memory.dex.rezone("bad-deploy", "_archive")
    report = capacity_report(memory.dex, DEFAULT_BUDGET)
    assert (report["notes"], report["protected"]) == (2, 1)


def test_report_warns_only_when_over_each_dimension(tmp_path):
    memory = seed(tmp_path)
    report = capacity_report(memory.dex, CapacityBudget(1, None))
    assert report["over_budget"] == {"protected": True, "bytes": False}
    assert len(report["warnings"]) == 1
    assert "2 protected notes" in report["warnings"][0]
    report = capacity_report(memory.dex, CapacityBudget(None, 10))
    assert report["over_budget"] == {"protected": False, "bytes": True}
    assert len(report["warnings"]) == 1
    report = capacity_report(memory.dex, CapacityBudget(2, 0))
    assert report["over_budget"] == {"protected": False, "bytes": False}


def test_budget_from_env_defaults_zero_disables_invalid_raises():
    assert budget_from_env({}) == CapacityBudget(1000, 104857600)
    assert budget_from_env({"MNEMOSYNE_MAX_PROTECTED_NOTES": "0",
                            "MNEMOSYNE_MAX_VAULT_BYTES": " 2048 "}) == \
        CapacityBudget(0, 2048)
    for name in ("MNEMOSYNE_MAX_PROTECTED_NOTES", "MNEMOSYNE_MAX_VAULT_BYTES"):
        for bad in ("lots", "-1", "1.5"):
            with pytest.raises(ValueError, match=name):
                budget_from_env({name: bad})
    with pytest.raises(ValueError):
        CapacityBudget(-1, None)


def test_no_candidates_under_budget(tmp_path):
    memory = seed(tmp_path)
    assert retire_candidates(memory.dex, DEFAULT_BUDGET, 10) == []
    assert retire_candidates(memory.dex, CapacityBudget(0, 0), 10) == []


def test_candidates_oldest_then_least_used_and_only_as_many_as_needed(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    for title in ("Alpha", "Beta", "Gamma", "Delta"):
        memory.write_note(title, f"{title} body.", polarity="negative",
                          zone="inbox")
    memory.write_note("Plain", "Unprotected.", zone="inbox")
    dex = memory.dex
    for s, last, count in (("alpha", "2026-03-01T00:00:00+00:00", 9),
                           ("beta", "2026-01-01T00:00:00+00:00", 5),
                           ("gamma", "2026-01-01T00:00:00+00:00", 1),
                           ("delta", "not a date", 50)):
        dex.set_dynamics(s, {"strength": 1.0, "stability": 1.0,
                             "access_count": count, "last_access": last})
    picks = retire_candidates(dex, CapacityBudget(1, None), 10)
    assert [c["slug"] for c in picks] == ["delta", "gamma", "beta"]
    assert picks[1]["access_count"] == 1
    assert picks[1]["last_access"] == "2026-01-01T00:00:00+00:00"
    assert [c["slug"] for c in
            retire_candidates(dex, CapacityBudget(1, None), 2)] == \
        ["delta", "gamma"]
    assert [c["slug"] for c in
            retire_candidates(dex, CapacityBudget(3, None), 10)] == ["delta"]


def test_byte_budget_takes_candidates_until_back_under(tmp_path):
    memory = VaultMemory({"vault_path": str(tmp_path)})
    for title in ("Alpha", "Beta", "Gamma"):
        memory.write_note(title, "x" * 400, polarity="negative", zone="inbox")
    total = capacity_report(memory.dex, DEFAULT_BUDGET)["bytes"]
    one = (tmp_path / "alpha.md").stat().st_size
    picks = retire_candidates(memory.dex, CapacityBudget(None, total - one), 10)
    assert len(picks) == 1
    picks = retire_candidates(memory.dex, CapacityBudget(None, total - one - 1), 10)
    assert len(picks) == 2


def test_report_and_candidates_never_change_files(tmp_path):
    memory = seed(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    capacity_report(memory.dex, CapacityBudget(1, 1))
    retire_candidates(memory.dex, CapacityBudget(1, 1), 10)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before
