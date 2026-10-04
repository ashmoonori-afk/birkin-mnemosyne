from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import is_dataclass
from itertools import permutations
from pathlib import Path

import pytest

from birkin_mnemosyne._startup_root_order import (
    JsonValue,
    RootPayload,
    apply_root_order,
    root_order,
    root_payload,
)
from birkin_mnemosyne.startup import StartupReader
from birkin_mnemosyne.startup_coverage import StartupPayload, verify_context

decode_root: Callable[[str], RootPayload] = json.loads
decode_legacy: Callable[[str], StartupPayload] = json.loads


@pytest.mark.parametrize("dates", list(permutations(range(1, 5))))
@pytest.mark.parametrize("superseded", [(), (1,), (1, 4), (1, 2, 3, 4)])
def test_selected_slots_preserve_every_legacy_group_and_state(
    tmp_path: Path, dates: tuple[int, ...], superseded: tuple[int, ...],
) -> None:
    # Given independently permuted roots, descendants and explicit state declarations.
    declarations = "".join(f"Supersedes: TOP NOTE 2026-09-{day:02d}\n" for day in superseded)
    text = "".join(
        f"## TOP NOTE 2026-09-{day:02d}\n{declarations if i == 0 else ''}"
        + f"### Child\nvalue-{day}\n" for i, day in enumerate(dates)
    )
    _ = (tmp_path / "notes.md").write_bytes(text.encode())
    reader = StartupReader(tmp_path)
    legacy = decode_legacy(reader.read(["notes.md"]).context)
    # When the real v3 public reader encodes the same source.
    result = reader.read(["notes.md"], compact=True, compact_format="file-root-order/3")
    record = decode_root(result.context)["files"][0]
    order = record.get("order", [])
    # Then assembly and states match actual legacy blocks, without losing bytes.
    assert apply_root_order(record["text"], order) == "".join(b["text"] for b in legacy["blocks"])
    expected = {
        b["start_byte"] for b in legacy["blocks"]
        if b["heading"].startswith("TOP NOTE") and b["state"] == "explicitly-superseded"
    }
    assert {-code - 1 for code in order if code < 0} == expected
    assert record["text"].encode() == text.encode()
    assert result.coverage.complete and reader.verify(result.context, ["notes.md"]).complete
    assert is_dataclass(result) and is_dataclass(result.coverage)


@pytest.mark.parametrize("pair", [
    ("2000-02-29", "2000-03-01"), ("1900-02-29", "1900-03-01"),
    ("0000-01-01", "0001-01-01"), ("9999-12-31", "0001-01-01"),
    ("2026-00-01", "2026-01-01"), ("2026-04-31", "2026-05-01"),
    ("2026-09-01T23:59Z", "2026-09-01T00:00Z"),
    ("2026-09-01T24:00Z", "2026-09-02T00:00Z"),
    ("2026-09-01T23:60Z", "2026-09-02T00:00Z"),
    ("2026-09-01T23:59:60Z", "2026-09-02T00:00:00Z"),
    ("2026-09-01", "2026-09-01T00:00Z"),
    ("2026-09-01", "2026-09-01"),
    ("٢٠٢٦-09-01", "2026-09-02"),
])
def test_calendar_and_precision_keep_real_legacy_presentation(
    tmp_path: Path, pair: tuple[str, str],
) -> None:
    # Given valid/invalid calendar, time, precision and non-ASCII date cases.
    text = f"## TOP NOTE {pair[0]}\nfirst\n## TOP NOTE {pair[1]}\nsecond"
    _ = (tmp_path / "notes.md").write_bytes(text.encode())
    legacy = decode_legacy(StartupReader(tmp_path).read(["notes.md"]).context)
    # When the new representation assembles its independently derived root order.
    actual = apply_root_order(text, root_order(text))
    # Then no validation or comparison change alters the old presentation.
    assert actual == "".join(b["text"] for b in legacy["blocks"])


@pytest.mark.parametrize("text", [
    "", "\ufeff", "\ufeff# Rules\r\nGuard\r\nTail",
    ("## TOP NOTE 2026-12-01\nSupersedes: TOP NOTE 2026-12-01\n"
     "## TOP NOTE 2026-09-01\nold\n## TOP NOTE 2026-10-01\nnew\n"
     "# Barrier\nfixed\n"
     "## TOP NOTE 2026-07-01\nolder\n## TOP NOTE 2026-08-01\nrecent\n"),
    ("TOP NOTE 2026-09-01\r\n### Detail\r\n끝\r\n"
     "TOP NOTE 2026-10-01\r\nSupersedes: TOP NOTE 2026-09-01"),
])
def test_barriers_unchanged_edges_and_raw_boundaries_match_legacy(
    tmp_path: Path, text: str,
) -> None:
    # Given multiple runs, a superseded fixed edge, BOM/CRLF or empty data.
    _ = (tmp_path / "notes.md").write_bytes(text.encode())
    legacy = decode_legacy(StartupReader(tmp_path).read(["notes.md"]).context)
    # When a complete v3 payload is derived.
    payload = decode_root(root_payload({"notes.md": text.encode()}))
    record = payload["files"][0]
    # Then plain barriers, descendant movement and all raw bytes remain intact.
    assert record["text"] == text
    assert apply_root_order(text, record.get("order", [])) == "".join(
        b["text"] for b in legacy["blocks"])
    assert verify_context(json.dumps(payload), {"notes.md": text.encode()}).complete


@pytest.mark.parametrize("order", [
    [], [True], [False], [0.0], [None], ["0"], [[0]], [0, -1],
    [999999], [-999999], [0], [-1, 0],
])
def test_untrusted_root_values_never_certify_complete(order: list[JsonValue]) -> None:
    # Given two changed roots including root zero and explicit supersession.
    text = ("## TOP NOTE 2026-09-01\nold\n## TOP NOTE 2026-10-01\n"
            "Supersedes: TOP NOTE 2026-09-01\nnew\n")
    payload = {"files": [{"path": "notes.md", "text": text, "order": order}]}
    # When the malformed/foreign/incomplete/duplicate state data is verified.
    coverage = verify_context(json.dumps(payload), {"notes.md": text.encode()})
    # Then no returned metadata acts as source authority.
    assert not coverage.complete


def test_v3_fresh_closure_same_stat_and_format_cache_isolation(tmp_path: Path) -> None:
    # Given a cyclic live declaration and independently cached legacy/v2/v3.
    _ = (tmp_path / "MODE.md").write_bytes(b"MUST READ: note.md\n")
    note = tmp_path / "note.md"
    _ = note.write_bytes(b"MUST READ: MODE.md\n# Value\nalpha\n")
    reader = StartupReader(tmp_path)
    legacy = reader.read(["MODE.md"])
    v2 = reader.read(["MODE.md"], compact=True)
    before = reader.read(["MODE.md"], compact=True, compact_format="file-root-order/3")
    assert not legacy.cache_hit and not v2.cache_hit and not before.cache_hit
    stat = note.stat()
    _ = note.write_bytes(b"MUST READ: MODE.md\n# Value\nomega\n")
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    # When v3 freshly reads a same-stat dependency edit.
    after = reader.read(["MODE.md"], compact=True, compact_format="file-root-order/3")
    # Then changed bytes invalidate the old context and all format caches.
    assert not after.cache_hit and not reader.verify(before.context, ["MODE.md"]).complete
    assert "omega" in after.context
    assert not reader.read(["MODE.md"]).cache_hit
    assert not reader.read(["MODE.md"], compact=True).cache_hit
