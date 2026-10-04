from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from birkin_mnemosyne import kibitzer, memory, mnemosyne
from birkin_mnemosyne.kibitzer import (
    KibitzerAdapter,
    RecallNudge,
    admit,
    render_recall,
    utf16_length,
)
from birkin_mnemosyne.memory import VaultMemory
from birkin_mnemosyne.mnemosyne import Mnemosyne, tokenize


@pytest.mark.parametrize("field", ["title", "tags", "body"])
def test_core_fields_outrank_description_only_matches(tmp_path: Path, field: str) -> None:
    # Given a core-supported match and a stronger description-only distractor.
    metadata = "title: ordinary\ncreated: 2000-01-01\n"
    body = "ordinary"
    if field == "body":
        body = "meridian"
    else:
        metadata += f"{field}: " + ("[meridian]" if field == "tags" else "meridian") + "\n"
    _ = (tmp_path / "supported.md").write_text(
        "---\n" + metadata + "description: ordinary\n---\n" + body, "utf-8",
    )
    _ = (tmp_path / "description.md").write_text(
        "---\ntitle: ordinary\ncreated: 2000-01-01\n"
        + "description: meridian meridian meridian\n---\nordinary", "utf-8",
    )
    baseline = Mnemosyne(tmp_path, semantic=False).search("meridian", limit=20)
    assert [hit["rel"] for hit in baseline] == ["supported.md"]

    # When the adapter selects with a nonempty eligible core result.
    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=20)

    # Then descriptions do not introduce or reorder baseline hits.
    assert [candidate.path for candidate in candidates] == [hit["rel"] for hit in baseline]


@pytest.mark.parametrize("boost", [False, True], ids=["updated-tie", "dynamics"])
def test_core_ties_and_dynamics_determine_adapter_order(tmp_path: Path, boost: bool) -> None:
    # Given equal indexed terms with a date tie-break opposing path order.
    dates = (("a", "2001-01-01"), ("z", "2000-01-01")) if boost else (
        ("a", "2000-01-01"), ("z", "2001-01-01"),
    )
    for name, updated in dates:
        _ = (tmp_path / f"{name}.md").write_text(
            f"---\ntitle: ordinary\ncreated: 2000-01-01\nupdated: {updated}\n"
            + "description: meridian\n---\nmeridian", "utf-8",
        )
    core = Mnemosyne(tmp_path, semantic=False)
    if boost:
        assert [hit["rel"] for hit in core.search("meridian", limit=20)] == ["a.md", "z.md"]
        core.set_dynamics("z", {
            "strength": 5.0, "stability": 1.0, "access_count": 10, "last_access": "invalid",
        })
    expected = ["z.md", "a.md"]
    assert [hit["rel"] for hit in core.search("meridian", limit=20)] == expected

    # When selection uses the same persisted dynamics and notes.
    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=20)

    # Then the actual core order and inverse score monotonicity survive.
    assert [candidate.path for candidate in candidates] == expected
    assert [candidate.score for candidate in candidates] == sorted(c.score for c in candidates)


def test_core_exclusions_and_allowed_paths_precede_cap(tmp_path: Path) -> None:
    # Given more high-ranked protected/excluded hits than the requested cap.
    for index in range(8):
        path = tmp_path / ("system" if index < 4 else "reference") / f"note-{index}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(
            f"---\ntitle: meridian\ncreated: 2000-01-01\nupdated: 200{index}-01-01\n"
            + "description: ordinary\n---\nordinary", "utf-8",
        )
    baseline = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=100)
    eligible = [hit["rel"] for hit in baseline if hit["rel"].startswith("reference/")]

    # When both caller exclusions remove the first three eligible hits.
    candidates = KibitzerAdapter(tmp_path).select(
        "meridian", limit=1, surfaced=eligible[:2], exclude_paths=eligible[2:3],
    )

    # Then the next eligible core hit fills the cap.
    assert [candidate.path for candidate in candidates] == eligible[3:4]


