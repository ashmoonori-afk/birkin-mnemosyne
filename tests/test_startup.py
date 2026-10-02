from __future__ import annotations

import json
import os

import pytest

from birkin_mnemosyne.startup import StartupError, StartupReader


def test_complete_context_preserves_frontmatter_blank_bom_crlf_and_last_line(tmp_path):
    raw = "\ufeff---\r\nrole: bootstrap\r\n---\r\n\r\n# Mode\r\nRule: guard\r\n\r\nTail".encode()
    (tmp_path / "MODE.md").write_bytes(raw)
    reader = StartupReader(tmp_path)
    result = reader.read(["MODE.md"])
    assert result.coverage.complete
    assert reader.verify(result.context, ["MODE.md"]).complete
    payload = json.loads(result.context)
    blocks = sorted(payload["blocks"], key=lambda b: b["start_byte"])
    assert "".join(b["text"] for b in blocks).encode() == raw


@pytest.mark.parametrize("mutation", ["drop", "duplicate", "alter", "misattribute", "index"])
def test_verification_rejects_each_returned_context_mutation(tmp_path, mutation):
    (tmp_path / "MODE.md").write_bytes(b"# Mode\nRule: guard\n## Tail\nPending: work\n")
    reader = StartupReader(tmp_path)
    payload = json.loads(reader.read(["MODE.md"]).context)
    if mutation == "drop":
        payload["blocks"].pop()
    elif mutation == "duplicate":
        payload["blocks"].append(payload["blocks"][0])
    elif mutation == "alter":
        payload["blocks"][0]["text"] += "Invented extra text"
    elif mutation == "misattribute":
        payload["blocks"][0]["path"] = "foreign.md"
    elif mutation == "index":
        payload["blocks"][0]["state"] = "invented-authority"
    assert not reader.verify(json.dumps(payload), ["MODE.md"]).complete


def test_fresh_sha_invalidates_same_length_preserved_mtime_without_force(tmp_path):
    path = tmp_path / "MODE.md"
    path.write_bytes(b"# Root\nValue: alpha\n")
    reader = StartupReader(tmp_path)
    before = reader.read(["MODE.md"])
    stat = path.stat()
    path.write_bytes(b"# Root\nValue: omega\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    after = reader.read(["MODE.md"])
    assert not after.cache_hit
    assert "omega" in after.context and "alpha" not in after.context
    assert not reader.verify(before.context, ["MODE.md"]).complete


def test_transitive_refs_relative_to_declarer_and_cycles_include_every_file(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "MODE.md").write_text("MUST READ: profile/soul.md\n", "utf-8")
    (tmp_path / "profile" / "soul.md").write_text("MUST READ: human.md\n", "utf-8")
    (tmp_path / "profile" / "human.md").write_text("MUST READ: ../MODE.md\n", "utf-8")
    result = StartupReader(tmp_path).read(["MODE.md"])
    assert result.coverage.files == 3
    assert {f["path"] for f in json.loads(result.context)["files"]} == {
        "MODE.md", "profile/soul.md", "profile/human.md",
    }


def test_missing_required_file_fails_even_after_cached_complete_read(tmp_path):
    (tmp_path / "MODE.md").write_text("MUST READ: soul.md\n", "utf-8")
    soul = tmp_path / "soul.md"
    soul.write_text("# Soul\n", "utf-8")
    reader = StartupReader(tmp_path)
    reader.read(["MODE.md"])
    soul.unlink()
    with pytest.raises(FileNotFoundError):
        reader.read(["MODE.md"])


def test_fenced_refs_and_top_labels_are_not_live_declarations(tmp_path):
    (tmp_path / "handoff.md").write_text(
        "```\nTOP NOTE 2099-01-01\nMUST READ: missing.md\n```\n"
        "TOP NOTE 2026-09-01\nPort: 11\nTOP NOTE 2026-10-01\nPort: 22\n",
        "utf-8",
    )
    payload = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)
    headings = [b["heading"] for b in payload["blocks"] if b["heading"].startswith("TOP NOTE")]
    assert headings == ["TOP NOTE 2026-10-01", "TOP NOTE 2026-09-01"]
    assert "2099-01-01" in "".join(b["text"] for b in payload["blocks"])


def test_old_material_retained_and_only_explicit_supersession_is_marked(tmp_path):
    (tmp_path / "handoff.md").write_text(
        "## TOP NOTE 2026-09-01\nPort: old\n"
        "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: new\n"
        "## TOP NOTE 2026-09-20\nRule: still binding\n",
        "utf-8",
    )
    blocks = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)["blocks"]
    old = next(b for b in blocks if b["heading"] == "TOP NOTE 2026-09-01")
    retained = next(b for b in blocks if b["heading"] == "TOP NOTE 2026-09-20")
    assert old["state"] == "explicitly-superseded" and "Port: old" in old["text"]
    assert retained["state"] == "source" and "still binding" in retained["text"]


def test_ambiguous_or_invalid_dates_preserve_source_order(tmp_path):
    (tmp_path / "handoff.md").write_text(
        "## TOP NOTE 2026-99-99\nOld: a\n## TOP NOTE unknown\nNew: b\n", "utf-8",
    )
    blocks = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)["blocks"]
    assert [b["heading"] for b in blocks] == ["TOP NOTE 2026-99-99", "TOP NOTE unknown"]


def test_json_registry_exact_coverage_and_required_refs(tmp_path):
    (tmp_path / "registry.json").write_bytes(
        b'\xef\xbb\xbf{"must_read":["MODE.md"],"jobs":[{"active":true,"pending":null}]}',
    )
    (tmp_path / "MODE.md").write_bytes(b"Rule: guard")
    reader = StartupReader(tmp_path)
    result = reader.read(["registry.json"])
    assert result.coverage.files == 2
    assert reader.verify(result.context, ["registry.json"]).complete


def test_invalid_json_and_outside_root_refs_never_produce_complete_claim(tmp_path):
    (tmp_path / "broken.json").write_bytes(b"{invalid")
    with pytest.raises(StartupError, match="invalid JSON"):
        StartupReader(tmp_path).read(["broken.json"])
    (tmp_path / "MODE.md").write_bytes(b"MUST READ: ../outside.md\n")
    with pytest.raises(StartupError, match="outside"):
        StartupReader(tmp_path).read(["MODE.md"])


def test_empty_file_has_one_verified_block_and_duplicate_is_rejected(tmp_path):
    (tmp_path / "empty.md").write_bytes(b"")
    reader = StartupReader(tmp_path)
    payload = json.loads(reader.read(["empty.md"]).context)
    assert reader.verify(json.dumps(payload), ["empty.md"]).complete
    payload["blocks"].append(payload["blocks"][0])
    assert not reader.verify(json.dumps(payload), ["empty.md"]).complete
