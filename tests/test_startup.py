from __future__ import annotations

import json
import os

import pytest

from birkin_mnemosyne.startup import StartupError, StartupReader


def test_bom_only_startup_file_retains_its_single_source_line(tmp_path):
    raw = "\ufeff".encode()
    (tmp_path / "MODE.md").write_bytes(raw)
    reader = StartupReader(tmp_path)
    result = reader.read(["MODE.md"])
    assert result.coverage.complete
    assert result.coverage.lines == 1
    payload = json.loads(result.context)
    assert "".join(block["text"] for block in payload["blocks"]).encode() == raw
    assert reader.verify(result.context, ["MODE.md"]).complete


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


def test_bom_first_required_reference_is_live_and_preserves_bytes(tmp_path):
    raw = "\ufeffMUST READ: soul.md\n".encode()
    (tmp_path / "MODE.md").write_bytes(raw)
    reader = StartupReader(tmp_path)
    with pytest.raises(FileNotFoundError):
        reader.read(["MODE.md"])
    (tmp_path / "soul.md").write_bytes(b"# Soul\n")
    result = reader.read(["MODE.md"])
    assert result.coverage.files == 2
    assert reader.verify(result.context, ["MODE.md"]).complete
    blocks = json.loads(result.context)["blocks"]
    assert "".join(b["text"] for b in blocks if b["path"] == "MODE.md").encode() == raw


def test_bom_first_fence_ignores_example_but_follows_real_reference(tmp_path):
    raw = "\ufeff```\nMUST READ: missing-example.md\n```\nMUST READ: real.md\n".encode()
    (tmp_path / "MODE.md").write_bytes(raw)
    reader = StartupReader(tmp_path)
    with pytest.raises(FileNotFoundError) as error:
        reader.read(["MODE.md"])
    assert error.value.filename == str(tmp_path / "real.md")
    (tmp_path / "real.md").write_bytes(b"# Real\n")
    result = reader.read(["MODE.md"])
    assert result.coverage.files == 2
    assert reader.verify(result.context, ["MODE.md"]).complete
    blocks = json.loads(result.context)["blocks"]
    assert "".join(b["text"] for b in blocks if b["path"] == "MODE.md").encode() == raw


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


@pytest.mark.parametrize(("old_heading", "child_heading", "boundary_heading"), [
    ("# TOP NOTE", "## Detail", "# Global safety"),
    ("## TOP NOTE", "### Detail", "# Global safety"),
    ("TOP NOTE", "### Detail", "## Global safety"),
])
def test_note_scope_excludes_peer_and_ancestor_sections(
    tmp_path, old_heading, child_heading, boundary_heading,
):
    (tmp_path / "handoff.md").write_text(
        f"{old_heading} 2026-09-01\nPort: old\n{child_heading}\nPending: old\n"
        f"{boundary_heading}\nRule: always ask\n### Global exception\nRule: still ask\n"
        "## TOP NOTE 2026-10-01\nSupersedes: TOP NOTE 2026-09-01\nPort: new\n"
        "## TOP NOTE 2026-10-02\nPort: newest\n",
        "utf-8",
    )
    reader = StartupReader(tmp_path)
    result = reader.read(["handoff.md"])
    blocks = json.loads(result.context)["blocks"]
    assert [b["heading"] for b in blocks] == [
        "TOP NOTE 2026-09-01", "Detail", "Global safety", "Global exception",
        "TOP NOTE 2026-10-02", "TOP NOTE 2026-10-01",
    ]
    assert [b["state"] for b in blocks] == [
        "explicitly-superseded", "explicitly-superseded", "source", "source",
        "source", "source",
    ]
    assert reader.verify(result.context, ["handoff.md"]).complete


def test_independent_section_cannot_declare_note_supersession(tmp_path):
    (tmp_path / "handoff.md").write_text(
        "# TOP NOTE 2026-09-01\nPort: old\n"
        "# Global safety\nSupersedes: TOP NOTE 2026-09-01\n"
        "# TOP NOTE 2026-10-01\nPort: new\n",
        "utf-8",
    )
    blocks = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)["blocks"]
    assert [b["heading"] for b in blocks] == [
        "TOP NOTE 2026-09-01", "Global safety", "TOP NOTE 2026-10-01",
    ]
    assert all(b["state"] == "source" for b in blocks)


def test_ambiguous_or_invalid_dates_preserve_source_order(tmp_path):
    (tmp_path / "handoff.md").write_text(
        "## TOP NOTE 2026-99-99\nOld: a\n## TOP NOTE unknown\nNew: b\n", "utf-8",
    )
    blocks = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)["blocks"]
    assert [b["heading"] for b in blocks] == ["TOP NOTE 2026-99-99", "TOP NOTE unknown"]