@pytest.mark.parametrize("field", ["title", "tags", "body"])
def test_preserved_stat_edits_refresh_core_matches(tmp_path: Path, field: str) -> None:
    # Given an already indexed note and a same-length edit of an indexed field.
    def text(term: str) -> str:
        title = term if field == "title" else "ordinary"
        tags = term if field == "tags" else "ordinary"
        body = term if field == "body" else "ordinary"
        return (
            f"---\ntitle: {title}\ntags: [{tags}]\ncreated: 2000-01-01\n"
            f"description: ordinary\n---\n{body}"
        )

    path = tmp_path / "changed.md"
    _ = path.write_text(text("meridian"), "utf-8")
    adapter = KibitzerAdapter(tmp_path)
    _ = adapter.documents()
    old = path.stat()
    _ = path.write_text(text("asteroid"), "utf-8")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert (path.stat().st_mtime_ns, path.stat().st_size) == (old.st_mtime_ns, old.st_size)

    # When a normal selection follows the outside edit without forcing refresh.
    candidates = adapter.select("asteroid")

    # Then the new indexed field is visible and the old match has disappeared.
    assert [candidate.path for candidate in candidates] == ["changed.md"]
    assert adapter.select("meridian") == ()


def test_preserved_stat_edit_with_creation_time_ctime_is_immediate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given actual directory entries with Windows creation-time ctime semantics.
    native_scan = os.scandir

    @dataclass(frozen=True, slots=True)
    class CreationStat:
        st_mtime_ns: int
        st_ctime_ns: int
        st_size: int

    @dataclass(frozen=True, slots=True)
    class CreationEntry:
        entry: os.DirEntry[str]

        @property
        def name(self) -> str:
            return self.entry.name

        @property
        def path(self) -> str:
            return self.entry.path

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            return self.entry.is_dir(follow_symlinks=follow_symlinks)

        def is_file(self, *, follow_symlinks: bool = True) -> bool:
            return self.entry.is_file(follow_symlinks=follow_symlinks)

        def stat(self) -> CreationStat:
            stat = self.entry.stat()
            return CreationStat(stat.st_mtime_ns, 1, stat.st_size)

    class CreationScan(list[CreationEntry]):
        def __enter__(self) -> Self:
            return self

        def __exit__(
            self, exc_type: type[BaseException] | None, exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def creation_scan(path: str | Path) -> CreationScan:
        with native_scan(path) as entries:
            return CreationScan(CreationEntry(entry) for entry in entries)

    monkeypatch.setattr(os, "scandir", creation_scan)
    monkeypatch.setattr(sys, "platform", "win32")
    path = tmp_path / "changed.md"
    _ = path.write_text("---\ntitle: meridian\n---\nordinary", "utf-8")
    adapter = KibitzerAdapter(tmp_path)
    assert [hit.path for hit in adapter.select("meridian")] == ["changed.md"]
    old = path.stat()
    _ = path.write_text("---\ntitle: asteroid\n---\nordinary", "utf-8")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))

    # When the normal public selection follows a same-size/same-mtime edit.
    candidates = adapter.select("asteroid")

    # Then neither cached documents nor core terms retain the prior title.
    assert [hit.path for hit in candidates] == ["changed.md"]
    assert adapter.select("meridian") == ()


@pytest.mark.parametrize("mutation", ["new", "delete", "rename"])
def test_outside_path_changes_are_immediate(tmp_path: Path, mutation: str) -> None:
    # Given a live snapshot, changed outside the library after discovery.
    path = tmp_path / "original.md"
    _ = path.write_text("---\ntitle: meridian\ndescription: ordinary\n---\nordinary", "utf-8")
    adapter = KibitzerAdapter(tmp_path)
    _ = adapter.documents()
    expected = ["original.md", "new.md"]
    if mutation == "new":
        _ = (tmp_path / "new.md").write_text(path.read_text("utf-8"), "utf-8")
    elif mutation == "delete":
        path.unlink()
        expected = []
    else:
        _ = path.rename(tmp_path / "renamed.md")
        expected = ["renamed.md"]

    # When selection checks the current paths.
    candidates = adapter.select("meridian", limit=20)

    # Then only the current core-supported paths remain.
    assert sorted(candidate.path for candidate in candidates) == sorted(expected)


def test_unchanged_documents_reuse_tokens_and_query_tokenizes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given two fallback documents and a recording seam on adapter tokenization.
    for name in ("one", "two"):
        _ = (tmp_path / f"{name}.md").write_text(
            "---\ndescription: meridian\n---\nordinary", "utf-8",
        )
    calls: list[str] = []
    original = tokenize

    def recorded(text: str) -> list[str]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(kibitzer, "tokenize", recorded)
    adapter = KibitzerAdapter(tmp_path)
    _ = adapter.documents()
    calls.clear()
    _ = (tmp_path / "one.md").write_text("---\ndescription: meridian\n---\nchanged", "utf-8")

    # When one document changes and multiple excerpts are produced.
    candidates = adapter.select("meridian", limit=2)

    # Then unchanged document terms are reused and excerpts share query terms.
    assert len(candidates) == 2
    assert calls.count("meridian") == 1
    assert "meridian ordinary" not in calls


