"""Onboarding previews preserve original bytes and stable path identities."""

from pathlib import Path

import pytest

from birkin_mnemosyne import frontmatter
from birkin_mnemosyne.memory_index import MemoryIndexError
from birkin_mnemosyne.onboarding_notes import (
    SourceBytes,
    catalogue,
    complete_header,
    describe_note,
    generated_catalogue,
    inventory,
)


@pytest.mark.parametrize("body", [
    b"Rule without final newline",
    "한국어 규칙\r\n日本語のメモ".encode(),
    b"\xef\xbb\xbf# Policy\r\nNo final newline",
    b"",
])
def test_missing_frontmatter_retains_complete_body_bytes(body: bytes) -> None:
    # Given an unnormalized source with its original byte framing.
    source = SourceBytes("knowledge/policy.md", body)

    # When missing metadata is completed.
    after, additions, warning = complete_header(source)

    # Then metadata parses and the complete body remains byte-exact.
    meta, _ = frontmatter.parse(after.decode())
    assert meta["title"] == "policy"
    assert meta["type"] == "topic" and meta["tags"] == []
    assert additions == ("title", "type", "tags") and warning is None
    assert after.endswith(body.removeprefix(b"\xef\xbb\xbf"))


def test_existing_header_fields_comments_and_body_are_preserved() -> None:
    # Given unfamiliar metadata, CRLF framing and a body without final newline.
    raw = (
        b'---\r\ntitle: "Original"\r\n# Keep this comment\r\n'
        b'metadata:\r\n  folder: "D:\\notes\\todo"\r\n'
        b"polarity: negative\r\n---\r\n\r\nOriginal body."
    )

    # When absent fields are completed.
    after, additions, warning = complete_header(SourceBytes("policy.md", raw))

    # Then existing header bytes and original body framing are unchanged.
    assert after == raw.replace(b"---\r\n\r\nOriginal", b"type: topic\r\ntags: []\r\n---\r\n\r\nOriginal")
    assert additions == ("type", "tags") and warning is None


@pytest.mark.parametrize("raw", [
    b"---\ntitle: First\ntitle: Second\n---\nRule",
    b"---\ntitle: First\ntitle : Second\n---\nRule",
    b'---\n"title": Owner title\n---\nRule',
    b"---\nmetadata: &shared\n  value: x\n---\nRule",
    b"---\n<<: *shared\n---\nRule",
    b"---\ntitle: Missing closing delimiter",
])
def test_ambiguous_headers_are_retained_without_additions(raw: bytes) -> None:
    # Given metadata that cannot safely be completed.
    source = SourceBytes("policy.md", raw)

    # When the preview inspects it.
    after, additions, warning = complete_header(source)

    # Then it is explicitly excluded without modifying any bytes.
    assert after == raw and additions == () and warning is not None


def test_receipt_protected_source_is_never_normalized() -> None:
    # Given exact bytes bound by an existing coverage receipt.
    source = SourceBytes("topics/original.md", b"Original rule.")

    # When a protected source is described for grouping.
    note = describe_note(source, protected=True)

    # Then its exact bytes are retained and the exclusion is reported.
    assert note.normalized == source.raw and note.additions == ()
    assert note.warning is not None


@pytest.mark.parametrize("separator", [b" :", b"\t:"])
def test_equivalent_header_keys_preserve_owner_metadata(separator: bytes) -> None:
    # Given an existing plain key with whitespace before its colon.
    raw = b"---\ntitle" + separator + b" Owner title\n---\nOwner body."

    # When absent metadata is completed.
    after, additions, warning = complete_header(SourceBytes("policy.md", raw))

    # Then the existing title is not duplicated or overridden.
    assert frontmatter.parse(after.decode())[0]["title"] == "Owner title"
    assert additions == ("type", "tags") and warning is None
    assert b"title: " not in after and after.endswith(b"Owner body.")


def test_catalogue_is_stable_across_normalization_and_body_edits() -> None:
    # Given the same path/title/topic with changing body and header completeness.
    first = describe_note(SourceBytes("knowledge/policy.md", b"Original body."))
    second = describe_note(SourceBytes("knowledge/policy.md", first.normalized + b"\nMore detail."))

    # When topic catalogues are rendered.
    before, after = catalogue(first.topic, (first,)), catalogue(second.topic, (second,))

    # Then unrelated source content changes do not multiply derived documents.
    assert before == after
    assert generated_catalogue(before)


def test_edited_generated_catalogue_is_a_collision() -> None:
    # Given a generated catalogue edited outside onboarding.
    note = describe_note(SourceBytes("policy.md", b"Rule."))
    created = catalogue(note.topic, (note,))
    edited = SourceBytes(created.path, created.raw + b"Owner edits.")

    # When onboarding tries to recognize it.
    with pytest.raises(MemoryIndexError):
        generated_catalogue(edited)


def test_recursive_inventory_preserves_equal_basenames_without_writes(tmp_path: Path) -> None:
    # Given distinct nested paths and excluded infrastructure.
    for relative in ("a/deep/policy.md", "b/deep/policy.md", ".hidden/old.md", "_archive/old.md"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
              for path in tmp_path.rglob("*.md")}

    # When the source tree is inventoried.
    sources = inventory(tmp_path)

    # Then both active identities survive and all file bytes/mtimes are unchanged.
    assert [source.path for source in sources] == ["a/deep/policy.md", "b/deep/policy.md"]
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in tmp_path.rglob("*.md")} == before