@pytest.mark.parametrize(("older", "newer"), [
    ("2026-10-01", "2026-10-02"),
    ("2026-10-02T10:00Z", "2026-10-02T10:01Z"),
    ("2026-10-02T10:00:00Z", "2026-10-02T10:00:30Z"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_compatible_timestamps_sort_chronologically(tmp_path, older, newer, reverse):
    stamps = [older, newer]
    if reverse:
        stamps.reverse()
    (tmp_path / "handoff.md").write_text(
        "".join(f"## TOP NOTE {stamp}\nValue: {i}\n" for i, stamp in enumerate(stamps)),
        "utf-8",
    )
    reader = StartupReader(tmp_path)
    result = reader.read(["handoff.md"])
    blocks = json.loads(result.context)["blocks"]
    assert [b["heading"] for b in blocks] == [f"TOP NOTE {newer}", f"TOP NOTE {older}"]
    assert reader.verify(result.context, ["handoff.md"]).complete


@pytest.mark.parametrize("stamps", [
    ["2026-10-02T10:00Z", "2026-10-02T10:00:30Z"],
    ["2026-10-02T10:00:30Z", "2026-10-02T10:00Z"],
    ["2026-10-02", "2026-10-02T10:00Z"],
    ["2026-10-02T10:00Z", "2026-10-02"],
    ["2026-10-02T10:00Z", "2026-10-02T10:00:00Z", "2026-10-03T10:00Z"],
    ["2026-10-02T10:00:00Z", "2026-10-02T10:00Z", "2026-10-03T10:00Z"],
    ["2026-10-02T10:00Z", "2026-10-03T10:00Z", "2026-10-02T10:00Z"],
])
def test_mixed_precision_or_equivalent_instants_preserve_source_order(tmp_path, stamps):
    headings = [f"TOP NOTE {stamp} entry {i}" for i, stamp in enumerate(stamps)]
    (tmp_path / "handoff.md").write_text(
        "".join(f"## {heading}\nValue: {i}\n" for i, heading in enumerate(headings)),
        "utf-8",
    )
    blocks = json.loads(StartupReader(tmp_path).read(["handoff.md"]).context)["blocks"]
    assert [b["heading"] for b in blocks] == headings


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


@pytest.mark.parametrize("raw", [
    b'{"must_read":[],"pending":NaN}',
    b'{"must_read":[],"pending":Infinity}',
    b'{"must_read":[],"pending":-Infinity}',
    b'{"must_read":["missing.md"],"must_read":[]}',
    b'{"must_read":["missing.md"],"must\\u005fread":[]}',
    b'{"must_read":[],"jobs":{"must_read":["missing.md"],"must_read":[]}}',
    b'{"must_read":[],"pending":true,"pending":false}',
])
@pytest.mark.parametrize("cached", [False, True])
def test_invalid_json_boundary_fails_before_and_after_cache(tmp_path, raw, cached):
    registry = tmp_path / "registry.json"
    reader = StartupReader(tmp_path)
    previous = None
    if cached:
        registry.write_bytes(b'{"must_read":["MODE.md"],"pending":null}')
        (tmp_path / "MODE.md").write_bytes(b"# Mode\nRule: guard\n")
        previous = reader.read(["registry.json"])
        assert previous.coverage.files == 2
        assert reader.read(["registry.json"]).cache_hit
    registry.write_bytes(raw)
    with pytest.raises(StartupError, match="invalid JSON"):
        reader.read(["registry.json"])
    if previous is not None:
        with pytest.raises(StartupError, match="invalid JSON"):
            reader.verify(previous.context, ["registry.json"])


def test_empty_file_has_one_verified_block_and_duplicate_is_rejected(tmp_path):
    (tmp_path / "empty.md").write_bytes(b"")
    reader = StartupReader(tmp_path)
    payload = json.loads(reader.read(["empty.md"]).context)
    assert reader.verify(json.dumps(payload), ["empty.md"]).complete
    payload["blocks"].append(payload["blocks"][0])
    assert not reader.verify(json.dumps(payload), ["empty.md"]).complete


@pytest.mark.parametrize("relative", [
    ".mnemosyne-reviews/x.json", ".env", "sub/.hidden.md", "sub/../.env",
])
def test_startup_refuses_hidden_and_dot_paths(tmp_path, relative):
    for target in (".mnemosyne-reviews/x.json", ".env", "sub/.hidden.md"):
        (tmp_path / target).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / target).write_text(
            '{"jobs": []}' if target.endswith(".json") else "secret\n", encoding="utf-8")
    with pytest.raises(StartupError, match="refusing hidden path") as caught:
        StartupReader(tmp_path).read([relative])
    assert str(tmp_path) not in str(caught.value)


def test_startup_refuses_hidden_file_reached_through_must_read(tmp_path):
    (tmp_path / "MODE.md").write_text("MUST READ: .env\n# Mode\n", encoding="utf-8")
    (tmp_path / ".env").write_text("secret\n", encoding="utf-8")
    with pytest.raises(StartupError):
        StartupReader(tmp_path).read(["MODE.md"])


def test_startup_still_reads_normal_files(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Agent\nrule\n", encoding="utf-8")
    assert StartupReader(tmp_path).read(["AGENTS.md"]).coverage.complete