def test_symlink_escape_is_not_discovered(tmp_path: Path) -> None:
    # Given a file and directory link escaping the canonical vault.
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.md"
    _ = target.write_text("---\ntitle: meridian\n---\nmeridian", "utf-8")
    (vault / "escape.md").symlink_to(target)
    (vault / "escape-dir").symlink_to(outside, target_is_directory=True)

    # When the public adapter discovers and selects.
    adapter = KibitzerAdapter(vault)

    # Then neither escape contributes documents or candidates.
    assert adapter.documents() == ()
    assert adapter.select("meridian") == ()


@pytest.mark.parametrize("targeted", [False, True])
def test_core_never_reads_or_caches_escaping_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, targeted: bool,
) -> None:
    # Given escaped file and zone links with real outside note content.
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.md"
    _ = target.write_text("---\ntitle: meridian\n---\nmeridian", "utf-8")
    (vault / "escape.md").symlink_to(target)
    (vault / "escape-dir").symlink_to(outside, target_is_directory=True)
    original = Path.read_text
    reads: list[Path] = []

    def read_text(
        path: Path, encoding: str | None = None, errors: str | None = None,
    ) -> str:
        reads.append(path.resolve())
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text)

    # When discovery synchronizes the real core and its persisted index.
    if targeted:
        Mnemosyne(vault, semantic=False).note_written(vault / "escape.md")
    else:
        _ = KibitzerAdapter(vault).documents()
    entries = Mnemosyne(vault, semantic=False).entries()

    # Then outside bytes were never read, including through zone links.
    assert not any(path.is_relative_to(outside) for path in reads)
    assert entries == {}


def test_nested_core_matches_survive_scan_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a nested-system note supported through targeted core indexing.
    clock = [0.0]
    monkeypatch.setattr(mnemosyne, "_clock", lambda: clock[0])
    path = tmp_path / "reference" / "system" / "deep.md"
    path.parent.mkdir(parents=True)
    _ = path.write_text("---\ntitle: meridian\ndescription: ordinary\n---\nordinary", "utf-8")
    adapter = KibitzerAdapter(tmp_path)
    assert [candidate.path for candidate in adapter.select("meridian")] == [
        "reference/system/deep.md",
    ]
    clock[0] += mnemosyne.SCAN_TTL + 1

    # When selection runs after the core scan TTL with an unchanged snapshot.
    candidates = adapter.select("meridian")

    # Then the core's shallow discovery cannot evict the nested match.
    assert [candidate.path for candidate in candidates] == ["reference/system/deep.md"]


@pytest.mark.parametrize("older_directory", ["a", "reference/deep"])
@pytest.mark.parametrize("newer_directory", ["z", "z/deep"])
def test_edited_older_duplicate_slug_keeps_newest_winner(
    tmp_path: Path, older_directory: str, newer_directory: str,
) -> None:
    # Given duplicate slugs with a known newer shallow or deep winner.
    older = tmp_path / older_directory / "same.md"
    newer = tmp_path / newer_directory / "same.md"
    for path in (older, newer):
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("---\ntitle: meridian\n---\nalpha", "utf-8")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer, ns=(2_000_000_000, 2_000_000_000))
    adapter = KibitzerAdapter(tmp_path)
    _ = adapter.documents()
    _ = older.write_text("---\ntitle: meridian\n---\nomega", "utf-8")
    os.utime(older, ns=(1_000_000_000, 1_000_000_000))

    # When a changed older copy is forwarded during normal selection.
    candidates = adapter.select("meridian")

    # Then both changed and unchanged snapshots retain the newest slug winner.
    expected = [f"{newer_directory}/same.md"]
    assert [candidate.path for candidate in candidates] == expected
    assert [candidate.path for candidate in adapter.select("meridian")] == expected


def test_core_candidate_ties_preserve_discovery_order(tmp_path: Path) -> None:
    # Given more identical lexical scores than the core candidate shortlist.
    for index in range(160):
        _ = (tmp_path / f"note-{index:03d}.md").write_text(
            "---\ntitle: ordinary\ncreated: 2000-01-01\n"
            + f"updated: 2000-01-{index % 28 + 1:02d}\n"
            + "description: unrelated\n---\nmeridian", "utf-8",
        )
    baseline = Mnemosyne(tmp_path, semantic=False).search("meridian", limit=200)

    # When initial synchronization forwards the discovered notes to the core.
    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=200)

    # Then forwarding must not reorder the core's pre-boost candidate ties.
    assert [candidate.path for candidate in candidates] == [hit["rel"] for hit in baseline]


