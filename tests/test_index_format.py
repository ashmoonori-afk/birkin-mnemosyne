"""On-disk index cache: compressed, lossless, and loaded without re-parsing."""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

from birkin_mnemosyne import mnemosyne

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
            (folder / f"{name}.md").write_text(
                f"---\ntitle: {title}\ntags: [a, b]\n---\n\n{body}\n" * (i + 1),
                encoding="utf-8")
    return tmp_path


def test_index_roundtrip_is_lossless(tmp_path):
    vault = _vault(tmp_path)
    first = mnemosyne.Mnemosyne(vault)
    first.rebuild()
    reloaded = mnemosyne.Mnemosyne(vault)
    assert reloaded.entries() == first.entries()
    assert reloaded.search("豚骨")[0]["slug"] == "ramen"
    assert reloaded.search("azafran")[0]["rel"] == "food/paella.md"


def test_index_file_is_compressed_json(tmp_path):
    vault = _vault(tmp_path, copies=10)
    dex = mnemosyne.Mnemosyne(vault)
    dex.rebuild()
    blob = (vault / mnemosyne.INDEX_FILE).read_bytes()
    assert mnemosyne._decode_index(blob) == dex.entries()
    plain = json.dumps({"version": 3, "notes": dex.entries()}, separators=(",", ":"))
    assert len(blob) < 0.3 * len(plain.encode())


def test_unchanged_notes_are_not_reparsed_on_load(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault).rebuild()

    def boom(path, rel):
        raise AssertionError(f"re-parsed {rel}")

    monkeypatch.setattr(mnemosyne, "_note_entry", boom)
    assert mnemosyne.Mnemosyne(vault).search("kimchi 배추")


@pytest.mark.parametrize("damage", [
    lambda blob: b"\x78\x01garbage",
    lambda blob: blob[: len(blob) // 2],
    lambda blob: b"",
    lambda blob: zlib.compress(b"{not json"),
    lambda blob: zlib.compress(b"[1, 2]"),
    lambda blob: zlib.compress("\ud7ff".encode("utf-8")[:1]),
], ids=["garbage", "truncated", "empty", "not-json", "json-list", "not-utf8"])
def test_corrupt_cache_is_rebuilt(tmp_path, damage):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault).rebuild()
    path = vault / mnemosyne.INDEX_FILE
    path.write_bytes(damage(path.read_bytes()))
    assert mnemosyne.Mnemosyne(vault).search("豚骨")[0]["slug"] == "ramen"


def test_legacy_json_cache_is_replaced(tmp_path):
    vault = _vault(tmp_path)
    (vault / mnemosyne.LEGACY_INDEX_FILE).write_text('{"version": 3, "notes": {}}',
                                                     encoding="utf-8")
    mnemosyne.Mnemosyne(vault).rebuild()
    assert not (vault / mnemosyne.LEGACY_INDEX_FILE).exists()
    assert (vault / mnemosyne.INDEX_FILE).exists()
