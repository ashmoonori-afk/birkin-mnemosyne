from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import TypedDict

import pytest

from birkin_mnemosyne import startup_compact
from birkin_mnemosyne._startup_syntax import Span, parse_spans
from birkin_mnemosyne.identity_reader import parse_sections
from birkin_mnemosyne.startup import StartupBundle, StartupError, StartupReader
from birkin_mnemosyne.startup_compact import (
    CompactPayload,
    OrderEntry,
    apply_order,
    compact_effects,
    compact_payload,
)
from birkin_mnemosyne.startup_coverage import (
    BlockRecord,
    JsonValue,
    StartupPayload,
    verify_context,
)

decode_compact: Callable[[str], CompactPayload] = json.loads
decode_legacy: Callable[[str], StartupPayload] = json.loads
decode_json: Callable[[str], dict[str, JsonValue]] = json.loads


def json_list(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list)
    return value


def json_record(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


class CompactView(TypedDict):
    headings: list[str]
    superseded: set[int]
    text: str


def legacy_blocks(tmp_path: Path, name: str, raw: bytes) -> list[BlockRecord]:
    _ = (tmp_path / name).write_bytes(raw)
    payload = decode_legacy(StartupReader(tmp_path).read([name]).context)
    return payload["blocks"]


def source_roots(text: str) -> dict[int, str]:
    """Byte offset of each TOP NOTE root -> its parsed heading line."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    roots: dict[int, str] = {}
    for section in parse_sections(text, startup_labels=True):
        if section.heading.upper().startswith("TOP NOTE"):
            roots[offsets[section.line_start - 1]] = section.text.splitlines()[0]
    return roots


def v2_view(sources: dict[str, bytes]) -> dict[str, CompactView]:
    """Assembled heading sequence plus superseded source offsets, per file."""
    payload = decode_compact(compact_payload(sources))
    assert payload["version"] == 2
    entries = {entry.get("path"): entry for entry in payload["order"]}
    view: dict[str, CompactView] = {}
    for record in payload["files"]:
        entry = entries.get(record["path"]) or OrderEntry(path=record["path"])
        assembled = apply_order(record["text"], entry)
        headings = [section.heading for section in parse_sections(assembled, startup_labels=True)
                    if section.heading not in ("Preamble", "Source preamble",
                                               "Source remainder")]
        view[record["path"]] = {
            "headings": headings,
            "superseded": set(entry.get("superseded", [])),
            "text": assembled,
        }
    return view


def legacy_headings(blocks: list[BlockRecord]) -> list[str]:
    synthetic = {"Preamble", "Source preamble", "Source remainder"}
    return [str(block["heading"]) for block in blocks
            if str(block["heading"]) not in synthetic]


def test_v2_roundtrips_bom_crlf_empty_and_final_line() -> None:
    raws = [
        b"\xef\xbb\xbf",
        "\ufeff---\r\nrole: bootstrap\r\n---\r\n\r\n# Mode\r\nRule: guard\r\n\r\nTail".encode(),
        b"",
        b"# Mode\nRule: guard\n## Tail\nPending: work",
        b"# Root\nValue: alpha\n",
    ]
    for raw in raws:
        sources = {"MODE.md": raw}
        context = compact_payload(sources)
        payload = decode_compact(context)
        assert payload["version"] == 2
        assert payload["files"][0]["text"].encode("utf-8") == raw
        entry = payload["order"][0] if payload["order"] else OrderEntry(path="MODE.md")
        assert apply_order(raw.decode("utf-8"), entry).encode("utf-8") == raw
        assert verify_context(context, sources).complete


def test_effects_parse_note_sections_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given real note sections with both ordering and supersession effects.
    text = ("## TOP NOTE 2026-09-01\nOld\n### Detail\nChild\n"
            "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nNew\n")
    newer = len(text[:text.index("## TOP NOTE 2026-10-01")].encode())
    calls: list[str] = []

    def counted(text: str, *, startup_labels: bool = False) -> tuple[Span, ...]:
        calls.append(text)
        return parse_spans(text, startup_labels=startup_labels)

    monkeypatch.setattr(startup_compact, "parse_spans", counted)
    # When effects are derived through the real parser.
    effects = compact_effects(text)
    # Then one parse supplies both effects without changing their byte offsets.
    assert effects == ([[newer, 0]], [0])
    assert calls == [text]


@pytest.mark.parametrize("corrupt", [False, True])
def test_verifier_parses_each_supplied_source_once(
    monkeypatch: pytest.MonkeyPatch, corrupt: bool,
) -> None:
    # Given an affected source and an unaffected source, using real payload bytes.
    text = ("## TOP NOTE 2026-09-01\nOld\n"
            "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nNew\n")
    plain = "# Safety\nKeep clear\n"
    sources = {"notes.md": text.encode(), "plain.md": plain.encode()}
    payload = decode_compact(compact_payload(sources))
    if corrupt:
        payload["order"][0]["superseded"] = []
    calls: list[str] = []

    def counted(text: str, *, startup_labels: bool = False) -> tuple[Span, ...]:
        calls.append(text)
        return parse_spans(text, startup_labels=startup_labels)

    monkeypatch.setattr(startup_compact, "parse_spans", counted)
    # When independently verifying against the supplied source snapshot.
    coverage = verify_context(json.dumps(payload), sources)
    # Then each source is parsed once and corruption still fails closed.
    assert calls == [text, plain]
    assert coverage.complete is not corrupt
    if corrupt:
        assert "supersession-drift:notes.md" in coverage.errors


@pytest.mark.parametrize("raw", [
    b"# Mode\nRule: guard\n",
    "\ufeff---\r\nrole: bootstrap\r\n---\r\n\r\n# Mode\r\nRule: x\r\n".encode(),
    b"",
])
def test_unaffected_file_matches_legacy_headings(tmp_path: Path, raw: bytes) -> None:
    sources = {"MODE.md": raw}
    blocks = legacy_blocks(tmp_path, "MODE.md", raw)
    assert v2_view(sources)["MODE.md"]["headings"] == legacy_headings(blocks)


@pytest.mark.parametrize("stamps", [
    ["2026-09-01", "2026-10-01"],
    ["2026-10-01", "2026-09-01"],
    ["2026-10-02T10:00Z", "2026-10-02T10:01Z"],
    ["2026-10-02T10:00:00Z", "2026-10-02T10:00:30Z"],
])
def test_uniform_precision_orders_newest_first_like_legacy(tmp_path: Path, stamps: list[str]) -> None:
    text = "".join(f"## TOP NOTE {stamp}\nValue: {i}\n" for i, stamp in enumerate(stamps))
    raw = text.encode()
    blocks = legacy_blocks(tmp_path, "handoff.md", raw)
    assert v2_view({"handoff.md": raw})["handoff.md"]["headings"] == legacy_headings(blocks)


@pytest.mark.parametrize("stamps", [
    ["2026-10-02T10:00Z", "2026-10-02T10:00:30Z"],
    ["2026-10-02", "2026-10-02T10:00Z"],
    ["2026-10-02T10:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00Z"],
    ["2026-99-99", "unknown"],
])
def test_mixed_or_invalid_precision_keeps_source_order(tmp_path: Path, stamps: list[str]) -> None:
    headings = [f"TOP NOTE {stamp} entry {i}" for i, stamp in enumerate(stamps)]
    text = "".join(f"## {heading}\nValue: {i}\n" for i, heading in enumerate(headings))
    raw = text.encode()
    assert decode_compact(compact_payload({"handoff.md": raw}))["order"] == []
    blocks = legacy_blocks(tmp_path, "handoff.md", raw)
    view = v2_view({"handoff.md": raw})["handoff.md"]
    assert view["headings"] == legacy_headings(blocks)
    assert view["text"] == "".join(block["text"] for block in blocks)
    assert view["superseded"] == set()
    assert all(block["state"] == "source" for block in blocks)


def test_descendant_sections_move_with_their_root() -> None:
    text = ("## TOP NOTE 2026-09-01\nPort: old\n### Detail\nPending: x\n"
            "## TOP NOTE 2026-10-01\nPort: new\n")
    sources = {"handoff.md": text.encode()}
    entry = decode_compact(compact_payload(sources))["order"][0]
    assembled = apply_order(text, entry)
    assert assembled.index("TOP NOTE 2026-10-01") < assembled.index("TOP NOTE 2026-09-01")
    assert assembled.index("### Detail") > assembled.index("TOP NOTE 2026-09-01")
    assert verify_context(compact_payload(sources), sources).complete


def test_separate_runs_are_encoded_independently() -> None:
    text = ("## TOP NOTE 2026-09-01\nA\n"
            "## TOP NOTE 2026-09-05\nB\n"
            "# Global safety\nRule: guard\n"
            "## TOP NOTE 2026-09-03\nC\n")
    sources = {"handoff.md": text.encode()}
    entry = decode_compact(compact_payload(sources))["order"][0]
    # The separator splits the notes into two runs; only the first needs reorder.
    assert len(entry.get("reorder", [])) == 1
    assembled = apply_order(text, entry)
    assert assembled.index("TOP NOTE 2026-09-05") < assembled.index("TOP NOTE 2026-09-01")
    assert assembled.index("TOP NOTE 2026-09-01") < assembled.index("# Global safety")
    assert assembled.index("# Global safety") < assembled.index("TOP NOTE 2026-09-03")
    assert verify_context(compact_payload(sources), sources).complete


SUPERSESSION_SOURCES = (
    "## TOP NOTE 2026-09-01\nPort: old\n"
    "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: new\n"
    "## TOP NOTE 2026-09-20\nRule: still binding\n"
), (
    "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: new\n"
    "## TOP NOTE 2026-09-01\nPort: old\n"
)


@pytest.mark.parametrize("raw", SUPERSESSION_SOURCES)
def test_explicit_supersession_matches_legacy_order_and_state(tmp_path: Path, raw: str) -> None:
    raw_bytes = raw.encode()
    blocks = legacy_blocks(tmp_path, "handoff.md", raw_bytes)
    view = v2_view({"handoff.md": raw_bytes})["handoff.md"]
    roots = source_roots(raw)
    assert view["headings"] == legacy_headings(blocks)
    legacy_superseded = {
        root for root, line in roots.items()
        for block in blocks
        if str(block["heading"]) in line and block["state"] == "explicitly-superseded"
    }
    assert view["superseded"] == legacy_superseded


def test_supersedes_ignores_fenced_lines_and_matches_case_insensitively(tmp_path: Path) -> None:
    raw = (b"```\nSupersedes: TOP NOTE 2026-01-01\n```\n"
           b"## TOP NOTE 2026-01-01\nPort: fenced-target\n"
           b"## TOP NOTE 2026-02-01\nsupersedes: top note 2026-01-01\nPort: new\n"
           b"## TOP NOTE 2026-03-01\nRule: x\n")
    blocks = legacy_blocks(tmp_path, "handoff.md", raw)
    view = v2_view({"handoff.md": raw})["handoff.md"]
    assert view["headings"] == legacy_headings(blocks)
    roots = source_roots(raw.decode())
    legacy_superseded = {
        root for root, line in roots.items()
        for block in blocks
        if str(block["heading"]) in line and block["state"] == "explicitly-superseded"
    }
    assert view["superseded"] == legacy_superseded


def test_effects_are_empty_without_notes() -> None:
    assert compact_effects("plain\n# Head\n") == ([], [])


@pytest.mark.parametrize("mutation", [
    "bool-version",
    "duplicate-json-key",
    "unexpected-version-field",
    "duplicate-file",
    "foreign-file",
    "file-byte-drift",
    "path-order",
    "missing-order",
    "reorder-drift",
    "supersession-drift",
    "repeated-permutation",
    "overlapping-permutation",
    "unsorted-superseded",
    "foreign-order",
    "duplicate-order",
    "bool-offset",
])
def test_verification_rejects_compact_corruption_classes(mutation: str) -> None:
    sources = {
        "a.md": b"# A\n",
        "b.md": (b"## TOP NOTE 2026-09-01\nX\n" +
                 b"## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nY\n"),
    }
    good = decode_json(compact_payload(sources))
    files = json_list(good["files"])
    order = json_list(good["order"])
    entry = json_record(order[0])
    match mutation:
        case "bool-version":
            context = '{"version":true,"files":[],"order":[]}'
        case "duplicate-json-key":
            context = '{"version":2,"version":2,"files":[],"order":[]}'
        case "unexpected-version-field":
            good["extra"] = 1
            context = json.dumps(good)
        case "duplicate-file":
            files.append(dict(json_record(files[0])))
            context = json.dumps(good)
        case "foreign-file":
            json_record(files[0])["path"] = "z.md"
            context = json.dumps(good)
        case "file-byte-drift":
            json_record(files[1])["text"] = "tampered\n"
            context = json.dumps(good)
        case "path-order":
            files.reverse()
            context = json.dumps(good)
        case "missing-order":
            good["order"] = []
            context = json.dumps(good)
        case "reorder-drift":
            entry["reorder"] = [[0, 25]]
            context = json.dumps(good)
        case "supersession-drift":
            entry["superseded"] = []
            context = json.dumps(good)
        case "repeated-permutation":
            run = json_list(json_list(entry["reorder"])[0])
            entry["reorder"] = [[run[0], run[0]]]
            context = json.dumps(good)
        case "overlapping-permutation":
            run = json_list(json_list(entry["reorder"])[0])
            entry["reorder"] = [run, run]
            context = json.dumps(good)
        case "unsorted-superseded":
            first = json_list(entry["superseded"])[0]
            assert type(first) is int
            entry["superseded"] = [first, max(0, first - 1)]
            context = json.dumps(good)
        case "foreign-order":
            entry["path"] = "z.md"
            context = json.dumps(good)
        case "duplicate-order":
            order.append(dict(entry))
            context = json.dumps(good)
        case "bool-offset":
            entry["reorder"] = [[True, False]]
            context = json.dumps(good)
        case _:
            raise AssertionError(mutation)
    assert not verify_context(context, sources).complete


def test_omits_order_for_files_without_effects() -> None:
    sources = {"plain.md": b"# Rules\nRule: guard\n", "empty.md": b""}
    context = compact_payload(sources)
    assert decode_compact(context)["order"] == []
    assert verify_context(context, sources).complete


def test_trims_equal_edges_and_keeps_two_changed_runs(tmp_path: Path) -> None:
    text = (
        "\ufeffpr\u00e9face\r\n# Rules\r\nUnicode: \ud55c\uae00\r\n"
        "## TOP NOTE 2026-09-09\r\nNewest\r\n"
        "## TOP NOTE 2026-09-02\r\nOld\r\n### Child\r\n\u03bb\r\n"
        "## TOP NOTE 2026-09-03\r\nNew\r\n"
        "## TOP NOTE 2026-09-01\r\nOldest\r\n"
        "# Boundary\r\nFixed\r\n"
        "## TOP NOTE 2026-09-04\r\nA\r\n"
        "## TOP NOTE 2026-09-05\r\nSupersedes: TOP NOTE 2026-09-02\r\nFinal"
    )
    sources = {"notes.md": text.encode()}
    payload = decode_compact(compact_payload(sources))
    entry = payload["order"][0]
    roots = list(source_roots(text))
    assert entry.get("reorder") == [[roots[2], roots[1]], [roots[5], roots[4]]]
    blocks = legacy_blocks(tmp_path, "notes.md", sources["notes.md"])
    assert apply_order(text, entry) == "".join(block["text"] for block in blocks)
    assert entry.get("superseded") == [
        block["start_byte"] for block in sorted(blocks, key=lambda block: block["start_byte"])
        if block["heading"].upper().startswith("TOP NOTE")
        and block["state"] == "explicitly-superseded"
    ]
    assert verify_context(json.dumps(payload), sources).complete


@pytest.mark.parametrize("declaration", [
    "# Rules\nSupersedes: TOP NOTE 2026-01-01\n",
    "## TOP NOTE 2026-02-01\n```\nSupersedes: TOP NOTE 2026-01-01\n```\n",
    "## TOP NOTE 2026-02-01\nSupersedes: TOP NOTE 2026-01\n",
])
def test_supersession_excludes_global_fenced_and_partial_targets(
    tmp_path: Path, declaration: str,
) -> None:
    text = "## TOP NOTE 2026-01-01\nOld\n" + declaration
    sources = {"notes.md": text.encode()}
    blocks = legacy_blocks(tmp_path, "notes.md", sources["notes.md"])
    assert all(block["state"] == "source" for block in blocks)
    assert compact_effects(text)[1] == []
    assert verify_context(compact_payload(sources), sources).complete


def test_child_supersession_marks_whole_group_like_legacy(tmp_path: Path) -> None:
    text = (
        "## TOP NOTE 2026-01-01\nOld\n### Detail\nChild\n"
        "## TOP NOTE 2026-02-01\nNew\n### Declaration\n"
        "sUpErSeDeS: top note 2026-01-01\n"
    )
    sources = {"notes.md": text.encode()}
    blocks = legacy_blocks(tmp_path, "notes.md", sources["notes.md"])
    assert compact_effects(text)[1] == [0]
    assert [block["heading"] for block in blocks
            if block["state"] == "explicitly-superseded"] == ["TOP NOTE 2026-01-01", "Detail"]


@pytest.mark.parametrize("mutation", [
    "empty-reorder", "empty-superseded", "untrimmed", "identity",
    "negative", "foreign-offset", "missing-file", "file-extra", "order-extra",
    "order-path-order", "nested-duplicate-key", "bool-superseded",
    "duplicate-superseded",
])
def test_rejects_noncanonical_effects_and_structural_drift(mutation: str) -> None:
    text = (
        "## TOP NOTE 2026-03-01\nNewest\n"
        "## TOP NOTE 2026-01-01\nOld\n"
        "## TOP NOTE 2026-02-01\nSupersedes: TOP NOTE 2026-01-01\n"
    )
    sources = {"a.md": text.encode(), "b.md": text.encode()}
    payload = decode_json(compact_payload(sources))
    files = json_list(payload["files"])
    order = json_list(payload["order"])
    entry = json_record(order[0])
    roots = list(source_roots(text))
    match mutation:
        case "empty-reorder":
            entry["reorder"] = []
        case "empty-superseded":
            entry["superseded"] = []
        case "untrimmed":
            entry["reorder"] = [[roots[0], roots[2], roots[1]]]
        case "identity":
            entry["reorder"] = [[roots[1], roots[2]]]
        case "negative":
            json_list(json_list(entry["reorder"])[0])[0] = -1
        case "foreign-offset":
            run = json_list(json_list(entry["reorder"])[0])
            first = run[0]
            assert type(first) is int
            run[0] = first + 1
        case "missing-file":
            _ = files.pop()
        case "file-extra":
            json_record(files[0])["extra"] = True
        case "order-extra":
            entry["extra"] = True
        case "order-path-order":
            order.reverse()
        case "bool-superseded":
            entry["superseded"] = [True]
        case "duplicate-superseded":
            entry["superseded"] = json_list(entry["superseded"]) * 2
        case "nested-duplicate-key":
            context = compact_payload(sources).replace(
                '"path":"a.md"', '"path":"a.md","p\\u0061th":"a.md"', 1,
            )
            assert not verify_context(context, sources).complete
            return
        case _:
            raise AssertionError(mutation)
    assert not verify_context(json.dumps(payload), sources).complete


@pytest.mark.parametrize("stamps", [
    ["2026-01-01", "2026-02-01T12:00Z"],
    ["2026-01-01T12:00Z", "2026-02-01T12:00:00Z"],
])
def test_mixed_precision_exact_reader_text_and_state(tmp_path: Path, stamps: list[str]) -> None:
    text = ("\ufeffpr\u00e9face\r\n"
            f"## TOP NOTE {stamps[0]}\r\n\ud55c\uae00\r\n### Child\r\nKeep\r\n"
            f"## TOP NOTE {stamps[1]}\r\nSupersedes: TOP NOTE {stamps[0]}\r\nFinal")
    sources = {"notes.md": text.encode()}
    blocks = legacy_blocks(tmp_path, "notes.md", sources["notes.md"])
    entry = decode_compact(compact_payload(sources))["order"][0]
    assert apply_order(text, entry) == "".join(block["text"] for block in blocks)
    assert entry.get("reorder", []) == []
    assert entry.get("superseded", []) == [
        block["start_byte"] for block in blocks
        if block["heading"].upper().startswith("TOP NOTE")
        and block["state"] == "explicitly-superseded"
    ]


def test_supersession_uses_each_child_record_fence_rules(tmp_path: Path) -> None:
    text = (
        "## TOP NOTE 2026-01-01\nOld\n### Detail\nRetained\n"
        "## TOP NOTE 2026-02-01\n~~~python\nSupersedes: TOP NOTE 2026-01-01\n"
        "~~~ trailing\nSupersedes: TOP NOTE 2026-01-01\n~~~~\n"
        "### Declaration\n```text\nSupersedes: TOP NOTE 2026-01-01\n```\n"
        "Supersedes: TOP NOTE 2026-01-01\n"
    )
    blocks = legacy_blocks(tmp_path, "notes.md", text.encode())
    assert compact_effects(text)[1] == [0]
    assert [block["heading"] for block in blocks
            if block["state"] == "explicitly-superseded"] == ["TOP NOTE 2026-01-01", "Detail"]


@pytest.mark.parametrize("text", [
    "Supersedes: TOP NOTE 2026-01-01\n## TOP NOTE 2026-01-01\nOld\n",
    "## TOP NOTE 2026-01-01\nOld\n# Barrier\nSupersedes: TOP NOTE 2026-01-01\n",
])
def test_outside_note_declarations_never_authorize_state(tmp_path: Path, text: str) -> None:
    raw = text.encode()
    blocks = legacy_blocks(tmp_path, "notes.md", raw)
    assert compact_effects(text)[1] == []
    assert all(block["state"] == "source" for block in blocks)
    assert v2_view({"notes.md": raw})["notes.md"]["text"] == "".join(
        block["text"] for block in blocks
    )


@pytest.mark.parametrize("field", ["reorder", "superseded"])
def test_rejects_present_empty_effect_even_when_other_effect_is_valid(field: str) -> None:
    text = (
        "## TOP NOTE 2026-01-01\nOld\n## TOP NOTE 2026-02-01\nNew\n"
        if field == "superseded" else
        ("## TOP NOTE 2026-02-01\nSupersedes: TOP NOTE 2026-01-01\n"
         "## TOP NOTE 2026-01-01\nOld\n")
    )
    sources = {"notes.md": text.encode()}
    payload = decode_json(compact_payload(sources))
    entry = json_record(json_list(payload["order"])[0])
    assert field not in entry
    entry[field] = []
    assert not verify_context(json.dumps(payload), sources).complete


def test_affected_order_follows_actual_reader_source_closure(tmp_path: Path) -> None:
    note = b"## TOP NOTE 2026-01-01\nOld\n## TOP NOTE 2026-02-01\nNew\n"
    _ = (tmp_path / "MODE.md").write_bytes(b"MUST READ: registry.json\n" + note)
    _ = (tmp_path / "registry.json").write_text(
        '{"must_read":["notes.md","empty.md"]}', encoding="utf-8",
    )
    _ = (tmp_path / "notes.md").write_bytes(note)
    _ = (tmp_path / "empty.md").write_bytes(b"")
    legacy = decode_legacy(StartupReader(tmp_path).read(["MODE.md"]).context)
    sources = {record["path"]: (tmp_path / record["path"]).read_bytes()
               for record in legacy["files"]}
    context = compact_payload(sources)
    assert verify_context(context, sources).complete
    payload = decode_json(context)
    order = json_list(payload["order"])
    assert [json_record(entry)["path"] for entry in order] == ["MODE.md", "notes.md"]
    order.reverse()
    assert not verify_context(json.dumps(payload), sources).complete


@pytest.mark.parametrize("raw", [
    b"", b"\xef\xbb\xbf", b"# Rules\r\nKeep\r\n\r\nTail",
    SUPERSESSION_SOURCES[0].encode(),
])
def test_reader_actual_formats_preserve_bytes_and_presentation(tmp_path: Path, raw: bytes) -> None:
    _ = (tmp_path / "notes.md").write_bytes(raw)
    reader = StartupReader(tmp_path)
    legacy = reader.read(["notes.md"])
    compact = reader.read(["notes.md"], compact=True)
    assert legacy.coverage == compact.coverage
    assert reader.verify(legacy.context, ["notes.md"]).complete
    assert reader.verify(compact.context, ["notes.md"]).complete
    v1 = decode_legacy(legacy.context)
    v2 = decode_compact(compact.context)
    assert v1["version"] == 1 and v2["version"] == 2
    assert v2["files"][0]["text"].encode() == raw
    entry = v2["order"][0] if v2["order"] else OrderEntry(path="notes.md")
    assert apply_order(raw.decode(), entry) == "".join(block["text"] for block in v1["blocks"])
    assert entry.get("superseded", []) == [
        block["start_byte"] for block in sorted(v1["blocks"], key=lambda block: block["start_byte"])
        if block["heading"].upper().startswith("TOP NOTE")
        and block["state"] == "explicitly-superseded"
    ]


def test_reader_closure_follows_literal_refs_and_deduplicates(tmp_path: Path) -> None:
    _ = (tmp_path / "nested").mkdir()
    sources = {
        "MODE.md": b"\xef\xbb\xbf~~~\nMUST READ: missing.md\n~~~\nMUST READ: nested/registry.json\n",
        "nested/registry.json": b'{"must_read":["notes.md","../MODE.md","notes.md"]}',
        "nested/notes.md": b"MUST READ: ../empty.md\n",
        "empty.md": b"",
    }
    for path, raw in sources.items():
        _ = (tmp_path / path).write_bytes(raw)
    reader = StartupReader(tmp_path)
    result = reader.read(["MODE.md", "./MODE.md"], compact=True)
    assert result.context == compact_payload(sources)
    assert result.coverage.files == 4
    assert reader.verify(result.context, ["MODE.md"]).complete
    assert reader.read(["MODE.md"], compact=True).cache_hit


@pytest.mark.parametrize("compact", [False, True])
def test_reader_same_stat_dependency_changes_and_deletion(tmp_path: Path, compact: bool) -> None:
    _ = (tmp_path / "MODE.md").write_bytes(b"MUST READ: dependency.md\n")
    dependency = tmp_path / "dependency.md"
    _ = dependency.write_bytes(b"# Root\nValue: alpha\n")
    reader = StartupReader(tmp_path)
    before = reader.read(["MODE.md"], compact=compact)
    stat = dependency.stat()
    _ = dependency.write_bytes(b"# Root\nValue: omega\n")
    os.utime(dependency, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = reader.read(["MODE.md"], compact=compact)
    assert not after.cache_hit
    assert "omega" in after.context and "alpha" not in after.context
    assert not reader.verify(before.context, ["MODE.md"]).complete
    _ = (tmp_path / "MODE.md").write_bytes(b"# Detached\n")
    detached = reader.read(["MODE.md"], compact=compact)
    assert detached.coverage.files == 1 and not detached.cache_hit
    assert not reader.verify(after.context, ["MODE.md"]).complete
    _ = (tmp_path / "MODE.md").write_bytes(b"MUST READ: dependency.md\n")
    dependency.unlink()
    with pytest.raises(FileNotFoundError):
        _ = reader.read(["MODE.md"], compact=compact)
    with pytest.raises(FileNotFoundError):
        _ = reader.verify(after.context, ["MODE.md"])


def test_reader_cache_is_exact_ordered_bytes_and_format_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from birkin_mnemosyne import startup

    _ = (tmp_path / "a.md").write_bytes(b"# A\n")
    _ = (tmp_path / "b.md").write_bytes(b"# B\n")
    reader = StartupReader(tmp_path)
    paths = ["a.md", "b.md"]
    assert not reader.read(paths).cache_hit
    assert not reader.read(paths, compact=True).cache_hit
    assert reader.read(paths).cache_hit
    assert reader.read(paths, compact=True).cache_hit
    assert not reader.read(paths[::-1], compact=True).cache_hit
    assert not reader.read(paths[::-1]).cache_hit
    assert not reader.verify(reader.read(paths).context, paths[::-1]).complete
    # A digest collision must not cause an exact-byte cache hit.
    def collision(_data: bytes) -> str:
        return "constant"

    monkeypatch.setattr(startup, "digest", collision)
    _ = (tmp_path / "a.md").write_bytes(b"# Z\n")
    assert not reader.read(paths[::-1], compact=True).cache_hit


@pytest.mark.parametrize("compact", [False, True])
def test_verify_takes_one_snapshot_and_never_calls_read(
    tmp_path: Path, compact: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "notes.md"
    _ = path.write_bytes(b"# Original\n")
    context = StartupReader(tmp_path).read(["notes.md"], compact=compact).context

    snapshots: list[dict[str, bytes]] = []

    class SnapshotReader(StartupReader):
        def snapshot(self, paths: Sequence[str]) -> dict[str, bytes]:
            sources = super()._sources(paths)
            snapshots.append(sources)
            _ = path.write_bytes(b"# Changed\n")
            return sources

    def forbidden(paths: Sequence[str], *, compact: bool = False) -> StartupBundle:
        raise AssertionError(f"verify must not call read: {paths}, compact={compact}")

    reader = SnapshotReader(tmp_path)
    monkeypatch.setattr(reader, "_sources", reader.snapshot)
    monkeypatch.setattr(reader, "read", forbidden)
    assert reader.verify(context, ["notes.md"]).complete
    assert len(snapshots) == 1
    assert not reader.verify(context, ["notes.md"]).complete
    assert len(snapshots) == 2


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("mutation", ["bytes", "order", "state"])
def test_reader_verify_rejects_actual_payload_corruption(
    tmp_path: Path, compact: bool, mutation: str,
) -> None:
    _ = (tmp_path / "notes.md").write_bytes(SUPERSESSION_SOURCES[0].encode())
    reader = StartupReader(tmp_path)
    payload = decode_json(reader.read(["notes.md"], compact=compact).context)
    if compact:
        if mutation == "bytes":
            json_record(json_list(payload["files"])[0])["text"] = "wrong"
        else:
            entry = json_record(json_list(payload["order"])[0])
            entry["reorder" if mutation == "order" else "superseded"] = []
    else:
        blocks = json_list(payload["blocks"])
        if mutation == "order":
            blocks.reverse()
        else:
            json_record(blocks[0])["text" if mutation == "bytes" else "state"] = "wrong"
    assert not reader.verify(json.dumps(payload), ["notes.md"]).complete


@pytest.mark.parametrize("kind", ["file", "bundle", "count", "escape"])
def test_compact_reader_preserves_safety_budgets(tmp_path: Path, kind: str) -> None:
    paths = ["a.md"]
    if kind == "file":
        _ = (tmp_path / "a.md").write_bytes(b"x" * 1_048_577)
    elif kind == "bundle":
        paths = ["a.md", "b.md", "c.md"]
        for name in paths:
            _ = (tmp_path / name).write_bytes(b"x" * 1_048_576)
    elif kind == "count":
        paths = [f"{i}.md" for i in range(65)]
        for name in paths:
            _ = (tmp_path / name).write_bytes(b"")
    else:
        paths = ["../escape.md"]
    with pytest.raises(StartupError, match="budget|outside"):
        _ = StartupReader(tmp_path).read(paths, compact=True)


def test_concurrent_reader_formats_are_serialized_and_independent(tmp_path: Path) -> None:
    _ = (tmp_path / "notes.md").write_bytes(SUPERSESSION_SOURCES[0].encode())
    reader = StartupReader(tmp_path)
    barrier = Barrier(4, timeout=5)

    def run(compact: bool) -> StartupBundle:
        _ = barrier.wait()
        result = reader.read(["notes.md"], compact=compact)
        assert reader.verify(result.context, ["notes.md"]).complete
        return result

    modes = [False, True, False, True]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run, compact) for compact in modes]
        results = [future.result(timeout=10) for future in futures]
    for compact in (False, True):
        matching = [result for mode, result in zip(modes, results) if mode == compact]
        assert matching[0].context == matching[1].context
        assert sorted(result.cache_hit for result in matching) == [False, True]