def test_initial_selection_preserves_prior_targeted_write_history(tmp_path: Path) -> None:
    for index in range(40):
        _ = (tmp_path / f"history-{index:03d}.md").write_text(
            "---\ntitle: ordinary\ncreated: 2000-01-01\nupdated: 2000-01-01\n"
            + "description: unrelated\n---\nmeridian", "utf-8",
        )
    core = Mnemosyne(tmp_path, semantic=False)
    before = core.search("meridian", limit=200)
    first = before[0]["rel"]
    assert isinstance(first, str)
    core.note_written(tmp_path / first)
    persisted = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=200)
    baseline = [hit["rel"] for hit in persisted]

    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=200)

    assert [candidate.path for candidate in candidates] == baseline
    after = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=200)
    after_paths = [hit["rel"] for hit in after]
    assert after_paths == baseline


def test_initial_selection_keeps_cached_order_when_scandir_order_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(40):
        _ = (tmp_path / f"scan-history-{index:03d}.md").write_text(
            "---\ntitle: ordinary\ncreated: 2000-01-01\nupdated: 2000-01-01\n"
            + "description: unrelated\n---\nmeridian", "utf-8",
        )
    hits = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=200)
    baseline = [hit["rel"] for hit in hits]
    native_scan = os.scandir

    class ScanOrder(list[os.DirEntry[str]]):
        def __enter__(self) -> Self:
            return self

        def __exit__(
            self, exc_type: type[BaseException] | None, exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def reversed_scan(path: str | Path) -> ScanOrder:
        with native_scan(path) as entries:
            return ScanOrder(reversed(list(entries)))

    monkeypatch.setattr(os, "scandir", reversed_scan)
    persisted = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=200)
    persisted_paths = [hit["rel"] for hit in persisted]
    assert persisted_paths == baseline

    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=200)

    assert [candidate.path for candidate in candidates] == baseline


def test_core_candidate_ties_with_protected_paths_preserve_baseline(tmp_path: Path) -> None:
    # Given equal lexical scores interleaved with protected core-only paths.
    for index in range(160):
        path = tmp_path / ("system" if index < 10 else "") / f"note-{index:03d}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(
            "---\ntitle: ordinary\ncreated: 2000-01-01\nupdated: 2000-01-01\n"
            + "description: meridian\n---\nmeridian", "utf-8",
        )
    hits = Mnemosyne(
        tmp_path, semantic=False,
    ).search("meridian", limit=200)
    baseline = [hit["rel"] for hit in hits if not hit["rel"].startswith("system/")]
    assert baseline

    # When the adapter synchronizes the initial snapshot.
    candidates = KibitzerAdapter(tmp_path).select("meridian", limit=200)

    # Then eligible nonempty core results keep their candidate slots and order.
    assert [candidate.path for candidate in candidates] == baseline


def test_unchanged_nested_candidate_ties_keep_their_order(tmp_path: Path) -> None:
    # Given a deep snapshot with more tied matches than the core shortlist.
    directory = tmp_path / "reference" / "system"
    directory.mkdir(parents=True)
    for index in range(40):
        _ = (directory / f"note-{index:03d}.md").write_text(
            "---\ntitle: meridian\ncreated: 2000-01-01\nupdated: 2000-01-01\n"
            + "description: unrelated\n---\nordinary", "utf-8",
        )
    adapter = KibitzerAdapter(tmp_path)
    original = [candidate.path for candidate in adapter.select("meridian", limit=100)]
    assert original

    # When an unchanged snapshot restores paths after the core's shallow refresh.
    candidates = adapter.select("meridian", limit=100)

    # Then restoring deep entries cannot reorder or replace earlier candidates.
    assert [candidate.path for candidate in candidates] == original


