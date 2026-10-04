"""On-disk index cache: compressed, lossless, and loaded without re-parsing."""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeAlias

import pytest

from birkin_mnemosyne import mnemosyne

_JsonValue: TypeAlias = str | int | float | bool | None | \
    list["_JsonValue"] | dict[str, "_JsonValue"]
_read_json: Callable[[bytes], _JsonValue] = json.loads

NOTES = {
    "garage": ("car", "the car needs new brake pads\n\nsee [[tax]]"),
    "ramen": ("豚骨スープ", "豚骨スープは十二時間煮込む。細麺を使う。"),
    "kimchi": ("김장", "배추를 소금에 절여 김치를 담근다."),
    "paella": ("Paella", "arroz bomba y azafrán"),
}


def _vault(tmp_path: Path, copies: int = 1) -> Path:
    (tmp_path / "food").mkdir()
    for n in range(copies):
        for i, (slug, (title, body)) in enumerate(NOTES.items()):
            folder = tmp_path / "food" if i % 2 else tmp_path
            name = slug if n == 0 else f"{slug}-{n}"
            _ = (folder / f"{name}.md").write_text(
                f"---\ntitle: {title}\ntags: [a, b]\n---\n\n{body}\n" * (i + 1),
                encoding="utf-8")
    return tmp_path


def test_index_roundtrip_is_lossless(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    first = mnemosyne.Mnemosyne(vault)
    _ = first.rebuild()
    reloaded = mnemosyne.Mnemosyne(vault)
    assert reloaded.entries() == first.entries()
    assert reloaded.search("豚骨")[0]["slug"] == "ramen"
    assert reloaded.search("azafran")[0]["rel"] == "food/paella.md"


def test_index_file_is_compressed_json(tmp_path: Path) -> None:
    vault = _vault(tmp_path, copies=10)
    dex = mnemosyne.Mnemosyne(vault)
    _ = dex.rebuild()
    blob = (vault / mnemosyne.INDEX_FILE).read_bytes()
    assert _read_json(zlib.decompress(blob)) == {
        "version": mnemosyne.INDEX_VERSION, "notes": dex.entries(),
    }
    plain = json.dumps({"version": 3, "notes": dex.entries()}, separators=(",", ":"))
    assert len(blob) < 0.3 * len(plain.encode())


def test_unchanged_notes_are_not_reparsed_on_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    _ = mnemosyne.Mnemosyne(vault).rebuild()

    def boom(_path: Path, rel: str) -> None:
        raise AssertionError(f"re-parsed {rel}")

    monkeypatch.setattr(mnemosyne, "_note_entry", boom)
    assert mnemosyne.Mnemosyne(vault).search("kimchi 배추")


_DAMAGES: Final[tuple[Callable[[bytes], bytes], ...]] = (
    lambda _blob: b"\x78\x01garbage",
    lambda blob: blob[: len(blob) // 2],
    lambda _blob: b"",
    lambda _blob: zlib.compress(b"{not json"),
    lambda _blob: zlib.compress(b"[1, 2]"),
    lambda _blob: zlib.compress("\ud7ff".encode("utf-8")[:1]),
)


@pytest.mark.parametrize("damage", _DAMAGES,
                         ids=["garbage", "truncated", "empty", "not-json", "json-list", "not-utf8"])
def test_corrupt_cache_is_rebuilt(
    tmp_path: Path, damage: Callable[[bytes], bytes],
) -> None:
    vault = _vault(tmp_path)
    _ = mnemosyne.Mnemosyne(vault).rebuild()
    path = vault / mnemosyne.INDEX_FILE
    _ = path.write_bytes(damage(path.read_bytes()))
    assert mnemosyne.Mnemosyne(vault).search("豚骨")[0]["slug"] == "ramen"


@pytest.mark.parametrize(("field", "value"), [
    ("terms", []),
    ("tags", {"invalid": 1}),
    ("title", ["invalid"]),
    ("expires_at", 123),
], ids=["terms-list", "tags-mapping", "title-list", "expiry-number"])
def test_wrong_entry_shapes_are_rebuilt_from_notes(
    tmp_path: Path, field: str, value: str | int | list[str] | dict[str, int],
) -> None:
    # Given a valid cache whose stat-matching entry has one invalid field shape.
    vault = _vault(tmp_path)
    engine = mnemosyne.Mnemosyne(vault)
    _ = engine.rebuild()
    expected = engine.entries()
    corrupted = {**expected["garage"], field: value}
    payload = {"version": mnemosyne.INDEX_VERSION,
               "notes": {**expected, "garage": corrupted}}
    _ = (vault / mnemosyne.INDEX_FILE).write_bytes(
        zlib.compress(json.dumps(payload).encode("utf-8")),
    )

    # When a fresh engine loads the untrusted persisted cache.
    actual = mnemosyne.Mnemosyne(vault).entries()

    # Then invalid cached shapes cannot survive or prevent a complete rebuild.
    assert actual == expected


def test_valid_cache_extensions_survive_loading(tmp_path: Path) -> None:
    # Given valid consumed fields plus metadata from a future cache producer.
    vault = _vault(tmp_path)
    engine = mnemosyne.Mnemosyne(vault)
    _ = engine.rebuild()
    expected = engine.entries()
    extended = {**expected["garage"], "extension": {"values": [1, "extra", None]}}
    expected_notes = {**expected, "garage": extended}
    _ = (vault / mnemosyne.INDEX_FILE).write_bytes(zlib.compress(json.dumps(
        {"version": mnemosyne.INDEX_VERSION, "notes": expected_notes},
    ).encode("utf-8")))

    # When the decoder validates and reloads the actual persisted index.
    actual = mnemosyne.Mnemosyne(vault).entries()

    # Then shape validation preserves unconsumed extension values exactly.
    assert actual == expected_notes


@pytest.mark.parametrize("field", ["created", "expires_at", "terms", "doclen"])
def test_optional_cache_fields_remain_absent(tmp_path: Path, field: str) -> None:
    # Given a stat-matching persisted entry with an optional field omitted.
    vault = _vault(tmp_path)
    engine = mnemosyne.Mnemosyne(vault)
    _ = engine.rebuild()
    notes = _read_json(zlib.decompress((vault / mnemosyne.INDEX_FILE).read_bytes()))
    assert isinstance(notes, dict)
    entries = notes["notes"]
    assert isinstance(entries, dict)
    entry = entries["garage"]
    assert isinstance(entry, dict)
    del entry[field]
    _ = (vault / mnemosyne.INDEX_FILE).write_bytes(
        zlib.compress(json.dumps(notes).encode("utf-8")),
    )

    # When a fresh engine loads the persisted cache without changed sources.
    actual = mnemosyne.Mnemosyne(vault).entries()

    # Then loading preserves the HEAD format instead of silently rebuilding.
    assert field not in actual["garage"]
    assert actual == entries


def test_legacy_json_cache_is_replaced(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _ = (vault / mnemosyne.LEGACY_INDEX_FILE).write_text('{"version": 3, "notes": {}}',
                                                     encoding="utf-8")
    _ = mnemosyne.Mnemosyne(vault).rebuild()
    assert not (vault / mnemosyne.LEGACY_INDEX_FILE).exists()
    assert (vault / mnemosyne.INDEX_FILE).exists()
