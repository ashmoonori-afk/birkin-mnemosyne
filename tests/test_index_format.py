"""On-disk index format: compact, lossless, and loaded without re-parsing."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_varint_roundtrip():
    pairs = [(0, 1), (5, 2), (127, 1), (128, 300), (70000, 1), (2**31, 9)]
    assert mnemosyne._unpack_postings(mnemosyne._pack_postings(pairs)) == pairs


def test_index_roundtrip_is_lossless(tmp_path):
    vault = _vault(tmp_path)
    first = mnemosyne.Mnemosyne(vault)
    first.rebuild()
    reloaded = mnemosyne.Mnemosyne(vault)
    assert reloaded.entries() == first.entries()
    assert reloaded.search("豚骨")[0]["slug"] == "ramen"
    assert reloaded.search("azafran")[0]["rel"] == "food/paella.md"


def test_index_file_is_compact_utf8(tmp_path):
    vault = _vault(tmp_path, copies=10)
    dex = mnemosyne.Mnemosyne(vault)
    dex.rebuild()
    raw = (vault / mnemosyne.INDEX_FILE).read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["version"] == mnemosyne.INDEX_VERSION
    assert "\\u" not in raw and "豚骨" in data["vocab"]
    plain = json.dumps({"version": 2, "notes": dex.entries()}, separators=(",", ":"))
    assert len(raw.encode()) < 0.6 * len(plain.encode())


def test_unchanged_notes_are_not_reparsed_on_load(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault).rebuild()

    def boom(path, rel):
        raise AssertionError(f"re-parsed {rel}")

    monkeypatch.setattr(mnemosyne, "_note_entry", boom)
    assert mnemosyne.Mnemosyne(vault).search("kimchi 배추")


def test_corrupt_postings_fall_back_to_rebuild(tmp_path):
    vault = _vault(tmp_path)
    mnemosyne.Mnemosyne(vault).rebuild()
    path = vault / mnemosyne.INDEX_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["notes"].values():
        row[len(data["fields"])] = "!!not base64!!"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert mnemosyne.Mnemosyne(vault).search("豚骨")[0]["slug"] == "ramen"