def test_description_ranks_and_export_produces_described_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _ = (vault / "guard.md").write_text(
        "---\ndescription: release publication approval guard\n---\n"
        + "The final step needs a human decision.\n", encoding="utf-8",
    )
    adapter = KibitzerAdapter(vault)
    candidate, = adapter.select("publication approval", limit=1)
    assert candidate.path == "guard.md"
    assert candidate.description == "release publication approval guard"
    assert set(asdict(candidate)) == {"path", "description", "excerpt", "score"}
    exported = adapter.export(tmp_path / "export")
    assert exported == ("guard.md",)
    text = (tmp_path / "export" / "guard.md").read_text("utf-8")
    assert 'description: "release publication approval guard"' in text
    assert "The final step needs a human decision." in text
    with pytest.raises(FileExistsError):
        _ = adapter.export(tmp_path / "export")


def test_root_system_archive_and_expiry_are_excluded_not_nested_system(tmp_path: Path) -> None:
    for relative in ("system/private.md", "_archive/old.md", "reference/system/live.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("---\ndescription: deploy guard\n---\ndeploy rule\n", "utf-8")
    _ = (tmp_path / "expired.md").write_text(
        "---\nexpires_at: 2000-01-01\n---\ndeploy rule\n", "utf-8",
    )
    documents = KibitzerAdapter(tmp_path).documents()
    assert [d.path for d in documents] == ["reference/system/live.md"]


@pytest.mark.parametrize("offset", [9, -7], ids=["local-ahead-of-utc", "local-behind-utc"])
def test_expiry_and_cached_selection_follow_local_midnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offset: int,
) -> None:
    clock = [datetime(2026, 10, 2, 23, 59, tzinfo=timezone(timedelta(hours=offset)))]

    class LocalDate:
        @classmethod
        def today(cls) -> date:
            return clock[0].date()

        @classmethod
        def fromisoformat(cls, value: str) -> date:
            return date.fromisoformat(value)

    @dataclass(frozen=True, slots=True)
    class ClockDatetime:
        value: datetime

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(clock[0].astimezone(tz))

        def astimezone(self, tz: tzinfo | None = None) -> Self:
            return type(self)(self.value.astimezone(clock[0].tzinfo if tz is None else tz))

        def date(self) -> date:
            return self.value.date()

    monkeypatch.setattr(kibitzer, "date", LocalDate)
    monkeypatch.setattr(memory, "date", LocalDate)
    # Control the former UTC clock too, so the regression is independent of the host timezone.
    monkeypatch.setattr(kibitzer, "datetime", ClockDatetime, raising=False)
    monkeypatch.setattr(memory, "datetime", ClockDatetime)
    vault = tmp_path / "vault"
    vault.mkdir()
    _ = (vault / "deadline.md").write_text(
        "---\nexpires_at: 2026-10-02\n---\nRelease deadline fact.\n", "utf-8",
    )
    adapter = KibitzerAdapter(vault)
    vault_memory = VaultMemory({"vault_path": str(vault)})
    assert len(vault_memory.list_notes()) == 1
    assert [c.path for c in adapter.select("deadline")] == ["deadline.md"]
    utc_day = clock[0].astimezone(timezone.utc).date()

    clock[0] += timedelta(minutes=2)

    assert clock[0].astimezone(timezone.utc).date() == utc_day
    assert vault_memory.list_notes() == []
    assert adapter.select("deadline") == ()
    assert adapter.documents() == ()
    assert adapter.export(tmp_path / "export") == ()


def test_exclusions_precede_cap_and_cache_sees_edits(tmp_path: Path) -> None:
    memory = VaultMemory({"vault_path": str(tmp_path)})
    _ = memory.write_note("First guard", "Release approval.")
    _ = memory.write_note("Second guard", "Release approval.")
    adapter = KibitzerAdapter(tmp_path)
    first = adapter.select("release", limit=1)[0]
    second, = adapter.select("release", limit=1, surfaced=[first.path])
    assert second.path != first.path
    assert adapter.select("no-match-zebra") == ()
    _ = memory.write_note("First guard", "Fresh distinct word: meridian.")
    assert adapter.select("meridian", limit=1)[0].path.endswith("first-guard.md")


def test_scores_are_ascending_and_excerpt_utf16_budget(tmp_path: Path) -> None:
    memory = VaultMemory({"vault_path": str(tmp_path)})
    _ = memory.write_note("Rocket rule", "rocket " + "🚀" * 150 + " release rule")
    _ = memory.write_note("Release overview", "release details")
    candidates = KibitzerAdapter(tmp_path).select("rocket release")
    assert [c.score for c in candidates] == sorted(c.score for c in candidates)
    assert all(utf16_length(c.excerpt) <= 200 for c in candidates)


