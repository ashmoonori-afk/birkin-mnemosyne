"""Normal rewrites retain label ownership and parse source metadata safely."""

from pathlib import Path

import pytest

from birkin_mnemosyne import frontmatter
from birkin_mnemosyne.label_values import LabelError
from birkin_mnemosyne.labels import read_labels
from birkin_mnemosyne.memory import VaultMemory
from birkin_mnemosyne.memory_index import MemoryIndex, MemoryIndexError


def seed(root: Path, labels_line: bytes, *, bom: bool = False) -> tuple[VaultMemory, Path]:
    root.mkdir()
    raw = (
        b"---\r\ntitle: Manual\r\ntype: fact\r\nversion: 3\r\n"
        b'created: 2026-01-02\r\ntags: ["Owner Tag"]\r\nsources: ["owner"]\r\n'
        + labels_line + b"---\r\nOriginal body.\r\n"
    )
    path = root / "manual.md"
    _ = path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + raw)
    return VaultMemory({"vault_path": str(root)}), path


@pytest.mark.parametrize("line", [
    b'labels : [ " Project:Owner  ", topic:Manual ]\r\n',
    b"labels:\r\n",
])
def test_omitted_labels_keep_the_exact_owned_field_line(tmp_path: Path, line: bytes) -> None:
    memory, path = seed(tmp_path / "vault", line)
    expected = read_labels(path.read_bytes())
    _ = memory.write_note("Manual", "Append.", append=True, expected_version=3)
    assert line in path.read_bytes()
    assert read_labels(path.read_bytes()) == expected


def test_bom_source_keeps_tags_sources_version_and_body(tmp_path: Path) -> None:
    memory, path = seed(
        tmp_path / "vault", b'labels: ["project:Owner"]\r\n', bom=True,
    )
    _ = memory.write_note("Manual", "Append.", append=True, expected_version=3)
    meta, body = frontmatter.parse(path.read_text("utf-8"))
    assert meta["tags"] == ["Owner Tag"] and meta["sources"] == ["owner"]
    assert meta["version"] == 4 and meta["created"] == "2026-01-02"
    assert body.strip() == "Original body.\n\nAppend."


def test_malformed_label_block_is_rejected_before_legacy_parse(tmp_path: Path) -> None:
    memory, path = seed(tmp_path / "vault", b"labels:\r\n- project:Owner\r\n")
    before = path.read_bytes()
    with pytest.raises(LabelError):
        _ = memory.write_note("Manual", "Must not write.", append=True)
    assert path.read_bytes() == before


def test_inference_does_not_silently_discard_corrupt_index_context(tmp_path: Path) -> None:
    memory = VaultMemory({"vault_path": str(tmp_path)})
    index = MemoryIndex(tmp_path)
    _ = index.enable()
    damaged = b'{"broken":'
    _ = index.path.write_bytes(damaged)
    with pytest.raises(MemoryIndexError):
        _ = memory.write_note("Fresh", "Body requiring inferred labels.")
    assert not tuple(tmp_path.rglob("*.md"))
    assert index.path.read_bytes() == damaged


def test_owned_labels_do_not_require_new_inference_context(tmp_path: Path) -> None:
    memory, path = seed(tmp_path / "vault", b'labels: ["project:Owner"]\r\n')
    index = MemoryIndex(memory.vault)
    _ = index.enable()
    _ = index.path.write_bytes(b'{"broken":')
    _ = memory.write_note("Manual", "Append.", append=True)
    assert read_labels(path.read_bytes()) == ("project:Owner",)
