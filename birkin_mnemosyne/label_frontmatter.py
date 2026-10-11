"""Byte-level frontmatter inspection and label-field edits.

Only whole lines are spliced.  Every byte outside the edited line (or the
added header) is kept verbatim — BOM, CRLF framing, comments, other header
keys and the complete body.  Ambiguous or unreadable headers stay unchanged
and are reported as a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

BOM: Final = b"\xef\xbb\xbf"
LABELS_KEY: Final = b"labels"
HEADER_KEY: Final = re.compile(rb"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:")
AMBIGUOUS_YAML: Final = re.compile(rb"^\s*(?:<<:|[^#:\r\n]+:\s*[&*!])", re.MULTILINE)
EXTRA_LINE_BREAK: Final = re.compile(rb"[\x0b\x0c\x1c-\x1e]|\xc2\x85|\xe2\x80[\xa8\xa9]")


@dataclass(frozen=True, slots=True)
class HeaderScan:
    present: bool
    closed: bool
    lines: tuple[bytes, ...]
    close_index: int
    labels_index: int | None
    labels_empty_scalar: bool
    labels_multiline: bool
    duplicate_keys: bool
    anchor_ambiguous: bool
    header_keys: tuple[str, ...]
    unsupported: bool = False


def inspect(raw: bytes) -> HeaderScan:
    """Describe the frontmatter structure of ``raw`` without parsing it."""
    lines = raw.splitlines(keepends=True)
    if not lines:
        return HeaderScan(False, False, (), -1, None, False, False, False, False, ())
    first = lines[0].removeprefix(BOM).rstrip(b"\r\n")
    if first != b"---":
        return HeaderScan(False, False, tuple(lines), -1, None, False, False, False, False, ())
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip(b"\r\n") == b"---"), -1)
    if close < 0:
        return HeaderScan(True, False, tuple(lines), -1, None, False, False, False, False, ())
    header = lines[1:close]
    keys: list[str] = []
    labels_index: int | None = None
    labels_empty_scalar = False
    labels_multiline = False
    unsupported = False
    for offset, line in enumerate(header):
        stripped = line.strip()
        if not stripped or stripped.startswith(b"#"):
            continue
        matched = HEADER_KEY.match(line)
        if matched is None:
            if line[:1] not in (b" ", b"\t"):
                unsupported = True
            continue
        key = matched[1].decode("ascii")
        keys.append(key)
        rest = line[matched.end():].strip(b" \t\r\n")
        if rest.startswith((b"|", b">")):
            unsupported = True
        if key != LABELS_KEY.decode("ascii"):
            continue
        labels_index = offset + 1
        if rest and not rest.startswith(b"#"):
            continue
        following = next((
            item for item in header[offset + 1:]
            if item.strip() and not item.lstrip().startswith(b"#")
        ), b"")
        labels_multiline = following[:1] in (b" ", b"\t") or following.startswith(b"- ")
        labels_empty_scalar = not labels_multiline
    joined = b"".join(header)
    return HeaderScan(
        present=True,
        closed=True,
        lines=tuple(lines),
        close_index=close,
        labels_index=labels_index,
        labels_empty_scalar=labels_empty_scalar,
        labels_multiline=labels_multiline,
        duplicate_keys=len(keys) != len(set(keys)),
        anchor_ambiguous=AMBIGUOUS_YAML.search(joined) is not None,
        header_keys=tuple(keys),
        unsupported=unsupported or EXTRA_LINE_BREAK.search(joined) is not None,
    )


def apply_label_edit(raw: bytes, rendered: str) -> tuple[bytes, str | None]:
    """Write the labels field described by ``rendered`` (an inline YAML list).

    Returns ``(edited_raw, warning)``.  Unclosed, duplicate-key or
    anchor-ambiguous frontmatter, and multiline label values, are left
    unchanged with a warning instead of a guessed rewrite.
    """
    payload = f"labels: {rendered}".encode("utf-8")
    scan = inspect(raw)
    if not scan.present:
        return _add_header(raw, payload), None
    if not scan.closed:
        return raw, "unterminated frontmatter retained"
    if scan.duplicate_keys or scan.anchor_ambiguous or scan.unsupported:
        return raw, "ambiguous frontmatter retained"
    if scan.labels_index is None:
        return _insert_line(raw, scan.close_index, payload), None
    if scan.labels_multiline:
        return raw, "multiline labels field retained"
    return _replace_line(raw, scan.labels_index, payload), None


def scoring_text(raw: bytes) -> str:
    """Decode retrieval input without letting a label field create terms/links.

    Keep all other metadata and body content. Invalid label blocks are excluded
    too: the strict label reader rejects them separately, while ordinary recall
    must not fail because the legacy parser cannot parse that block.
    """
    scan = inspect(raw)
    if scan.present and scan.closed:
        lines = [scan.lines[0]]
        in_labels = False
        for line in scan.lines[1:scan.close_index]:
            matched = HEADER_KEY.match(line)
            if matched is not None:
                in_labels = matched[1] == LABELS_KEY
            if not in_labels:
                lines.append(line)
        lines.extend(scan.lines[scan.close_index:])
        raw = b"".join(lines)
    # Match read_text's existing universal-newline retrieval representation.
    return raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _line_eol(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    return b"\r" if line.endswith(b"\r") else b"\n"


def _dominant_eol(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    return _line_eol(lines[0]) if lines else b"\n"


def _add_header(raw: bytes, payload: bytes) -> bytes:
    eol = _dominant_eol(raw)
    header = b"---" + eol + payload + eol + b"---" + eol
    if raw.startswith(BOM):
        return BOM + header + raw[len(BOM):]
    return header + raw


def _insert_line(raw: bytes, close: int, payload: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    eol = _dominant_eol(raw)
    return b"".join(lines[:close]) + payload + eol + b"".join(lines[close:])


def _replace_line(raw: bytes, index: int, payload: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    lines[index] = payload + _line_eol(lines[index])
    return b"".join(lines)