@pytest.mark.parametrize("hint", [
    "", " \t", "Two\nlines", "You should revise this.", "Never publish that.",
    "The memory is not relevant.", "이 기록을 확인하세요.", "기록을 공개하지 마라.",
    "Fact\x00invalid", "Fact\ud800invalid",
])
def test_admission_rejects_non_factual_shapes(hint: str) -> None:
    result = admit([RecallNudge("rule.md", hint)], offered=["rule.md"])
    assert result.accepted == ()
    assert len(result.rejected) == 1


def test_admission_uses_js_units_at_emoji_boundary() -> None:
    prefix = "The note records "
    hint = prefix + "x" * (200 - len(prefix) - 3) + "🚀."
    assert utf16_length(hint) == 200
    assert len(admit([RecallNudge("a.md", hint)], offered=["a.md"]).accepted) == 1
    assert admit([RecallNudge("a.md", hint + "x")], offered=["a.md"]).accepted == ()


def test_offered_path_surfaced_duplicate_and_cap_are_authoritative() -> None:
    fact = "The note records that releases require approval."
    result = admit([
        RecallNudge("forged.md", fact), RecallNudge("system/private.md", fact),
        RecallNudge("seen.md", fact), RecallNudge("a.md", fact),
        RecallNudge("a.md", fact), RecallNudge("b.md", fact), RecallNudge("c.md", fact),
    ], offered=["system/private.md", "seen.md", "a.md", "b.md", "c.md"],
        surfaced=["seen.md"], max_items=2)
    assert [n.path for n in result.accepted] == ["a.md", "b.md"]
    assert len(result.rejected) == 5


@pytest.mark.parametrize("path", ["../escape.md", "/absolute.md", "C:/outside.md", "C:relative.md"])
def test_even_offered_foreign_paths_are_not_admitted(path: str) -> None:
    fact = "The note records that releases require approval."
    assert admit([RecallNudge(path, fact)], offered=[path]).accepted == ()


@pytest.mark.parametrize("codepoint", [
    0x00, 0x08, 0x0B, 0x0C, 0x0E, 0x1F,
    0xD800, 0xDBFF, 0xDC00, 0xDFFF, 0xFFFE, 0xFFFF,
])
@pytest.mark.parametrize("field", ["path", "hint"])
def test_admission_rejects_xml_invalid_scalars(codepoint: int, field: str) -> None:
    scalar = chr(codepoint)
    path = f"note{scalar}.md" if field == "path" else "note.md"
    hint = f"A stored fact{scalar}." if field == "hint" else "A stored fact."

    result = admit([RecallNudge(path, hint)], offered=[path])

    assert result.accepted == ()
    assert result.rejected == ((path, "unoffered-or-protected" if field == "path"
                                else "hint-shape"),)


@pytest.mark.parametrize("scalar", [
    "\x20", "\ud7ff", "\ue000", "\ufffd", "\U00010000", "\U0010ffff",
])
def test_admitted_xml_scalar_boundaries_render_as_utf8_data(scalar: str) -> None:
    path = f"note{scalar}.md"
    hint = f"A stored fact{scalar}."

    accepted, = admit([RecallNudge(path, hint)], offered=[path]).accepted
    parsed = ET.fromstring(render_recall(accepted).encode("utf-8"))

    assert parsed.attrib["source"] == f"[[{path}]]"
    assert parsed.text is not None
    assert hint in parsed.text


def test_candidate_and_hint_redaction_never_emits_secret_like_values(tmp_path: Path) -> None:
    fake = "sk-" + "fixture" * 8
    memory = VaultMemory({"vault_path": str(tmp_path)})
    _ = memory.write_note("Credential incident", "Credential incident token: " + fake)
    documents = KibitzerAdapter(tmp_path).documents()
    assert all(fake not in d.body + d.description for d in documents)
    result = admit([RecallNudge("a.md", "The note records token: " + fake)],
                   offered=["a.md"])
    assert result.accepted == ()
    assert result.rejected[0][1] == "secret-like"


def test_envelope_escapes_path_and_hint_as_data() -> None:
    path = 'reference/A & "B".md'
    hint = "The note records that A < B & C remains true."
    accepted = admit([RecallNudge(path, hint)], offered=[path]).accepted[0]
    block = render_recall(accepted)
    parsed = ET.fromstring(block)
    assert parsed.tag == "recalled-memory"
    assert parsed.attrib["source"] == f"[[{path}]]"
    assert parsed.text is not None
    assert hint in parsed.text
