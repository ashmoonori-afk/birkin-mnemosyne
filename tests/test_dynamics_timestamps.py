"""Malformed JSON timestamps preserve the existing fail-open decay contract."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, TypeAlias

import pytest

from birkin_mnemosyne.mnemosyne import (
    DYNAMICS_FILE,
    JsonValue,
    Mnemosyne,
    effective_strength,
)

_TimestampValue: TypeAlias = JsonValue
_TIMESTAMPS: Final[tuple[_TimestampValue, ...]] = (
    None, False, True, 123, 1.5, [], [1], {"invalid": "timestamp"},
)
_RootValue: TypeAlias = str | bool | int | float | None | list[int]
_ROOTS: Final[tuple[_RootValue, ...]] = (
    None, False, True, 123, 1.5, [], [1], "unexpected",
)


@pytest.mark.parametrize("raw", _TIMESTAMPS)
def test_non_string_json_timestamps_do_not_decay_strength(raw: _TimestampValue) -> None:
    # Given a persisted JSON timestamp that cannot represent an ISO datetime.
    dynamics: dict[str, JsonValue] = {"strength": 4.0, "stability": 7.0, "last_access": raw}
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)

    # When the real public strength calculation consumes the timestamp.
    actual = effective_strength(dynamics, now)

    # Then malformed timestamps remain fail-open rather than losing history.
    assert actual == 4.0


@pytest.mark.parametrize("raw", _ROOTS)
def test_non_object_dynamics_roots_keep_default_strength(
    tmp_path: Path, raw: _RootValue,
) -> None:
    # Given a source note and a persisted dynamics root with the wrong shape.
    _ = (tmp_path / "note.md").write_text(
        "---\ntitle: note\ncreated: 2026-10-03T12:00:00+00:00\n---\nnote",
        encoding="utf-8",
    )
    _ = (tmp_path / DYNAMICS_FILE).write_text(json.dumps(raw), encoding="utf-8")
    engine = Mnemosyne(tmp_path, semantic=False)
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)

    # When a fresh real engine reads and calculates persisted dynamics.
    actual = engine.effective_of("note", now)

    # Then malformed roots retain the existing source-derived default state.
    assert actual == 1.0


@pytest.mark.parametrize("raw", [True, 123, [1], "unexpected"])
def test_truthy_non_mapping_note_dynamics_preserve_errors(
    tmp_path: Path, raw: bool | int | list[int] | str,
) -> None:
    # Given a truthy note-level value that HEAD cannot copy into a dictionary.
    _ = (tmp_path / DYNAMICS_FILE).write_text(
        json.dumps({"notes": {"note": raw}}), encoding="utf-8",
    )
    engine = Mnemosyne(tmp_path, semantic=False)

    # When reading note dynamics, then no source-derived fallback is substituted.
    with pytest.raises((TypeError, ValueError)):
        _ = engine.dynamics_of("note")


@pytest.mark.parametrize(("raw", "expected"), [
    ([["strength", 4.0], ["last_access", None]], {"strength": 4.0, "last_access": None}),
    (["ab"], {"a": "b"}),
    ([[123, "extension"]], {123: "extension"}),
    ([{"strength": 4.0, "stability": 7.0}], {"strength": "stability"}),
])
def test_pair_sequence_note_dynamics_keep_dict_constructor_contract(
    tmp_path: Path, raw: list[JsonValue], expected: dict[str | int, JsonValue],
) -> None:
    # Given a non-mapping JSON value that the HEAD dict constructor accepts.
    _ = (tmp_path / DYNAMICS_FILE).write_text(
        json.dumps({"notes": {"note": raw}}), encoding="utf-8",
    )

    # When reading the persisted note dynamics.
    actual = Mnemosyne(tmp_path, semantic=False).dynamics_of("note")

    # Then valid pair sequences are copied rather than defaulted or rejected.
    assert actual == expected


@pytest.mark.parametrize("raw", [True, 123, [1], "unexpected"])
def test_truthy_non_mapping_zone_dynamics_preserve_errors(
    tmp_path: Path, raw: bool | int | list[int] | str,
) -> None:
    # Given a present zone with the same malformed telemetry HEAD rejected.
    _ = (tmp_path / "note.md").write_text("---\ntitle: note\n---\nnote", encoding="utf-8")
    _ = (tmp_path / DYNAMICS_FILE).write_text(
        json.dumps({"zones": {"": raw}}), encoding="utf-8",
    )
    engine = Mnemosyne(tmp_path, semantic=False)
    _ = engine.entries()

    # When reading zone priorities, then the original get failure remains visible.
    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        _ = engine.zone_priorities()


def test_basic_iso_integer_timestamp_remains_stale(tmp_path: Path) -> None:
    # Given a JSON integer that datetime accepts after HEAD's string conversion.
    _ = (tmp_path / "note.md").write_text("---\ntitle: note\n---\nnote", encoding="utf-8")
    _ = (tmp_path / DYNAMICS_FILE).write_text(json.dumps({
        "notes": {"note": {"strength": 4.0, "stability": 7.0, "last_access": 20200101}},
    }), encoding="utf-8")

    # When the note is evaluated long after its last access.
    actual = Mnemosyne(tmp_path, semantic=False).stale(
        datetime(2026, 10, 3, 12, tzinfo=timezone.utc),
    )

    # Then the persisted value is retained, not filtered out or rewritten.
    assert actual == [{
        "slug": "note", "title": "note", "zone": "",
        "last_access": 20200101, "eff": 0.05,
    }]
